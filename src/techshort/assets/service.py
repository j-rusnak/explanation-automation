from __future__ import annotations

import os
import tempfile
from pathlib import Path

from techshort.domain.hashing import sha256_file, stable_hash
from techshort.domain.models import Asset, AssetManifest, ReviewStatus, StoryboardManifest
from techshort.domain.storage import ProjectStore, atomic_write_model, load_model

FONT_PACKAGE = "@fontsource/atkinson-hyperlegible"
FONT_LICENSE = "SIL Open Font License 1.1"
FONT_ATTRIBUTION = "Atkinson Hyperlegible, Copyright 2020 Braille Institute of America, Inc."
FONT_FILES = {
    "asset-font-atkinson-400": "atkinson-hyperlegible-latin-400-normal.woff2",
    "asset-font-atkinson-700": "atkinson-hyperlegible-latin-700-normal.woff2",
}
BUILTIN_FONT_ASSET_IDS = frozenset(FONT_FILES)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with source.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
            while chunk := reader.read(1024 * 1024):
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def ensure_builtin_assets(store: ProjectStore) -> AssetManifest:
    """Register the exact OFL font files rasterized into every rendered video."""

    package = _repository_root() / "node_modules" / FONT_PACKAGE / "files"
    license_source = package.parent / "LICENSE"
    if not package.is_dir() or not license_source.is_file():
        raise ValueError(
            "renderer font package is missing; run `npm.cmd ci` before storyboard review"
        )

    manifest_path = store.path("assets/asset-manifest.json")
    manifest = (
        load_model(manifest_path, AssetManifest)
        if manifest_path.exists()
        else AssetManifest(version_id="assets-empty")
    )
    existing = {asset.asset_id: asset for asset in manifest.assets}
    storyboard_path = store.path("storyboard/storyboard.json")
    scene_ids = (
        [scene.scene_id for scene in load_model(storyboard_path, StoryboardManifest).scenes]
        if storyboard_path.exists()
        else []
    )
    changed = False
    for asset_id, filename in FONT_FILES.items():
        source = package / filename
        if not source.is_file():
            raise ValueError(f"renderer font file is missing: {filename}")
        destination = store.path(f"assets/generated/{filename}")
        source_hash = sha256_file(source)
        if not destination.exists() or sha256_file(destination) != source_hash:
            _atomic_copy(source, destination)
        replacement = Asset(
            asset_id=asset_id,
            asset_type="font",
            local_path=destination.relative_to(store.root).as_posix(),
            sha256=source_hash,
            origin=f"npm:{FONT_PACKAGE}@5.2.8",
            creator="Braille Institute of America, Inc.",
            source_url="https://fontsource.org/fonts/atkinson-hyperlegible",
            license=FONT_LICENSE,
            required_attribution=FONT_ATTRIBUTION,
            rights_status="permissively-licensed",
            embedding_allowed=True,
            review_status=ReviewStatus.PENDING,
            scene_usage=scene_ids,
        )
        previous = existing.get(asset_id)
        if previous is not None and previous.model_dump(
            exclude={"review_status"}
        ) == replacement.model_dump(exclude={"review_status"}):
            replacement.review_status = previous.review_status
        elif previous != replacement:
            changed = True
        existing[asset_id] = replacement

    license_destination = store.path("assets/generated/ATKINSON-OFL-1.1.txt")
    if not license_destination.exists() or sha256_file(license_destination) != sha256_file(
        license_source
    ):
        _atomic_copy(license_source, license_destination)

    ordered = [existing[key] for key in sorted(existing)]
    next_version = f"assets-{stable_hash([item.model_dump(exclude={'review_status'}) for item in ordered])[:12]}"
    if manifest.version_id != next_version or manifest.assets != ordered:
        manifest = AssetManifest(version_id=next_version, assets=ordered)
        atomic_write_model(manifest_path, manifest)
        changed = True
    if changed:
        project = store.invalidate_from("rights", "renderer font assets changed")
        project.active_versions["assets"] = manifest.version_id
        store.save_project(project)
    return manifest
