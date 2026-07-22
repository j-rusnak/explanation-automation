from __future__ import annotations

import json
import math
import os
import platform
import re
import shutil
import statistics
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from techshort.audio.providers import (
    NarrationConcatenationReceipt,
    NarrationEngineEvent,
    NarrationSegmentReceipt,
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
MAX_ENGINE_EVENTS = 4096
PCM_SAMPLE_RATE = 48_000
PCM_CHANNELS = 1
PCM_SAMPLE_WIDTH = 2
SEGMENT_PAUSE_MILLISECONDS = 140
SEGMENT_PAUSE_FRAMES = 6_720
SILENCE_EVENT = re.compile(r"silence_(start|end):\s*(-?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class _ApprovedNarrationSegment:
    segment_id: str
    order: int
    text: str
    approval_hash: str


@dataclass(frozen=True)
class _RawEngineEvent:
    spoken_text: str
    audio_position_seconds: float
    raw_character_position: int
    raw_character_count: int


@dataclass(frozen=True)
class _PcmInfo:
    frame_count: int

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / PCM_SAMPLE_RATE


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


def _approved_script_segments(
    store: ProjectStore,
) -> tuple[ScriptManifest, list[_ApprovedNarrationSegment]]:
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

    approved: list[_ApprovedNarrationSegment] = []
    for order, segment in enumerate(script.segments):
        text = " ".join(segment.text.split())
        if not text:
            raise ValueError(f"approved script segment {segment.segment_id} has no narration text")
        if "\x00" in text:
            raise ValueError("approved narration may not contain NUL bytes")
        approval_hash = segment.approval_hash
        if approval_hash is None:  # Defensive narrowing after the approval check above.
            raise ValueError(f"approved script segment {segment.segment_id} has no approval hash")
        approved.append(
            _ApprovedNarrationSegment(
                segment_id=segment.segment_id,
                order=order,
                text=text,
                approval_hash=approval_hash,
            )
        )

    text = "\n".join(segment.text for segment in approved)
    encoded = text.encode("utf-8")
    if not text:
        raise ValueError("the approved script has no narration text")
    if len(encoded) > MAX_SYNTHESIS_TEXT_BYTES:
        raise ValueError("approved narration exceeds the 128 KiB local synthesis safety limit")
    return script, approved


def _approved_script_text(store: ProjectStore) -> str:
    _, segments = _approved_script_segments(store)
    return "\n".join(segment.text for segment in segments)


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


def _utf16_slice(text: str, position: int, count: int) -> str:
    """Resolve System.Speech UTF-16 character offsets without guessing code points."""

    encoded = text.encode("utf-16-le")
    start = position * 2
    end = (position + count) * 2
    if position < 0 or count <= 0 or end > len(encoded):
        raise ValueError("speech progress character range is outside its approved segment")
    try:
        return encoded[start:end].decode("utf-16-le")
    except UnicodeDecodeError as exc:
        raise ValueError("speech progress character range splits a UTF-16 character") from exc


def _verify_engine_event_text(
    text: str,
    events: list[NarrationEngineEvent],
) -> None:
    for event in events:
        selected = _utf16_slice(
            text,
            event.raw_character_position,
            event.raw_character_count,
        )
        if selected != event.spoken_text:
            raise ValueError("speech progress text does not match its approved character range")


def _approved_text_event_ranges(
    approved_text: str,
    events: list[_RawEngineEvent],
) -> list[tuple[int, int]]:
    """Resolve progress events to exact approved-text UTF-16 ranges.

    ``SpeechSynthesizer`` normally reports offsets into the supplied text, but
    some installed voices report offsets into the SSML generated internally by
    ``PromptBuilder``. Preserve direct ranges only when every event verifies.
    Otherwise remap the complete ordered sequence by exact event text. This
    never adopts engine prose: an event that cannot be found monotonically in
    the approved segment remains a hard failure.
    """

    direct_ranges: list[tuple[int, int]] = []
    direct_valid = True
    for event in events:
        try:
            selected = _utf16_slice(
                approved_text,
                event.raw_character_position,
                event.raw_character_count,
            )
        except ValueError:
            direct_valid = False
            break
        if selected != event.spoken_text:
            direct_valid = False
            break
        direct_ranges.append((event.raw_character_position, event.raw_character_count))
    if direct_valid:
        return direct_ranges

    mapped: list[tuple[int, int]] = []
    codepoint_cursor = 0
    utf16_cursor = 0
    for index, event in enumerate(events):
        if (
            index
            and event.spoken_text == events[index - 1].spoken_text
            and event.raw_character_position == events[index - 1].raw_character_position
            and event.raw_character_count == events[index - 1].raw_character_count
        ):
            # Some SAPI voices emit one SpeakProgress callback per spoken part
            # of a hyphenated token while repeating the compound text and SSML
            # range. Preserve both audio observations against the same verified
            # approved-text range; downstream alignment accounts for duplicates.
            mapped.append(mapped[-1])
            continue
        start = approved_text.find(event.spoken_text, codepoint_cursor)
        if start < 0:
            raise LocalNarrationUnavailable(
                "System.Speech progress text cannot be mapped to the approved segment"
            )
        utf16_cursor += len(approved_text[codepoint_cursor:start].encode("utf-16-le")) // 2
        count = len(event.spoken_text.encode("utf-16-le")) // 2
        mapped.append((utf16_cursor, count))
        codepoint_cursor = start + len(event.spoken_text)
        utf16_cursor += count
    return mapped


def _parse_sapi_synthesis_output(
    output: str,
    *,
    expected_voice: str,
    expected_rate: int,
    expected_volume: int,
    expected_output_name: str,
    approved_text: str,
) -> list[_RawEngineEvent]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise LocalNarrationUnavailable(
            "System.Speech returned invalid synthesis metadata"
        ) from exc
    expected_keys = {
        "voice",
        "rate",
        "volume",
        "output",
        "progress",
        "progressTruncated",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise LocalNarrationUnavailable("System.Speech returned malformed synthesis metadata")
    if (
        payload["voice"] != expected_voice
        or payload["rate"] != expected_rate
        or payload["volume"] != expected_volume
        or payload["output"] != expected_output_name
    ):
        raise LocalNarrationUnavailable("System.Speech synthesis metadata changed unexpectedly")
    if payload["progressTruncated"] is not False:
        raise LocalNarrationUnavailable("System.Speech progress metadata exceeded its safety bound")
    progress = payload["progress"]
    if not isinstance(progress, list) or not 1 <= len(progress) <= MAX_ENGINE_EVENTS:
        raise LocalNarrationUnavailable(
            "System.Speech returned missing or excessive progress metadata"
        )

    events: list[_RawEngineEvent] = []
    for item in progress:
        if not isinstance(item, dict) or set(item) != {
            "spokenText",
            "audioPositionSeconds",
            "characterPosition",
            "characterCount",
        }:
            raise LocalNarrationUnavailable("System.Speech returned malformed progress metadata")
        spoken_text = item["spokenText"]
        audio_position = item["audioPositionSeconds"]
        character_position = item["characterPosition"]
        character_count = item["characterCount"]
        if (
            not isinstance(spoken_text, str)
            or not spoken_text
            or len(spoken_text) > 512
            or "\x00" in spoken_text
            or not isinstance(audio_position, (int, float))
            or isinstance(audio_position, bool)
            or not math.isfinite(float(audio_position))
            or float(audio_position) < 0
            or not isinstance(character_position, int)
            or isinstance(character_position, bool)
            or character_position < 0
            or not isinstance(character_count, int)
            or isinstance(character_count, bool)
            or character_count <= 0
        ):
            raise LocalNarrationUnavailable("System.Speech returned invalid progress metadata")
        events.append(
            _RawEngineEvent(
                spoken_text=spoken_text,
                audio_position_seconds=float(audio_position),
                raw_character_position=character_position,
                raw_character_count=character_count,
            )
        )
    if [event.audio_position_seconds for event in events] != sorted(
        event.audio_position_seconds for event in events
    ) or [event.raw_character_position for event in events] != sorted(
        event.raw_character_position for event in events
    ):
        raise LocalNarrationUnavailable("System.Speech progress metadata is out of order")
    approved_ranges = _approved_text_event_ranges(approved_text, events)
    return [
        _RawEngineEvent(
            spoken_text=event.spoken_text,
            audio_position_seconds=event.audio_position_seconds,
            raw_character_position=position,
            raw_character_count=count,
        )
        for event, (position, count) in zip(events, approved_ranges, strict=True)
    ]


def _fit_sapi_progress_positions(
    events: list[_RawEngineEvent],
    *,
    trim_start_seconds: float,
    pcm_duration_seconds: float,
) -> list[float]:
    """Fit a voice engine's monotonic clock into the verified PCM interval.

    Some Windows voices report ``AudioPosition`` in an internal clock that can
    run longer than the WAV they emit. When that happens, preserve the engine's
    relative cadence and apply one deterministic affine scale. A median positive
    event gap reserves room for the final spoken token instead of pinning it to
    the PCM boundary.
    """

    if pcm_duration_seconds <= 0:
        raise ValueError("normalized narration segment duration must be positive")
    positions = [max(0.0, event.audio_position_seconds - trim_start_seconds) for event in events]
    if not positions or positions[-1] < pcm_duration_seconds:
        return positions
    positive_gaps = [
        right - left
        for left, right in zip(positions, positions[1:], strict=False)
        if right - left > 1e-7
    ]
    tail = (
        statistics.median(positive_gaps) if positive_gaps else max(0.05, pcm_duration_seconds * 0.1)
    )
    engine_end = positions[-1] + tail
    if engine_end <= 0:
        raise ValueError("System.Speech event clock cannot be normalized")
    scale = pcm_duration_seconds / engine_end
    return [min(max(0.0, pcm_duration_seconds - 1e-6), position * scale) for position in positions]


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
    script, approved_segments = _approved_script_segments(store)
    text = "\n".join(segment.text for segment in approved_segments)
    segment_hashes = {segment.segment_id: segment.approval_hash for segment in approved_segments}
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
    if receipt.schema_version == "1.1.0":
        _verify_segmented_synthesis(store, narration, receipt, approved_segments)
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


def _pcm_info(path: Path) -> _PcmInfo:
    try:
        with wave.open(str(path), "rb") as audio:
            if (
                audio.getnchannels() != PCM_CHANNELS
                or audio.getsampwidth() != PCM_SAMPLE_WIDTH
                or audio.getframerate() != PCM_SAMPLE_RATE
                or audio.getcomptype() != "NONE"
            ):
                raise ValueError("narration segment must be 48 kHz mono 16-bit PCM")
            frame_count = audio.getnframes()
    except (EOFError, OSError, wave.Error) as exc:
        raise ValueError("narration segment is not a readable PCM WAV") from exc
    if frame_count <= 0:
        raise ValueError("narration segment contains no PCM frames")
    return _PcmInfo(frame_count=frame_count)


def _concatenate_pcm(segment_paths: list[Path], destination: Path) -> _PcmInfo:
    """Join canonical PCM segment bytes with an exact, deterministic zero pause."""

    if not segment_paths:
        raise ValueError("narration concatenation requires at least one segment")
    infos = [_pcm_info(path) for path in segment_paths]
    try:
        with wave.open(str(destination), "wb") as output:
            output.setnchannels(PCM_CHANNELS)
            output.setsampwidth(PCM_SAMPLE_WIDTH)
            output.setframerate(PCM_SAMPLE_RATE)
            for index, (path, info) in enumerate(zip(segment_paths, infos, strict=True)):
                with wave.open(str(path), "rb") as source:
                    remaining = info.frame_count
                    while remaining:
                        frame_batch = min(remaining, 65_536)
                        frames = source.readframes(frame_batch)
                        if len(frames) != frame_batch * PCM_CHANNELS * PCM_SAMPLE_WIDTH:
                            raise ValueError(
                                "narration segment ended before its declared frame count"
                            )
                        output.writeframesraw(frames)
                        remaining -= frame_batch
                if index < len(segment_paths) - 1:
                    output.writeframesraw(
                        b"\x00" * SEGMENT_PAUSE_FRAMES * PCM_CHANNELS * PCM_SAMPLE_WIDTH
                    )
    except (EOFError, OSError, wave.Error) as exc:
        raise ValueError("could not concatenate narration segment PCM") from exc
    result = _pcm_info(destination)
    expected_frames = (
        sum(info.frame_count for info in infos) + (len(infos) - 1) * SEGMENT_PAUSE_FRAMES
    )
    if result.frame_count != expected_frames:
        raise ValueError("concatenated narration frame count is not deterministic")
    return result


def _verify_pcm_concatenation(output_path: Path, segment_paths: list[Path]) -> None:
    """Compare every final PCM frame with the receipted ordered inputs and pauses."""

    try:
        with wave.open(str(output_path), "rb") as output:
            for index, path in enumerate(segment_paths):
                info = _pcm_info(path)
                with wave.open(str(path), "rb") as source:
                    remaining = info.frame_count
                    while remaining:
                        frame_batch = min(remaining, 65_536)
                        expected = source.readframes(frame_batch)
                        actual = output.readframes(frame_batch)
                        if actual != expected:
                            raise ValueError(
                                "active narration is not the receipted segment concatenation"
                            )
                        remaining -= frame_batch
                if index < len(segment_paths) - 1:
                    pause = output.readframes(SEGMENT_PAUSE_FRAMES)
                    if pause != (b"\x00" * SEGMENT_PAUSE_FRAMES * PCM_CHANNELS * PCM_SAMPLE_WIDTH):
                        raise ValueError("active narration segment pause is not exact zero PCM")
            if output.readframes(1):
                raise ValueError("active narration has unreceipted trailing PCM frames")
    except (EOFError, OSError, wave.Error) as exc:
        raise ValueError("active narration concatenation is not readable PCM") from exc


def _verify_segmented_synthesis(
    store: ProjectStore,
    narration: Path,
    receipt: NarrationSynthesisReceipt,
    approved_segments: list[_ApprovedNarrationSegment],
) -> None:
    concatenation = receipt.concatenation
    if concatenation is None or len(receipt.segments) != len(approved_segments):
        raise ValueError("segmented synthesis receipt is incomplete")
    segment_paths: list[Path] = []
    for approved, segment in zip(approved_segments, receipt.segments, strict=True):
        if (
            segment.order != approved.order
            or segment.segment_id != approved.segment_id
            or segment.text_hash != sha256_bytes(approved.text.encode("utf-8"))
            or segment.approval_hash != approved.approval_hash
        ):
            raise ValueError("segment receipt does not match its currently approved script segment")
        expected_path = f"audio/narration-segments/{segment.output_hash}.wav"
        if segment.output_path != expected_path:
            raise ValueError("segment receipt does not use its content-addressed audio path")
        segment_path = store.path(segment.output_path)
        if not segment_path.is_file() or sha256_file(segment_path) != segment.output_hash:
            raise ValueError("receipted narration segment audio is missing or changed")
        info = _pcm_info(segment_path)
        if (
            info.frame_count != segment.frame_count
            or abs(info.duration_seconds - segment.duration_seconds) > 1e-9
        ):
            raise ValueError("receipted narration segment PCM duration is stale")
        _verify_engine_event_text(approved.text, segment.engine_events)
        segment_paths.append(segment_path)

    output_info = _pcm_info(narration)
    if (
        output_info.frame_count != concatenation.output_frame_count
        or abs(output_info.duration_seconds - concatenation.output_duration_seconds) > 1e-9
        or concatenation.pause_milliseconds != SEGMENT_PAUSE_MILLISECONDS
        or concatenation.pause_frames != SEGMENT_PAUSE_FRAMES
    ):
        raise ValueError("active narration PCM does not match its concatenation receipt")
    _verify_pcm_concatenation(narration, segment_paths)


def _normalize_audio(source: Path, destination: Path) -> float:
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
    _pcm_info(destination)
    return start


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

        script, approved_segments = _approved_script_segments(store)
        text = "\n".join(segment.text for segment in approved_segments)
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
            concatenated_path = working / "narration.wav"
            text_path.write_text(text + "\n", encoding="utf-8", newline="\n")
            segment_receipts: list[NarrationSegmentReceipt] = []
            normalized_paths: list[Path] = []
            for approved in approved_segments:
                segment_text_path = working / f"segment-{approved.order:04d}.txt"
                raw_path = working / f"segment-{approved.order:04d}-raw.wav"
                normalized_path = working / f"segment-{approved.order:04d}.wav"
                segment_text_path.write_text(approved.text + "\n", encoding="utf-8", newline="\n")
                sapi_output = _run_sapi(
                    [
                        "-Action",
                        "synthesize",
                        "-InputText",
                        str(segment_text_path),
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
                raw_events = _parse_sapi_synthesis_output(
                    sapi_output,
                    expected_voice=voice.name,
                    expected_rate=rate,
                    expected_volume=volume,
                    expected_output_name=raw_path.name,
                    approved_text=approved.text,
                )
                if not raw_path.is_file() or raw_path.stat().st_size == 0:
                    raise LocalNarrationUnavailable("System.Speech did not produce a WAV file")
                trim_start = _normalize_audio(raw_path, normalized_path)
                info = _pcm_info(normalized_path)
                output_hash = sha256_file(normalized_path)
                fitted_positions = _fit_sapi_progress_positions(
                    raw_events,
                    trim_start_seconds=trim_start,
                    pcm_duration_seconds=info.duration_seconds,
                )
                events = [
                    NarrationEngineEvent(
                        spoken_text=event.spoken_text,
                        normalized_start_seconds=round(position, 6),
                        raw_character_position=event.raw_character_position,
                        raw_character_count=event.raw_character_count,
                    )
                    for event, position in zip(raw_events, fitted_positions, strict=True)
                ]
                segment_receipts.append(
                    NarrationSegmentReceipt(
                        segment_id=approved.segment_id,
                        order=approved.order,
                        text_hash=sha256_bytes(approved.text.encode("utf-8")),
                        approval_hash=approved.approval_hash,
                        output_path=f"audio/narration-segments/{output_hash}.wav",
                        output_hash=output_hash,
                        frame_count=info.frame_count,
                        duration_seconds=info.duration_seconds,
                        engine_events=events,
                    )
                )
                normalized_paths.append(normalized_path)

            concatenation_info = _concatenate_pcm(normalized_paths, concatenated_path)
            segment_directory = store.path("audio/narration-segments")
            segment_directory.mkdir(parents=True, exist_ok=True)
            for segment, normalized_path in zip(segment_receipts, normalized_paths, strict=True):
                destination = store.path(segment.output_path)
                if destination.is_file() and sha256_file(destination) != segment.output_hash:
                    raise ValueError("content-addressed narration segment has unexpected bytes")
                if not destination.exists():
                    atomic_copy_file(normalized_path, destination)

            imported = import_audio(
                store,
                concatenated_path,
                rights_status,
                creator=f"Windows System.Speech voice: {voice.name}",
                license_name=license_name,
                required_attribution=required_attribution,
                origin=f"local synthetic narration ({self.provider_id})",
            )
            transcript = import_transcript(store, text_path)

        duration = concatenation_info.duration_seconds
        probed_duration = probe_duration(imported)
        if probed_duration is None or abs(probed_duration - duration) > 0.05:
            raise LocalNarrationUnavailable(
                "FFprobe could not verify synthesized narration duration"
            )
        script_path = store.path("script/script.json")
        assets = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
        asset_id = store.project().active_versions["audio_asset"]
        asset = next(item for item in assets.assets if item.asset_id == asset_id)
        receipt_payload = {
            "schema_version": "1.1.0",
            "provider": self.provider_id,
            "voice_name": voice.name,
            "voice_culture": voice.culture,
            "voice_gender": voice.gender,
            "voice_age": voice.age,
            "rate": rate,
            "volume": volume,
            "segment_pause_milliseconds": SEGMENT_PAUSE_MILLISECONDS,
            "script_version_id": script.version_id,
            "script_hash": sha256_file(script_path),
            "script_text_hash": sha256_bytes(text.encode("utf-8")),
            "segment_approval_hashes": {
                segment.segment_id: segment.approval_hash for segment in approved_segments
            },
            "audio_asset_id": asset.asset_id,
            "output_path": asset.local_path,
            "output_hash": sha256_file(imported),
            "output_duration_seconds": duration,
            "transcript_hash": sha256_file(transcript),
            "segments": [segment.model_dump(mode="json") for segment in segment_receipts],
            "concatenation": NarrationConcatenationReceipt(
                output_frame_count=concatenation_info.frame_count,
                output_duration_seconds=concatenation_info.duration_seconds,
            ).model_dump(mode="json"),
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
        # A replacement synthesis receipt invalidates any word timing derived
        # from the previous engine events, even when output audio hashes happen
        # to match. The alignment service registers the new timing below.
        project.active_versions.pop("narration_timing", None)
        project.dependency_hashes.pop("narration_timing", None)
        project.active_versions["narration_synthesis"] = receipt.synthesis_id
        project.dependency_hashes["narration_synthesis"] = sha256_file(receipt_path)
        store.save_project(project)
        from techshort.alignment import register_active_synthesis_timing

        register_active_synthesis_timing(store)
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
