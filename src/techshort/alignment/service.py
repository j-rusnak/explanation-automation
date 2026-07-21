from __future__ import annotations

from pathlib import Path

from techshort.audio.local_tts import active_synthesis_receipt
from techshort.audio.service import active_audio, probe_duration
from techshort.domain.hashing import sha256_bytes, sha256_file
from techshort.domain.models import ReviewStatus, ScriptManifest
from techshort.domain.storage import (
    ProjectStore,
    atomic_copy_file,
    atomic_write_model,
    load_model,
)

from .timing import (
    EngineWordObservation,
    NarrationTimingManifest,
    ObservationSource,
    align_engine_observations,
    canonical_script_text,
    derive_narration_timing_id,
    proportional_timing_projection,
    validate_timing_projection,
)

NARRATION_TIMING_PATH = "audio/narration-timing.json"


def _current_approved_script(store: ProjectStore) -> tuple[ScriptManifest, Path]:
    script_path = store.path("script/script.json")
    if not script_path.is_file():
        raise ValueError("generate and approve a script before creating narration timing")
    script = load_model(script_path, ScriptManifest)
    project = store.project()
    if (
        project.active_versions.get("script") != script.version_id
        or project.approvals.script != ReviewStatus.APPROVED
    ):
        raise ValueError("narration timing requires the current approved script")

    # Imported lazily because review resolves active audio during module import.
    from techshort.review import has_current_approval, script_segment_review_hash

    for segment in script.segments:
        if (
            segment.review_status != ReviewStatus.APPROVED
            or segment.approval_hash != script_segment_review_hash(segment)
            or not has_current_approval(store, "script-segment", segment.segment_id)
        ):
            raise ValueError(
                f"narration timing requires current approval for segment {segment.segment_id}"
            )
    return script, script_path


def _active_audio_binding(store: ProjectStore) -> tuple[Path, str, float]:
    narration = active_audio(store)
    if narration is None:
        raise ValueError("import narration audio before creating narration timing")
    project = store.project()
    asset_id = project.active_versions.get("audio_asset")
    if not asset_id:
        raise ValueError("active narration asset metadata is incomplete; import audio again")
    duration = probe_duration(narration)
    if duration is None or duration <= 0:
        raise ValueError("active narration duration could not be verified")
    return narration, asset_id, duration


def build_narration_timing_manifest(
    store: ProjectStore,
    *,
    observations: list[EngineWordObservation] | None = None,
    source: ObservationSource | None = None,
) -> NarrationTimingManifest:
    """Build timing provenance against exact current script, audio, and synthesis state."""

    if (observations is None) != (source is None):
        raise ValueError("engine observations and their source must be supplied together")
    script, script_path = _current_approved_script(store)
    narration, audio_asset_id, duration = _active_audio_binding(store)
    if observations is None:
        projection = proportional_timing_projection(script, duration)
    else:
        if source is None:
            raise AssertionError("observation source validation did not narrow the source")
        projection = align_engine_observations(
            script,
            observations,
            audio_duration_seconds=duration,
            source=source,
        )

    synthesis = active_synthesis_receipt(store)
    synthesis_id = synthesis[0].synthesis_id if synthesis is not None else None
    synthesis_hash = sha256_file(synthesis[1]) if synthesis is not None else None
    if projection.alignment.observation_source == "sapi-speak-progress" and synthesis is None:
        raise ValueError("SAPI timing observations require a current synthesis receipt")

    try:
        relative_audio = narration.resolve().relative_to(store.root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("active narration path is outside the project") from exc
    segment_approval_hashes = {
        segment.segment_id: segment.approval_hash
        for segment in script.segments
        if segment.approval_hash is not None
    }
    payload: dict[str, object] = {
        "source": projection.source,
        "quality": projection.quality,
        "audio_asset_id": audio_asset_id,
        "audio_path": relative_audio,
        "audio_hash": sha256_file(narration),
        "audio_duration_seconds": duration,
        "script_version_id": script.version_id,
        "script_hash": sha256_file(script_path),
        "script_text_hash": sha256_bytes(canonical_script_text(script).encode("utf-8")),
        "segment_approval_hashes": segment_approval_hashes,
        "synthesis_id": synthesis_id,
        "synthesis_receipt_hash": synthesis_hash,
        "segments": list(projection.segments),
        "words": list(projection.words),
        "alignment": projection.alignment,
    }
    manifest = NarrationTimingManifest(
        timing_id=derive_narration_timing_id(payload),
        **payload,
    )
    verify_narration_timing(store, manifest)
    return manifest


def verify_narration_timing(
    store: ProjectStore, manifest: NarrationTimingManifest
) -> NarrationTimingManifest:
    """Reject timing provenance that no longer matches active reviewed artifacts."""

    script, script_path = _current_approved_script(store)
    if manifest.script_hash != sha256_file(script_path):
        raise ValueError("narration timing does not match the current script bytes")
    expected_text_hash = sha256_bytes(canonical_script_text(script).encode("utf-8"))
    if manifest.script_text_hash != expected_text_hash:
        raise ValueError("narration timing does not match the approved script text")
    validate_timing_projection(manifest, script)

    narration, audio_asset_id, duration = _active_audio_binding(store)
    try:
        relative_audio = narration.resolve().relative_to(store.root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("active narration path is outside the project") from exc
    if (
        manifest.audio_asset_id != audio_asset_id
        or manifest.audio_path != relative_audio
        or manifest.audio_hash != sha256_file(narration)
        or abs(manifest.audio_duration_seconds - duration) > 0.05
    ):
        raise ValueError("narration timing does not match the active narration audio")

    synthesis = active_synthesis_receipt(store)
    if synthesis is None:
        if manifest.synthesis_id is not None or manifest.synthesis_receipt_hash is not None:
            raise ValueError("narration timing references an inactive synthesis receipt")
    elif (
        manifest.synthesis_id != synthesis[0].synthesis_id
        or manifest.synthesis_receipt_hash != sha256_file(synthesis[1])
    ):
        raise ValueError("narration timing does not match the active synthesis receipt")
    if manifest.alignment.observation_source == "sapi-speak-progress" and synthesis is None:
        raise ValueError("SAPI narration timing requires current synthesis provenance")
    return manifest


def register_narration_timing(
    store: ProjectStore, manifest: NarrationTimingManifest
) -> Path:
    """Validate, archive, atomically persist, and activate narration timing."""

    verify_narration_timing(store, manifest)
    destination = store.path(NARRATION_TIMING_PATH)
    if destination.is_file():
        previous = load_model(destination, NarrationTimingManifest)
        if previous != manifest:
            versions = store.path("audio/timing-versions")
            versions.mkdir(parents=True, exist_ok=True)
            archived = versions / f"{previous.timing_id}.json"
            if archived.is_file() and sha256_file(archived) != sha256_file(destination):
                archived = versions / f"{previous.timing_id}-{sha256_file(destination)[:12]}.json"
            if not archived.exists():
                atomic_copy_file(destination, archived)
            elif sha256_file(archived) != sha256_file(destination):
                raise ValueError("narration timing archive collision")
    atomic_write_model(destination, manifest)
    project = store.project()
    project.active_versions["narration_timing"] = manifest.timing_id
    project.dependency_hashes["narration_timing"] = sha256_file(destination)
    store.save_project(project)
    return destination


def active_narration_timing(
    store: ProjectStore,
) -> tuple[NarrationTimingManifest, Path] | None:
    """Load active timing only when its bytes and all dependencies remain current."""

    project = store.project()
    timing_id = project.active_versions.get("narration_timing")
    expected_hash = project.dependency_hashes.get("narration_timing")
    if timing_id is None and expected_hash is None:
        return None
    if not timing_id or not expected_hash:
        raise ValueError("active narration timing metadata is incomplete; generate it again")
    path = store.path(NARRATION_TIMING_PATH)
    if not path.is_file() or sha256_file(path) != expected_hash:
        raise ValueError("active narration timing manifest is missing or changed")
    manifest = load_model(path, NarrationTimingManifest)
    if manifest.timing_id != timing_id:
        raise ValueError("active narration timing ID does not match the project")
    verify_narration_timing(store, manifest)
    return manifest, path
