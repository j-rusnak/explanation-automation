from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from techshort.audio.providers import (
    NarrationSynthesisReceipt,
    NarrationVoice,
    SynthesizedNarration,
    derive_synthesis_id,
)
from techshort.audio.service import (
    active_audio,
    active_transcript,
    import_audio,
    import_transcript,
    probe_duration,
)
from techshort.domain.hashing import sha256_bytes, sha256_file
from techshort.domain.models import AssetManifest, ReviewStatus, ScriptManifest
from techshort.domain.storage import (
    ProjectStore,
    atomic_copy_file,
    atomic_write_model,
    load_model,
)

SAPI_PROVIDER_ID = "windows-sapi"
SAPI_TIMEOUT_SECONDS = 120
NORMALIZATION_TIMEOUT_SECONDS = 120
MAX_SYNTHESIS_TEXT_BYTES = 128 * 1024
SILENCE_EVENT = re.compile(r"silence_(start|end):\s*(-?\d+(?:\.\d+)?)")


class LocalNarrationUnavailable(RuntimeError):
    """Raised when a supported, zero-cost local speech engine is unavailable."""


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _sapi_script_path() -> Path:
    script = (_repository_root() / "scripts" / "synthesize_sapi.ps1").resolve()
    if not script.is_file():
        raise LocalNarrationUnavailable(
            "the repository-owned System.Speech helper is missing; restore "
            "scripts/synthesize_sapi.ps1"
        )
    return script


def _powershell_executable() -> str:
    if platform.system() != "Windows":
        raise LocalNarrationUnavailable(
            "local System.Speech narration is available only on Windows; import a recording "
            "or explicitly use silent-reviewed mode on this platform"
        )
    executable = shutil.which("powershell.exe") or shutil.which("powershell")
    if not executable:
        raise LocalNarrationUnavailable(
            "Windows PowerShell is required for local System.Speech narration but was not found"
        )
    return executable


def _run_sapi(arguments: list[str], *, timeout: int = SAPI_TIMEOUT_SECONDS) -> str:
    command = [
        _powershell_executable(),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(_sapi_script_path()),
        *arguments,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise LocalNarrationUnavailable(
            f"local System.Speech narration exceeded its {timeout}-second safety timeout"
        ) from exc
    except OSError as exc:
        raise LocalNarrationUnavailable(
            f"Windows PowerShell could not start local narration: {type(exc).__name__}"
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().replace("\x00", "")[-1000:]
        raise LocalNarrationUnavailable(
            "local System.Speech narration failed"
            + (f": {detail}" if detail else f" with exit code {result.returncode}")
        )
    return result.stdout.strip().lstrip("\ufeff")


def _voice_from_payload(value: Any) -> NarrationVoice:
    if not isinstance(value, dict) or set(value) != {"name", "culture", "gender", "age"}:
        raise LocalNarrationUnavailable("System.Speech returned malformed voice metadata")
    fields = {key: value[key] for key in ("name", "culture", "gender", "age")}
    if not all(isinstance(item, str) and item.strip() for item in fields.values()):
        raise LocalNarrationUnavailable("System.Speech returned incomplete voice metadata")
    return NarrationVoice(provider=SAPI_PROVIDER_ID, **fields)


def discover_windows_voices() -> list[NarrationVoice]:
    """Return enabled Windows voices in a stable order."""

    output = _run_sapi(["-Action", "list"], timeout=20)
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise LocalNarrationUnavailable("System.Speech returned invalid voice metadata") from exc
    if not isinstance(payload, list):
        raise LocalNarrationUnavailable("System.Speech returned malformed voice metadata")
    voices = [_voice_from_payload(item) for item in payload]
    if not voices:
        raise LocalNarrationUnavailable(
            "Windows System.Speech has no enabled voices; install a Windows speech voice "
            "or import a recording"
        )
    return sorted(voices, key=lambda voice: (voice.culture.lower(), voice.name.lower()))


def _default_voice(voices: list[NarrationVoice]) -> NarrationVoice:
    return next(
        (voice for voice in voices if voice.culture.lower().startswith("en-us")),
        next((voice for voice in voices if voice.culture.lower().startswith("en")), voices[0]),
    )


def local_narration_readiness() -> tuple[bool, str]:
    try:
        voices = discover_windows_voices()
    except LocalNarrationUnavailable as exc:
        return False, str(exc)
    default = _default_voice(voices)
    return (
        True,
        f"{len(voices)} enabled Windows System.Speech voice(s); default is {default.name} "
        f"({default.culture})",
    )


def _approved_script_text(store: ProjectStore) -> str:
    script_path = store.path("script/script.json")
    if not script_path.is_file():
        raise ValueError("generate and approve a script before synthesizing narration")
    script = load_model(script_path, ScriptManifest)
    project = store.project()
    if (
        project.active_versions.get("script") != script.version_id
        or project.approvals.script != ReviewStatus.APPROVED
    ):
        raise ValueError("the active script must have a current human approval before synthesis")

    # Imported lazily: review itself resolves active audio through techshort.audio.
    from techshort.review import has_current_approval

    if any(
        segment.review_status != ReviewStatus.APPROVED
        or not has_current_approval(store, "script-segment", segment.segment_id)
        for segment in script.segments
    ):
        raise ValueError(
            "every active script segment must have a current approval before synthesis"
        )
    # Each approved segment becomes one plain-text line. The trusted helper maps
    # line boundaries to a fixed pause through PromptBuilder; project text never
    # becomes SSML or code.
    text = "\n".join(" ".join(segment.text.split()) for segment in script.segments).strip()
    encoded = text.encode("utf-8")
    if not text:
        raise ValueError("the approved script has no narration text")
    if len(encoded) > MAX_SYNTHESIS_TEXT_BYTES:
        raise ValueError("approved narration exceeds the 128 KiB local synthesis safety limit")
    if "\x00" in text:
        raise ValueError("approved narration may not contain NUL bytes")
    return text


def _write_synthesis_receipt(store: ProjectStore, receipt: NarrationSynthesisReceipt) -> Path:
    destination = store.path("audio/narration-synthesis.json")
    if destination.is_file():
        previous = load_model(destination, NarrationSynthesisReceipt)
        if previous == receipt:
            return destination
        versions = store.path("audio/synthesis-versions")
        versions.mkdir(parents=True, exist_ok=True)
        archived = versions / f"{previous.synthesis_id}.json"
        if archived.is_file() and sha256_file(archived) != sha256_file(destination):
            archived = versions / f"{previous.synthesis_id}-{sha256_file(destination)[:12]}.json"
        if not archived.exists():
            atomic_copy_file(destination, archived)
        elif sha256_file(archived) != sha256_file(destination):
            raise ValueError("synthesis receipt archive collision")
    atomic_write_model(destination, receipt)
    return destination


def active_synthesis_receipt(
    store: ProjectStore,
) -> tuple[NarrationSynthesisReceipt, Path] | None:
    """Resolve and verify the receipt, approved script, audio, and transcript bytes."""

    project = store.project()
    synthesis_id = project.active_versions.get("narration_synthesis")
    expected_receipt_hash = project.dependency_hashes.get("narration_synthesis")
    if synthesis_id is None and expected_receipt_hash is None:
        return None
    if not synthesis_id or not expected_receipt_hash:
        raise ValueError("active narration synthesis metadata is incomplete; synthesize again")
    path = store.path("audio/narration-synthesis.json")
    if not path.is_file() or sha256_file(path) != expected_receipt_hash:
        raise ValueError("active narration synthesis receipt is missing or changed")
    receipt = load_model(path, NarrationSynthesisReceipt)
    if receipt.synthesis_id != synthesis_id:
        raise ValueError("active narration synthesis receipt ID does not match the project")

    narration = active_audio(store)
    if narration is None or narration != store.path(receipt.output_path):
        raise ValueError("synthesis receipt does not match the active narration path")
    if sha256_file(narration) != receipt.output_hash:
        raise ValueError("synthesis receipt does not match the active narration bytes")
    transcript = active_transcript(store)
    if transcript is None or sha256_file(transcript[1]) != receipt.transcript_hash:
        raise ValueError("synthesis receipt does not match the active narration transcript")

    script_path = store.path("script/script.json")
    script = load_model(script_path, ScriptManifest)
    text = _approved_script_text(store)
    segment_hashes = {
        segment.segment_id: segment.approval_hash
        for segment in script.segments
        if segment.approval_hash is not None
    }
    if (
        script.version_id != receipt.script_version_id
        or sha256_file(script_path) != receipt.script_hash
        or sha256_bytes(text.encode("utf-8")) != receipt.script_text_hash
        or segment_hashes != receipt.segment_approval_hashes
    ):
        raise ValueError("synthesis receipt does not match the currently approved script")
    duration = probe_duration(narration)
    if duration is None or abs(duration - receipt.output_duration_seconds) > 0.05:
        raise ValueError("synthesis receipt does not match the active narration duration")
    return receipt, path


def _silence_trim_bounds(log: str, duration: float) -> tuple[float, float]:
    """Find only leading/trailing silence, preserving all pauses within narration."""

    intervals: list[tuple[float, float]] = []
    current_start: float | None = None
    for match in SILENCE_EVENT.finditer(log):
        value = float(match.group(2))
        if match.group(1) == "start":
            current_start = value
        elif current_start is not None:
            intervals.append((current_start, value))
            current_start = None
    if current_start is not None:
        intervals.append((current_start, duration))

    start = 0.0
    end = duration
    if intervals and intervals[0][0] <= 0.02:
        start = max(0.0, intervals[0][1] - 0.03)
    if intervals and duration - intervals[-1][1] <= 0.1:
        end = min(duration, intervals[-1][0] + 0.03)
    if end - start < 0.1:
        return 0.0, duration
    return start, end


def _detect_silence(ffmpeg: str, source: Path) -> str:
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "info",
                "-nostdin",
                "-i",
                str(source),
                "-af",
                "silencedetect=noise=-55dB:d=0.04",
                "-f",
                "null",
                os.devnull,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stderr if result.returncode == 0 else ""


def _normalize_audio(source: Path, destination: Path) -> None:
    # Keep renderer startup out of audio package import time. The rendering
    # package imports review services, which in turn resolve active audio.
    from techshort.rendering.tools import media_tool

    ffmpeg = media_tool("ffmpeg")
    if not ffmpeg:
        raise LocalNarrationUnavailable(
            "FFmpeg is required to trim and normalize synthesized narration; install FFmpeg "
            "and retry"
        )
    duration = probe_duration(source)
    if duration is None:
        raise LocalNarrationUnavailable("FFprobe could not validate raw synthesized narration")
    start, end = _silence_trim_bounds(_detect_silence(ffmpeg, source), duration)
    audio_filters = (
        f"atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS,loudnorm=I=-16:TP=-1.5:LRA=11"
    )
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(source),
                "-af",
                audio_filters,
                "-ar",
                "48000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(destination),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=NORMALIZATION_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LocalNarrationUnavailable(
            f"FFmpeg could not normalize synthesized narration: {type(exc).__name__}"
        ) from exc
    if result.returncode != 0 or not destination.is_file() or destination.stat().st_size == 0:
        detail = result.stderr.strip().replace("\x00", "")[-1000:]
        raise LocalNarrationUnavailable(
            "FFmpeg rejected synthesized narration"
            + (f": {detail}" if detail else f" with exit code {result.returncode}")
        )


class WindowsSapiNarrationProvider:
    """Zero-cost local narration through installed Windows System.Speech voices."""

    provider_id = SAPI_PROVIDER_ID

    def readiness(self) -> tuple[bool, str]:
        return local_narration_readiness()

    def list_voices(self) -> list[NarrationVoice]:
        return discover_windows_voices()

    def synthesize(
        self,
        store: ProjectStore,
        *,
        voice_name: str | None = None,
        rate: int = 1,
        volume: int = 100,
        rights_status: str = "unknown",
        license_name: str | None = None,
        required_attribution: str | None = None,
    ) -> SynthesizedNarration:
        if not isinstance(rate, int) or isinstance(rate, bool) or not -10 <= rate <= 10:
            raise ValueError("local narration rate must be an integer from -10 to 10")
        if not isinstance(volume, int) or isinstance(volume, bool) or not 1 <= volume <= 100:
            raise ValueError("local narration volume must be an integer from 1 to 100")
        if voice_name is not None and (
            not voice_name.strip()
            or len(voice_name) > 200
            or any(character in voice_name for character in ("\x00", "\r", "\n"))
        ):
            raise ValueError("local narration voice name is invalid")

        text = _approved_script_text(store)
        voices = self.list_voices()
        voice = (
            _default_voice(voices)
            if voice_name is None
            else next((item for item in voices if item.name == voice_name), None)
        )
        if voice is None:
            raise ValueError(f"requested local narration voice is not installed: {voice_name}")

        audio_directory = store.path("audio")
        audio_directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".local-tts-", dir=audio_directory) as temporary:
            working = Path(temporary)
            text_path = working / "approved-script.txt"
            raw_path = working / "sapi-raw.wav"
            normalized_path = working / "narration.wav"
            text_path.write_text(text + "\n", encoding="utf-8", newline="\n")
            _run_sapi(
                [
                    "-Action",
                    "synthesize",
                    "-InputText",
                    str(text_path),
                    "-OutputWav",
                    str(raw_path),
                    "-Voice",
                    voice.name,
                    "-Rate",
                    str(rate),
                    "-Volume",
                    str(volume),
                ]
            )
            if not raw_path.is_file() or raw_path.stat().st_size == 0:
                raise LocalNarrationUnavailable("System.Speech did not produce a WAV file")
            _normalize_audio(raw_path, normalized_path)
            imported = import_audio(
                store,
                normalized_path,
                rights_status,
                creator=f"Windows System.Speech voice: {voice.name}",
                license_name=license_name,
                required_attribution=required_attribution,
                origin=f"local synthetic narration ({self.provider_id})",
            )
            transcript = import_transcript(store, text_path)

        duration = probe_duration(imported)
        if duration is None:
            raise LocalNarrationUnavailable("FFprobe could not read synthesized narration duration")
        script_path = store.path("script/script.json")
        script = load_model(script_path, ScriptManifest)
        assets = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
        asset_id = store.project().active_versions["audio_asset"]
        asset = next(item for item in assets.assets if item.asset_id == asset_id)
        receipt_payload = {
            "provider": self.provider_id,
            "voice_name": voice.name,
            "voice_culture": voice.culture,
            "voice_gender": voice.gender,
            "voice_age": voice.age,
            "rate": rate,
            "volume": volume,
            "segment_pause_milliseconds": 140,
            "script_version_id": script.version_id,
            "script_hash": sha256_file(script_path),
            "script_text_hash": sha256_bytes(text.encode("utf-8")),
            "segment_approval_hashes": {
                segment.segment_id: segment.approval_hash
                for segment in script.segments
                if segment.approval_hash is not None
            },
            "audio_asset_id": asset.asset_id,
            "output_path": asset.local_path,
            "output_hash": sha256_file(imported),
            "output_duration_seconds": duration,
            "transcript_hash": sha256_file(transcript),
            "rights_status": asset.rights_status,
            "license_name": license_name,
            "required_attribution": required_attribution,
        }
        synthesis_id = derive_synthesis_id(receipt_payload)
        receipt = NarrationSynthesisReceipt(
            synthesis_id=synthesis_id,
            **receipt_payload,
        )
        receipt_path = _write_synthesis_receipt(store, receipt)
        project = store.project()
        project.active_versions["narration_synthesis"] = receipt.synthesis_id
        project.dependency_hashes["narration_synthesis"] = sha256_file(receipt_path)
        store.save_project(project)
        return SynthesizedNarration(
            provider=self.provider_id,
            voice=voice,
            audio_path=imported,
            transcript_path=transcript,
            receipt_path=receipt_path,
            duration_seconds=duration,
            rate=rate,
            volume=volume,
        )


def synthesize_local_narration(
    store: ProjectStore,
    **options: Any,
) -> SynthesizedNarration:
    """Convenience entry point for the default zero-cost local provider."""

    return WindowsSapiNarrationProvider().synthesize(store, **options)
