from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from techshort.audio.local_tts import (
    MAX_SYNTHESIS_TEXT_BYTES,
    SEGMENT_PAUSE_MILLISECONDS,
    _approved_script_segments,
    _concatenate_pcm,
    _normalize_audio,
    _pcm_info,
    _write_synthesis_receipt,
)
from techshort.audio.providers import (
    KOKORO_DEVICE,
    KOKORO_DTYPE,
    KOKORO_MODEL_ID,
    KOKORO_MODEL_REVISION,
    KOKORO_RUNTIME_VERSION,
    KokoroCacheFile,
    KokoroModelCacheManifest,
    KokoroProviderMetadata,
    KokoroVoiceId,
    NarrationConcatenationReceipt,
    NarrationSegmentReceipt,
    NarrationSynthesisReceipt,
    NarrationVoice,
    SynthesizedNarration,
    derive_kokoro_cache_hash,
    derive_synthesis_id,
)
from techshort.audio.service import import_audio, import_transcript, probe_duration
from techshort.domain.hashing import sha256_bytes, sha256_file
from techshort.domain.models import AssetManifest
from techshort.domain.storage import (
    ProjectStore,
    atomic_copy_file,
    atomic_write_model,
    load_model,
)

KOKORO_PROVIDER_ID = "kokoro-local"
KOKORO_CACHE_MANIFEST_NAME = "techshort-kokoro-manifest.json"
KOKORO_SETUP_TIMEOUT_SECONDS = 900
KOKORO_SYNTHESIS_TIMEOUT_SECONDS = 900
MAX_NODE_OUTPUT_BYTES = 4 * 1024 * 1024
_STABLE_SEGMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

KOKORO_VOICE_DETAILS: tuple[tuple[KokoroVoiceId, str, str, str], ...] = (
    ("af_heart", "Heart", "en-US", "Female"),
    ("af_bella", "Bella", "en-US", "Female"),
    ("af_nicole", "Nicole", "en-US", "Female"),
    ("af_aoede", "Aoede", "en-US", "Female"),
    ("af_kore", "Kore", "en-US", "Female"),
    ("af_nova", "Nova", "en-US", "Female"),
    ("af_sarah", "Sarah", "en-US", "Female"),
    ("am_fenrir", "Fenrir", "en-US", "Male"),
    ("am_michael", "Michael", "en-US", "Male"),
    ("am_puck", "Puck", "en-US", "Male"),
    ("bf_emma", "Emma", "en-GB", "Female"),
    ("bf_isabella", "Isabella", "en-GB", "Female"),
    ("bm_fable", "Fable", "en-GB", "Male"),
    ("bm_george", "George", "en-GB", "Male"),
)
_VOICE_BY_ID = {
    voice_id: (display, culture, gender)
    for voice_id, display, culture, gender in KOKORO_VOICE_DETAILS
}


class KokoroNarrationUnavailable(RuntimeError):
    """Raised when the pinned local neural runtime cannot be used safely."""


class _NodeCacheFile(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    path: str
    size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class _NodeCacheInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)

    model_id: str = Field(alias="modelId")
    revision: str
    dtype: str
    device: str
    runtime_version: str = Field(alias="runtimeVersion")
    aggregate_sha256: str = Field(alias="aggregateSha256", pattern=r"^[0-9a-f]{64}$")
    file_count: int = Field(alias="fileCount", gt=0)
    total_bytes: int = Field(alias="totalBytes", gt=0)
    files: list[_NodeCacheFile] = Field(min_length=1, max_length=1000)


class _NodeSegmentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)

    segment_id: str = Field(alias="segmentId")
    file_name: str = Field(alias="fileName")
    sample_rate: int = Field(alias="sampleRate")
    sample_count: int = Field(alias="sampleCount", gt=0)
    duration_seconds: float = Field(alias="durationSeconds", gt=0)


class _NodeSynthesisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)

    schema_version: str = Field(alias="schemaVersion")
    provider: str
    model_id: str = Field(alias="modelId")
    revision: str
    dtype: str
    device: str
    runtime_version: str = Field(alias="runtimeVersion")
    voice: str
    speed: float
    segments: list[_NodeSegmentOutput] = Field(min_length=1, max_length=100)
    model_cache_sha256: str = Field(alias="modelCacheSha256", pattern=r"^[0-9a-f]{64}$")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _kokoro_helper_path() -> Path:
    path = (_repository_root() / "renderer" / "scripts" / "kokoro-local.mjs").resolve()
    if not path.is_file():
        raise KokoroNarrationUnavailable("the repository-owned Kokoro helper is missing")
    return path


def _kokoro_runtime_path() -> Path:
    path = (_repository_root() / "renderer" / "scripts" / "kokoro-runtime.mjs").resolve()
    if not path.is_file():
        raise KokoroNarrationUnavailable("the pinned Kokoro runtime module is missing")
    return path


def _package_lock_path() -> Path:
    path = (_repository_root() / "package-lock.json").resolve()
    if not path.is_file():
        raise KokoroNarrationUnavailable("package-lock.json is required for Kokoro provenance")
    return path


def _runtime_hashes() -> tuple[str, str, str]:
    return (
        sha256_file(_kokoro_helper_path()),
        sha256_file(_kokoro_runtime_path()),
        sha256_file(_package_lock_path()),
    )


def _resolve_cache_directory(cache_directory: Path | None) -> Path:
    repository = _repository_root().resolve()
    model_root = (repository / ".techshort" / "models").resolve()
    configured = os.getenv("TECHSHORT_KOKORO_CACHE") if cache_directory is None else None
    selected = Path(configured) if configured and configured.strip() else cache_directory
    candidate = (
        model_root / "kokoro"
        if selected is None
        else (selected if selected.is_absolute() else repository / selected)
    ).resolve()
    try:
        relative = candidate.relative_to(model_root)
    except ValueError as exc:
        raise ValueError(
            "Kokoro cache must remain under .techshort/models in this repository"
        ) from exc
    if not relative.parts:
        raise ValueError("Kokoro cache must use a dedicated directory under .techshort/models")
    return candidate


def _relative_repository_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(_repository_root().resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("Kokoro runtime path is outside the repository") from exc


def _node_executable() -> str:
    executable = shutil.which("node")
    if not executable:
        raise KokoroNarrationUnavailable("Node.js is required for local Kokoro narration")
    return executable


def _subprocess_environment(*, offline: bool) -> dict[str, str]:
    allowed = {
        "COMSPEC",
        "HOME",
        "LANG",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
    environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    environment["DO_NOT_TRACK"] = "1"
    environment["HF_HUB_DISABLE_TELEMETRY"] = "1"
    if offline:
        environment["HF_HUB_OFFLINE"] = "1"
        environment["TRANSFORMERS_OFFLINE"] = "1"
    return environment


def _run_kokoro(
    arguments: list[str],
    *,
    timeout_seconds: int,
    offline: bool,
) -> str:
    if (
        not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or timeout_seconds <= 0
    ):
        raise ValueError("Kokoro timeout must be a positive integer")
    command = [_node_executable(), str(_kokoro_helper_path()), *arguments]
    try:
        result = subprocess.run(
            command,
            cwd=_repository_root(),
            env=_subprocess_environment(offline=offline),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise KokoroNarrationUnavailable(
            f"local Kokoro narration exceeded its {timeout_seconds}-second timeout"
        ) from exc
    except OSError as exc:
        raise KokoroNarrationUnavailable(
            f"Node.js could not start local Kokoro narration: {type(exc).__name__}"
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().replace("\x00", "")[-1000:]
        raise KokoroNarrationUnavailable(
            "local Kokoro narration failed"
            + (f": {detail}" if detail else f" with exit code {result.returncode}")
        )
    output = result.stdout.strip()
    if not output or len(output.encode("utf-8")) > MAX_NODE_OUTPUT_BYTES:
        raise KokoroNarrationUnavailable("local Kokoro returned missing or excessive metadata")
    return output


def _walk_cache_files(cache_directory: Path) -> list[KokoroCacheFile]:
    files: list[KokoroCacheFile] = []

    def visit(directory: Path) -> None:
        for child in sorted(directory.iterdir(), key=lambda item: item.name):
            if child.is_symlink():
                raise ValueError("Kokoro cache may not contain symbolic links")
            if child.is_dir():
                visit(child)
                continue
            if not child.is_file():
                raise ValueError("Kokoro cache may contain only directories and regular files")
            if child.name == KOKORO_CACHE_MANIFEST_NAME:
                continue
            files.append(
                KokoroCacheFile(
                    path=child.relative_to(cache_directory).as_posix(),
                    size=child.stat().st_size,
                    sha256=sha256_file(child),
                )
            )

    if not cache_directory.is_dir():
        raise ValueError("Kokoro model cache is missing; run explicit setup first")
    visit(cache_directory)
    return sorted(files, key=lambda item: item.path)


def _parse_cache_inspection(output: str) -> _NodeCacheInspection:
    try:
        return _NodeCacheInspection.model_validate_json(output)
    except ValueError as exc:
        raise KokoroNarrationUnavailable("Kokoro setup returned invalid cache metadata") from exc


def _cache_manifest_from_inspection(
    cache_directory: Path,
    inspection: _NodeCacheInspection,
) -> KokoroModelCacheManifest:
    files = _walk_cache_files(cache_directory)
    helper_hash, runtime_hash, package_lock_hash = _runtime_hashes()
    manifest = KokoroModelCacheManifest(
        model_id=cast(Any, inspection.model_id),
        revision=cast(Any, inspection.revision),
        dtype=cast(Any, inspection.dtype),
        device=cast(Any, inspection.device),
        runtime_version=cast(Any, inspection.runtime_version),
        node_helper_hash=helper_hash,
        runtime_module_hash=runtime_hash,
        package_lock_hash=package_lock_hash,
        aggregate_sha256=derive_kokoro_cache_hash(files),
        file_count=len(files),
        total_bytes=sum(item.size for item in files),
        files=files,
    )
    if (
        inspection.aggregate_sha256 != manifest.aggregate_sha256
        or inspection.file_count != manifest.file_count
        or inspection.total_bytes != manifest.total_bytes
        or [item.model_dump() for item in inspection.files]
        != [item.model_dump() for item in manifest.files]
    ):
        raise KokoroNarrationUnavailable(
            "Python and Node disagree about the exact Kokoro model cache bytes"
        )
    return manifest


def _verified_cache_manifest(cache_directory: Path) -> tuple[KokoroModelCacheManifest, Path]:
    manifest_path = cache_directory / KOKORO_CACHE_MANIFEST_NAME
    if not manifest_path.is_file():
        raise ValueError("Kokoro cache manifest is missing; run explicit setup first")
    manifest = load_model(manifest_path, KokoroModelCacheManifest)
    helper_hash, runtime_hash, package_lock_hash = _runtime_hashes()
    files = _walk_cache_files(cache_directory)
    if (
        manifest.node_helper_hash != helper_hash
        or manifest.runtime_module_hash != runtime_hash
        or manifest.package_lock_hash != package_lock_hash
        or manifest.files != files
        or manifest.aggregate_sha256 != derive_kokoro_cache_hash(files)
    ):
        raise ValueError("Kokoro cache manifest or pinned runtime is stale; run setup again")
    return manifest, manifest_path


def discover_kokoro_voices() -> list[NarrationVoice]:
    """Return the fixed reviewed English Kokoro voice IDs in stable order."""

    return [
        NarrationVoice(
            provider=KOKORO_PROVIDER_ID,
            name=voice_id,
            culture=culture,
            gender=gender,
            age="Adult",
        )
        for voice_id, _display, culture, gender in KOKORO_VOICE_DETAILS
    ]


class KokoroLocalNarrationProvider:
    """Pinned CPU/q8 Kokoro narration; setup is explicit and synthesis is offline-only."""

    provider_id = KOKORO_PROVIDER_ID

    def __init__(self, cache_directory: Path | None = None) -> None:
        self.cache_directory = _resolve_cache_directory(cache_directory)

    def readiness(self) -> tuple[bool, str]:
        try:
            _node_executable()
            manifest, _ = _verified_cache_manifest(self.cache_directory)
        except (OSError, ValueError, KokoroNarrationUnavailable) as exc:
            return False, str(exc)
        return (
            True,
            f"pinned Kokoro CPU/q8 cache verified ({manifest.aggregate_sha256[:12]})",
        )

    def list_voices(self) -> list[NarrationVoice]:
        return discover_kokoro_voices()

    def setup(
        self,
        *,
        timeout_seconds: int = KOKORO_SETUP_TIMEOUT_SECONDS,
    ) -> KokoroModelCacheManifest:
        """Explicitly permit the pinned helper to download, then hash-lock the cache."""

        self.cache_directory.mkdir(parents=True, exist_ok=True)
        output = _run_kokoro(
            ["setup", "--cache-dir", str(self.cache_directory)],
            timeout_seconds=timeout_seconds,
            offline=False,
        )
        inspection = _parse_cache_inspection(output)
        manifest = _cache_manifest_from_inspection(self.cache_directory, inspection)
        atomic_write_model(self.cache_directory / KOKORO_CACHE_MANIFEST_NAME, manifest)
        return manifest

    def synthesize(
        self,
        store: ProjectStore,
        *,
        voice_name: str | None = None,
        speed: float = 1.0,
        rights_status: str = "unknown",
        license_name: str | None = None,
        required_attribution: str | None = None,
    ) -> SynthesizedNarration:
        if (
            isinstance(speed, bool)
            or not isinstance(speed, (int, float))
            or not math.isfinite(float(speed))
            or not 0.75 <= float(speed) <= 1.5
        ):
            raise ValueError("Kokoro speed must be a finite number from 0.75 to 1.5")
        selected_voice = voice_name or KOKORO_VOICE_DETAILS[0][0]
        if selected_voice not in _VOICE_BY_ID:
            raise ValueError("Kokoro voice is not in the reviewed English allowlist")
        voice_id = selected_voice
        _display, culture, gender = _VOICE_BY_ID[voice_id]
        voice = NarrationVoice(
            provider=self.provider_id,
            name=voice_id,
            culture=culture,
            gender=gender,
            age="Adult",
        )

        script, approved_segments = _approved_script_segments(store)
        if len(approved_segments) > 100:
            raise ValueError("Kokoro supports at most 100 approved script segments")
        if any(not _STABLE_SEGMENT_ID.fullmatch(item.segment_id) for item in approved_segments):
            raise ValueError("approved script contains a segment ID unsafe for Kokoro")
        if any(len(item.text) > 4000 for item in approved_segments):
            raise ValueError("an approved script segment exceeds Kokoro's 4,000-character limit")
        text = "\n".join(segment.text for segment in approved_segments)
        if len(text.encode("utf-8")) > MAX_SYNTHESIS_TEXT_BYTES:
            raise ValueError("approved narration exceeds the 128 KiB Kokoro safety limit")
        manifest, manifest_path = _verified_cache_manifest(self.cache_directory)

        audio_directory = store.path("audio")
        audio_directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".kokoro-tts-", dir=audio_directory) as stage:
            working = Path(stage)
            input_path = working / "approved-segments.json"
            output_directory = working / "segments"
            output_directory.mkdir()
            transcript_path = working / "approved-script.txt"
            input_payload = {
                "schemaVersion": "1.0.0",
                "voice": voice_id,
                "speed": float(speed),
                "segments": [
                    {"segmentId": segment.segment_id, "text": segment.text}
                    for segment in approved_segments
                ],
            }
            encoded_input = (
                json.dumps(input_payload, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
            if len(encoded_input.encode("utf-8")) > MAX_SYNTHESIS_TEXT_BYTES:
                raise ValueError("encoded Kokoro request exceeds the 128 KiB safety limit")
            input_path.write_text(
                encoded_input,
                encoding="utf-8",
                newline="\n",
            )
            transcript_path.write_text(text + "\n", encoding="utf-8", newline="\n")
            output = _run_kokoro(
                [
                    "synthesize",
                    "--cache-dir",
                    str(self.cache_directory),
                    "--input",
                    str(input_path),
                    "--output-dir",
                    str(output_directory),
                ],
                timeout_seconds=KOKORO_SYNTHESIS_TIMEOUT_SECONDS,
                offline=True,
            )
            result = _parse_synthesis_output(
                output,
                voice_id=voice_id,
                speed=float(speed),
                manifest=manifest,
                approved_segment_ids=[item.segment_id for item in approved_segments],
            )
            manifest_after, _ = _verified_cache_manifest(self.cache_directory)
            if manifest_after != manifest:
                raise KokoroNarrationUnavailable(
                    "Kokoro model cache changed during offline synthesis"
                )
            output_entries = list(output_directory.iterdir())
            if any(item.is_symlink() or not item.is_file() for item in output_entries) or sorted(
                item.name for item in output_entries
            ) != sorted(item.file_name for item in result.segments):
                raise KokoroNarrationUnavailable(
                    "Kokoro output directory contains unexpected segment artifacts"
                )

            normalized_paths: list[Path] = []
            segment_receipts: list[NarrationSegmentReceipt] = []
            for approved, node_segment in zip(approved_segments, result.segments, strict=True):
                raw_path = output_directory / node_segment.file_name
                if not raw_path.is_file() or raw_path.stat().st_size == 0:
                    raise KokoroNarrationUnavailable("Kokoro segment WAV is missing or empty")
                raw_duration = probe_duration(raw_path)
                if raw_duration is None or abs(raw_duration - node_segment.duration_seconds) > 0.05:
                    raise KokoroNarrationUnavailable(
                        "Kokoro segment WAV duration does not match helper metadata"
                    )
                normalized_path = working / f"normalized-{approved.order:03d}.wav"
                _normalize_audio(raw_path, normalized_path)
                info = _pcm_info(normalized_path)
                output_hash = sha256_file(normalized_path)
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
                        engine_events=[],
                    )
                )
                normalized_paths.append(normalized_path)

            concatenated_path = working / "narration.wav"
            concatenation_info = _concatenate_pcm(normalized_paths, concatenated_path)
            segment_directory = store.path("audio/narration-segments")
            segment_directory.mkdir(parents=True, exist_ok=True)
            for segment, normalized_path in zip(segment_receipts, normalized_paths, strict=True):
                destination = store.path(segment.output_path)
                if destination.is_file() and sha256_file(destination) != segment.output_hash:
                    raise ValueError("content-addressed Kokoro segment has unexpected bytes")
                if not destination.exists():
                    atomic_copy_file(normalized_path, destination)

            imported = import_audio(
                store,
                concatenated_path,
                rights_status,
                creator=f"Kokoro local voice: {voice_id}",
                license_name=license_name,
                required_attribution=required_attribution,
                origin=f"local synthetic narration ({self.provider_id})",
            )
            transcript = import_transcript(store, transcript_path)

        duration = concatenation_info.duration_seconds
        probed_duration = probe_duration(imported)
        if probed_duration is None or abs(probed_duration - duration) > 0.05:
            raise KokoroNarrationUnavailable("FFprobe could not verify Kokoro narration duration")
        script_path = store.path("script/script.json")
        assets = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
        asset_id = store.project().active_versions["audio_asset"]
        asset = next(item for item in assets.assets if item.asset_id == asset_id)
        helper_hash, runtime_hash, package_lock_hash = _runtime_hashes()
        provider_metadata = KokoroProviderMetadata(
            voice_id=voice_id,
            speed=float(speed),
            cache_path=_relative_repository_path(self.cache_directory),
            cache_manifest_path=_relative_repository_path(manifest_path),
            cache_manifest_hash=sha256_file(manifest_path),
            model_cache_sha256=manifest.aggregate_sha256,
            node_helper_hash=helper_hash,
            runtime_module_hash=runtime_hash,
            package_lock_hash=package_lock_hash,
        )
        receipt_payload: dict[str, object] = {
            "schema_version": "1.1.0",
            "provider": self.provider_id,
            "voice_name": voice.name,
            "voice_culture": voice.culture,
            "voice_gender": voice.gender,
            "voice_age": voice.age,
            "rate": 0,
            "volume": 100,
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
            "kokoro": provider_metadata.model_dump(mode="json"),
            "rights_status": asset.rights_status,
            "license_name": license_name,
            "required_attribution": required_attribution,
        }
        receipt = NarrationSynthesisReceipt(
            synthesis_id=derive_synthesis_id(receipt_payload),
            **receipt_payload,
        )
        receipt_path = _write_synthesis_receipt(store, receipt)
        project = store.project()
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
            rate=0,
            volume=100,
            speed=float(speed),
        )


def _parse_synthesis_output(
    output: str,
    *,
    voice_id: KokoroVoiceId,
    speed: float,
    manifest: KokoroModelCacheManifest,
    approved_segment_ids: list[str],
) -> _NodeSynthesisOutput:
    try:
        result = _NodeSynthesisOutput.model_validate_json(output)
    except ValueError as exc:
        raise KokoroNarrationUnavailable("Kokoro returned invalid synthesis metadata") from exc
    if (
        result.schema_version != "1.0.0"
        or result.provider != KOKORO_PROVIDER_ID
        or result.model_id != KOKORO_MODEL_ID
        or result.revision != KOKORO_MODEL_REVISION
        or result.dtype != KOKORO_DTYPE
        or result.device != KOKORO_DEVICE
        or result.runtime_version != KOKORO_RUNTIME_VERSION
        or result.voice != voice_id
        or abs(result.speed - speed) > 1e-9
        or result.model_cache_sha256 != manifest.aggregate_sha256
        or [item.segment_id for item in result.segments] != approved_segment_ids
    ):
        raise KokoroNarrationUnavailable(
            "Kokoro synthesis metadata does not match its approved pinned request"
        )
    for index, segment in enumerate(result.segments):
        if (
            segment.file_name != f"segment-{index + 1:03d}.wav"
            or segment.sample_rate != 24_000
            or abs(segment.duration_seconds - segment.sample_count / 24_000) > 1e-9
        ):
            raise KokoroNarrationUnavailable("Kokoro returned invalid segment media metadata")
    return result


def kokoro_narration_readiness(
    cache_directory: Path | None = None,
) -> tuple[bool, str]:
    return KokoroLocalNarrationProvider(cache_directory).readiness()


def setup_kokoro_model(
    cache_directory: Path | None = None,
    *,
    timeout_seconds: int = KOKORO_SETUP_TIMEOUT_SECONDS,
) -> KokoroModelCacheManifest:
    return KokoroLocalNarrationProvider(cache_directory).setup(timeout_seconds=timeout_seconds)


def synthesize_kokoro_narration(
    store: ProjectStore,
    *,
    cache_directory: Path | None = None,
    **options: Any,
) -> SynthesizedNarration:
    return KokoroLocalNarrationProvider(cache_directory).synthesize(store, **options)
