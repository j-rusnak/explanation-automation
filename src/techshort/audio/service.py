from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

from techshort.domain.hashing import sha256_file, stable_hash
from techshort.domain.models import Asset, AssetManifest, ReviewStatus
from techshort.domain.storage import ProjectStore, atomic_write_model, load_model, sanitize_filename

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


def import_audio(store: ProjectStore, source: Path, rights_status: str = "unknown") -> Path:
    if not source.is_file() or source.suffix.lower() not in ALLOWED_AUDIO:
        raise ValueError("audio must be a regular FFmpeg-compatible audio file")
    if source.stat().st_size > 200 * 1024 * 1024:
        raise ValueError("audio exceeds the 200 MiB limit")
    if rights_status not in AUDIO_RIGHTS:
        raise ValueError(
            "audio rights status must be original, user-owned, permissively-licensed, "
            "citation-only, unknown, or restricted"
        )
    digest = sha256_file(source)
    filename = sanitize_filename(source.name)
    destination = store.path(f"audio/{digest[:12]}-{filename}")
    if not destination.exists():
        shutil.copyfile(source, destination)
    elif sha256_file(destination) != digest:
        raise ValueError("existing audio destination does not match the imported file")

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
    licenses = {
        "original": "original work (review required)",
        "user-owned": "user-owned (review required)",
        "permissively-licensed": "permissive license details pending review",
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
        creator="not recorded",
        license=licenses[rights_status],
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
    # Import lazily to avoid coupling audio registration to renderer startup.
    from techshort.rendering.tools import media_tool

    ffprobe = media_tool("ffprobe")
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        duration = float(result.stdout.strip()) if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return duration if duration is not None and math.isfinite(duration) and duration > 0 else None
