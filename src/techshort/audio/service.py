from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

from techshort.domain.hashing import sha256_file, stable_hash
from techshort.domain.models import Asset, AssetManifest, ReviewStatus
from techshort.domain.storage import (
    ProjectStore,
    atomic_copy_file,
    atomic_write_model,
    atomic_write_text,
    load_model,
    sanitize_filename,
)

ALLOWED_AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
AUDIO_RIGHTS = {
    "original",
    "user-owned",
    "permissively-licensed",
    "citation-only",
    "unknown",
    "restricted",
}
EMBEDDABLE_AUDIO_RIGHTS = {"original", "user-owned", "permissively-licensed"}
MAX_TRANSCRIPT_BYTES = 128 * 1024


def _probe_audio_duration(path: Path, *, require_tool: bool) -> float | None:
    # Import lazily to avoid coupling audio registration to renderer startup.
    from techshort.rendering.tools import media_tool

    ffprobe = media_tool("ffprobe")
    if not ffprobe:
        if require_tool:
            raise ValueError(
                "FFprobe is required to validate audio imports; install FFmpeg and retry"
            )
        return None
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,duration:format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        if require_tool:
            raise ValueError(f"FFprobe could not validate the audio file: {exc}") from exc
        return None
    if result.returncode != 0:
        if require_tool:
            raise ValueError(
                "FFprobe rejected the audio file; verify that it is a valid supported media file"
            )
        return None
    try:
        payload = json.loads(result.stdout)
        streams = payload.get("streams", [])
        audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
        duration_values = [payload.get("format", {}).get("duration")]
        duration_values.extend(stream.get("duration") for stream in audio_streams)
        durations = [float(value) for value in duration_values if value not in {None, "", "N/A"}]
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        if require_tool:
            raise ValueError("FFprobe returned invalid metadata for the audio file") from None
        return None
    duration = next(
        (value for value in durations if math.isfinite(value) and value > 0),
        None,
    )
    if not audio_streams or duration is None:
        if require_tool:
            raise ValueError("audio import requires a valid audio stream with a positive duration")
        return None
    return duration


def import_audio(
    store: ProjectStore,
    source: Path,
    rights_status: str = "unknown",
    *,
    creator: str | None = None,
    license_name: str | None = None,
    source_url: str | None = None,
    required_attribution: str | None = None,
) -> Path:
    if not source.is_file() or source.suffix.lower() not in ALLOWED_AUDIO:
        raise ValueError("audio must be a regular FFmpeg-compatible audio file")
    if source.stat().st_size > 200 * 1024 * 1024:
        raise ValueError("audio exceeds the 200 MiB limit")
    if rights_status not in AUDIO_RIGHTS:
        raise ValueError(
            "audio rights status must be original, user-owned, permissively-licensed, "
            "citation-only, unknown, or restricted"
        )
    _probe_audio_duration(source, require_tool=True)
    digest = sha256_file(source)
    filename = sanitize_filename(source.name)
    destination = store.path(f"audio/{digest[:12]}-{filename}")

    asset_path = store.path("assets/asset-manifest.json")
    manifest = (
        load_model(asset_path, AssetManifest)
        if asset_path.exists()
        else AssetManifest(version_id="assets-empty")
    )
    asset_id = f"asset-narration-{digest[:12]}"
    previous = next((item for item in manifest.assets if item.asset_id == asset_id), None)
    # Re-importing the exact active file without a new assertion is idempotent and
    # does not discard an already reviewed rights record.
    if previous is not None and rights_status == "unknown":
        rights_status = previous.rights_status
        creator = creator or previous.creator
        license_name = license_name or previous.license
        source_url = source_url or previous.source_url
        required_attribution = required_attribution or previous.required_attribution
    if rights_status == "permissively-licensed" and not (
        creator and creator.strip() and license_name and license_name.strip()
    ):
        raise ValueError(
            "permissively-licensed audio requires explicit creator and license_name metadata"
        )
    if not destination.exists():
        atomic_copy_file(source, destination)
    elif sha256_file(destination) != digest:
        raise ValueError("existing audio destination does not match the imported file")

    licenses = {
        "original": "original work (review required)",
        "user-owned": "user-owned (review required)",
        "permissively-licensed": license_name or "",
        "citation-only": "citation only; embedding forbidden",
        "unknown": "unrecorded",
        "restricted": "restricted; embedding forbidden",
    }
    narration = Asset(
        asset_id=asset_id,
        asset_type="narration",
        local_path=destination.relative_to(store.root).as_posix(),
        sha256=digest,
        origin="local audio import",
        creator=creator or "not recorded",
        source_url=source_url,
        license=licenses[rights_status],
        required_attribution=required_attribution,
        rights_status=rights_status,
        embedding_allowed=rights_status in EMBEDDABLE_AUDIO_RIGHTS,
        review_status=(
            previous.review_status
            if previous is not None
            and previous.rights_status == rights_status
            and previous.local_path == destination.relative_to(store.root).as_posix()
            else ReviewStatus.PENDING
        ),
        scene_usage=[],
    )
    retained = [item for item in manifest.assets if item.asset_type != "narration"]
    updated_assets = [*retained, narration]
    # Human review state is deliberately excluded from the content version. An
    # approval changes the append-only review ledger, not the bytes or rights
    # assertion that the version identifies.
    version_payload = [item.model_dump(exclude={"review_status"}) for item in updated_assets]
    updated = AssetManifest(
        version_id=f"assets-{stable_hash(version_payload)[:12]}", assets=updated_assets
    )

    project = store.project()
    audio_changed = project.dependency_hashes.get("audio") != digest
    unchanged = (
        project.active_versions.get("audio_asset") == asset_id
        and project.dependency_hashes.get("audio") == digest
        and previous is not None
        and previous == narration
    )
    atomic_write_model(asset_path, updated)
    project.active_versions["audio_asset"] = asset_id
    project.active_versions["assets"] = updated.version_id
    project.dependency_hashes["audio"] = digest
    if audio_changed:
        project.active_versions.pop("narration_transcript", None)
        project.dependency_hashes.pop("narration_transcript", None)
    store.save_project(project)
    if not unchanged:
        store.invalidate_from("rights", f"narration asset {asset_id} imported or changed")
    return destination


def active_audio(store: ProjectStore) -> Path | None:
    """Resolve the active narration by manifest ID and verify its exact bytes."""
    project = store.project()
    asset_id = project.active_versions.get("audio_asset")
    expected_hash = project.dependency_hashes.get("audio")
    if asset_id is None and expected_hash is None:
        return None
    if not asset_id or not expected_hash:
        raise ValueError("active narration metadata is incomplete; import the audio again")
    asset_path = store.path("assets/asset-manifest.json")
    if not asset_path.exists():
        raise ValueError("active narration asset manifest is missing; import the audio again")
    manifest = load_model(asset_path, AssetManifest)
    asset = next((item for item in manifest.assets if item.asset_id == asset_id), None)
    if asset is None or asset.asset_type != "narration":
        raise ValueError(f"active narration asset {asset_id} is missing")
    path = store.path(asset.local_path)
    if not path.is_file():
        raise ValueError(f"active narration file is missing: {asset.local_path}")
    actual_hash = sha256_file(path)
    if actual_hash != asset.sha256 or actual_hash != expected_hash:
        raise ValueError("active narration bytes changed after import; import the audio again")
    return path


def probe_duration(path: Path) -> float | None:
    return _probe_audio_duration(path, require_tool=False)


def _validate_transcript_text(text: str) -> str:
    if "\x00" in text:
        raise ValueError("narration transcript may not contain NUL bytes")
    if len(text.encode("utf-8")) > MAX_TRANSCRIPT_BYTES:
        raise ValueError("narration transcript exceeds the 128 KiB safety limit")
    normalized = text.strip()
    if not normalized:
        raise ValueError("narration transcript is empty")
    return normalized + "\n"


def _active_transcript_path(store: ProjectStore, narration: Path) -> Path:
    audio_hash = sha256_file(narration)
    return store.path(f"audio/{audio_hash[:12]}-transcript.txt")


def import_transcript(store: ProjectStore, source: Path) -> Path:
    """Register a UTF-8 transcript sidecar for the exact active narration bytes."""
    if not source.is_file() or source.suffix.lower() != ".txt":
        raise ValueError("narration transcript must be a regular UTF-8 .txt file")
    if source.stat().st_size > MAX_TRANSCRIPT_BYTES:
        raise ValueError("narration transcript exceeds the 128 KiB safety limit")
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("narration transcript must be valid UTF-8") from exc
    text = _validate_transcript_text(text)

    narration = active_audio(store)
    if narration is None:
        raise ValueError("import narration audio before importing its transcript")
    destination = _active_transcript_path(store, narration)
    atomic_write_text(destination, text)
    transcript_hash = sha256_file(destination)

    project = store.project()
    unchanged = (
        project.dependency_hashes.get("narration_transcript") == transcript_hash
        and project.active_versions.get("narration_transcript")
        == f"transcript-{transcript_hash[:12]}"
    )
    project.active_versions["narration_transcript"] = f"transcript-{transcript_hash[:12]}"
    project.dependency_hashes["narration_transcript"] = transcript_hash
    store.save_project(project)
    if not unchanged:
        store.invalidate_from("final", "narration transcript imported or changed")
    return destination


def active_transcript(store: ProjectStore) -> tuple[str, Path] | None:
    """Load the hash-bound transcript sidecar for the active narration, if any."""
    narration = active_audio(store)
    if narration is None:
        return None
    path = _active_transcript_path(store, narration)
    project = store.project()
    expected_hash = project.dependency_hashes.get("narration_transcript")
    expected_version = project.active_versions.get("narration_transcript")
    if not path.exists() and expected_hash is None and expected_version is None:
        return None
    if not path.is_file() or not expected_hash or not expected_version:
        raise ValueError("active narration transcript metadata is incomplete; import it again")
    actual_hash = sha256_file(path)
    if actual_hash != expected_hash or expected_version != f"transcript-{actual_hash[:12]}":
        raise ValueError("active narration transcript changed after import; import it again")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("active narration transcript is not valid UTF-8") from exc
    return _validate_transcript_text(text).strip(), path
