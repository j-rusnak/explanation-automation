from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from techshort.audio.local_tts import active_synthesis_receipt
from techshort.audio.service import active_audio, probe_duration
from techshort.domain.hashing import sha256_bytes, sha256_file, stable_hash
from techshort.domain.models import ReviewStatus, ScriptManifest
from techshort.domain.storage import (
    ProjectStore,
    atomic_copy_file,
    atomic_write_model,
    load_model,
)

from .captions import CaptionCue, cues_from_script
from .comparison import normalized_words
from .timing import (
    EngineWordObservation,
    NarrationTimingManifest,
    ObservationSource,
    WordTiming,
    align_engine_observations,
    canonical_script_text,
    derive_narration_timing_id,
    proportional_segment_timing_projection,
    proportional_timing_projection,
    validate_timing_projection,
)

NARRATION_TIMING_PATH = "audio/narration-timing.json"
RendererCaptionTimingSource = Literal[
    "legacy-cue",
    "estimated-script",
    "sapi-bookmark",
    "aligned-local",
    "manual-reviewed",
]


@dataclass(frozen=True)
class CaptionTimingResolution:
    """One verified cue set shared by rendering, sidecars, and QA."""

    cues: tuple[CaptionCue, ...]
    renderer_captions: tuple[dict[str, object], ...]
    manifest: NarrationTimingManifest | None
    timing_source: RendererCaptionTimingSource
    fallback_reason: str | None


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
    segment_intervals: list[tuple[str, float, float]] | None = None,
) -> NarrationTimingManifest:
    """Build timing provenance against exact current script, audio, and synthesis state."""

    if (observations is None) != (source is None):
        raise ValueError("engine observations and their source must be supplied together")
    if observations is not None and segment_intervals is not None:
        raise ValueError("engine observations and proportional segment intervals are exclusive")
    script, script_path = _current_approved_script(store)
    narration, audio_asset_id, duration = _active_audio_binding(store)
    if observations is None:
        projection = (
            proportional_segment_timing_projection(script, duration, segment_intervals)
            if segment_intervals is not None
            else proportional_timing_projection(script, duration)
        )
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
    elif manifest.synthesis_id != synthesis[
        0
    ].synthesis_id or manifest.synthesis_receipt_hash != sha256_file(synthesis[1]):
        raise ValueError("narration timing does not match the active synthesis receipt")
    if manifest.alignment.observation_source == "sapi-speak-progress" and synthesis is None:
        raise ValueError("SAPI narration timing requires current synthesis provenance")
    return manifest


def register_narration_timing(store: ProjectStore, manifest: NarrationTimingManifest) -> Path:
    """Validate, archive, atomically persist, and activate narration timing."""

    verify_narration_timing(store, manifest)
    destination = store.path(NARRATION_TIMING_PATH)
    changed = True
    if destination.is_file():
        previous = load_model(destination, NarrationTimingManifest)
        if previous.timing_id == manifest.timing_id:
            # Creation timestamps are not content identity. Preserve the first
            # valid bytes so an idempotent rebuild cannot churn final approval.
            manifest = previous
            changed = False
        else:
            versions = store.path("audio/timing-versions")
            versions.mkdir(parents=True, exist_ok=True)
            archived = versions / f"{previous.timing_id}.json"
            if archived.is_file() and sha256_file(archived) != sha256_file(destination):
                archived = versions / f"{previous.timing_id}-{sha256_file(destination)[:12]}.json"
            if not archived.exists():
                atomic_copy_file(destination, archived)
            elif sha256_file(archived) != sha256_file(destination):
                raise ValueError("narration timing archive collision")
    if changed:
        atomic_write_model(destination, manifest)
    project = store.project()
    project.active_versions["narration_timing"] = manifest.timing_id
    project.dependency_hashes["narration_timing"] = sha256_file(destination)
    store.save_project(project)
    if changed:
        store.invalidate_from("final", "narration timing registered or changed")
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


def register_active_synthesis_timing(store: ProjectStore) -> NarrationTimingManifest:
    """Build and register timing from the verified active synthesis receipt.

    Segmented SAPI progress positions are local to each normalized PCM file.
    Convert them to the concatenated timeline with exact receipted segment
    durations and pauses. Eventless local providers intentionally receive a
    proportional manifest instead of fabricated word boundaries.
    """

    active = active_synthesis_receipt(store)
    if active is None:
        raise ValueError("active synthetic narration receipt is required for timing")
    receipt, _receipt_path = active
    observations: list[EngineWordObservation] = []
    segments = list(receipt.segments)
    has_complete_events = bool(segments) and all(segment.engine_events for segment in segments)
    offset = 0.0
    total_duration = receipt.output_duration_seconds
    pause_seconds = receipt.segment_pause_milliseconds / 1000
    segment_intervals: list[tuple[str, float, float]] = []
    for segment_index, segment in enumerate(segments):
        segment_end = offset + segment.duration_seconds
        segment_intervals.append((segment.segment_id, offset, segment_end))
        offset = segment_end
        if segment_index < len(segments) - 1:
            offset += pause_seconds
    if segments and abs(offset - total_duration) > 0.05:
        raise ValueError("synthesis segment timing does not match concatenated audio duration")

    if has_complete_events:
        offset = 0.0
        for segment_index, segment in enumerate(segments):
            events = list(segment.engine_events)
            for event_index, event in enumerate(events):
                absolute_start = min(
                    max(0.0, total_duration - 1e-6),
                    offset + event.normalized_start_seconds,
                )
                next_later_start = next(
                    (
                        later.normalized_start_seconds
                        for later in events[event_index + 1 :]
                        if later.normalized_start_seconds > event.normalized_start_seconds + 1e-7
                    ),
                    segment.duration_seconds,
                )
                absolute_end = min(
                    offset + segment.duration_seconds,
                    offset + next_later_start,
                )
                observations.append(
                    EngineWordObservation(
                        sequence_index=len(observations),
                        text=event.spoken_text,
                        start_seconds=absolute_start,
                        end_seconds=(absolute_end if absolute_end > absolute_start else None),
                        character_position=event.raw_character_position,
                        character_count=event.raw_character_count,
                    )
                )
            offset += segment.duration_seconds
            if segment_index < len(segments) - 1:
                offset += pause_seconds
        manifest = build_narration_timing_manifest(
            store,
            observations=observations,
            source="sapi-speak-progress",
        )
    else:
        manifest = build_narration_timing_manifest(
            store,
            segment_intervals=segment_intervals or None,
        )
    register_narration_timing(store, manifest)
    return manifest


def _renderer_timing_source(
    manifest: NarrationTimingManifest | None,
) -> RendererCaptionTimingSource:
    if manifest is None or manifest.source == "proportional-fallback":
        return "estimated-script"
    if manifest.alignment.observation_source == "sapi-speak-progress":
        return "sapi-bookmark"
    if manifest.alignment.observation_source == "local-whisper":
        return "aligned-local"
    return "estimated-script"


def _caption_segment_windows(
    script: ScriptManifest,
    timing: NarrationTimingManifest | None,
    target_duration: float | None,
) -> list[tuple[str, float, float]]:
    if timing is not None:
        return [
            (segment.segment_id, segment.start_seconds, segment.end_seconds)
            for segment in timing.segments
        ]
    script_duration = sum(segment.approximate_duration for segment in script.segments)
    scale = target_duration / script_duration if target_duration is not None else 1.0
    windows: list[tuple[str, float, float]] = []
    current = 0.0
    for segment in script.segments:
        end = current + segment.approximate_duration * scale
        windows.append((segment.segment_id, current, end))
        current = end
    return windows


def _surface_token_groups(tokens: list[str]) -> list[int]:
    groups: list[int] = []
    group = 0
    group_size = 0
    for token in tokens:
        groups.append(group)
        group_size += 1
        if group_size >= 3 or token.rstrip("\"'\u2019\u201d)]}").endswith(
            (",", ";", ":", ".", "?", "!")
        ):
            group = min(19, group + 1)
            group_size = 0
    return groups


def _proportional_caption_tokens(cue: CaptionCue, tokens: list[str]) -> list[dict[str, object]]:
    if not tokens or len(tokens) > 20:
        return []
    weights = [max(1, len(token)) for token in tokens]
    total_weight = sum(weights)
    duration = cue.end - cue.start
    elapsed_weight = 0
    groups = _surface_token_groups(tokens)
    result: list[dict[str, object]] = []
    for index, (token, weight) in enumerate(zip(tokens, weights, strict=True)):
        start = cue.start + duration * elapsed_weight / total_weight
        elapsed_weight += weight
        end = (
            cue.end
            if index == len(tokens) - 1
            else cue.start + duration * elapsed_weight / total_weight
        )
        result.append({"text": token, "start": start, "end": end, "group": groups[index]})
    return result


def _timed_caption_tokens(
    cue: CaptionCue,
    tokens: list[str],
    words: list[WordTiming],
    cursor: int,
) -> tuple[list[dict[str, object]], int, bool]:
    normalized_by_token = [normalized_words(token) for token in tokens]
    normalized = tuple(item for token_words in normalized_by_token for item in token_words)
    candidate = words[cursor : cursor + len(normalized)]
    if (
        not tokens
        or len(tokens) > 20
        or not normalized
        or tuple(word.canonical for word in candidate) != normalized
    ):
        return _proportional_caption_tokens(cue, tokens), cursor, False

    groups = _surface_token_groups(tokens)
    payload: list[dict[str, object]] = []
    candidate_cursor = 0
    for index, (token, token_words) in enumerate(zip(tokens, normalized_by_token, strict=True)):
        linked = candidate[candidate_cursor : candidate_cursor + len(token_words)]
        start = max(cue.start, linked[0].start_seconds)
        end = min(cue.end, linked[-1].end_seconds)
        if end <= start:
            return _proportional_caption_tokens(cue, tokens), cursor, False
        payload.append({"text": token, "start": start, "end": end, "group": groups[index]})
        candidate_cursor += len(token_words)
    uses_verified_observations = all(word.quality != "proportional-fallback" for word in candidate)
    return payload, cursor + len(normalized), uses_verified_observations


def resolve_caption_timing(
    store: ProjectStore,
    script: ScriptManifest,
    *,
    target_duration: float | None = None,
) -> CaptionTimingResolution:
    """Resolve one verified cue/token payload for rendering, sidecars, and QA."""

    active = active_narration_timing(store)
    timing = active[0] if active is not None else None
    cues = tuple(cues_from_script(script, target_duration=target_duration, timing=timing))
    timing_source = _renderer_timing_source(timing)
    if timing is None:
        fallback_reason = (
            "no active narration timing manifest; captions use approved-script proportional timing"
        )
    elif timing.quality == "proportional-fallback":
        fallback_reason = timing.alignment.fallback_reason or (
            "narration timing explicitly uses approved-script proportional fallback"
        )
    elif timing.alignment.proportional_word_count:
        fallback_reason = (
            f"{timing.alignment.proportional_word_count} approved words use proportional timing"
        )
    elif timing.alignment.coverage < 1:
        fallback_reason = f"narration alignment coverage is {timing.alignment.coverage:.1%}"
    else:
        fallback_reason = None

    windows = _caption_segment_windows(script, timing, target_duration)
    timing_words: dict[str, list[WordTiming]] = {segment_id: [] for segment_id, _, _ in windows}
    if timing is not None:
        for word in timing.words:
            timing_words[word.segment_id].append(word)
    cursors = {segment_id: 0 for segment_id, _, _ in windows}
    renderer_captions: list[dict[str, object]] = []
    for cue in cues:
        matching = next(
            (
                window
                for window in windows
                if cue.start >= window[1] - 1e-7 and cue.end <= window[2] + 1e-7
            ),
            None,
        )
        if matching is None:
            raise ValueError(f"caption {cue.index} does not fit an approved script segment")
        segment_id = matching[0]
        surface_tokens = cue.text.split()
        token_payload, cursor, used_timing = _timed_caption_tokens(
            cue,
            surface_tokens,
            timing_words[segment_id],
            cursors[segment_id],
        )
        cursors[segment_id] = cursor
        cue_source = timing_source if timing is not None and used_timing else "estimated-script"
        cue_payload: dict[str, object] = asdict(cue)
        cue_payload.update(
            {
                "cueId": "caption-"
                + stable_hash(
                    {
                        "timing": timing.timing_id if timing is not None else None,
                        "segment": segment_id,
                        "index": cue.index,
                        "start": cue.start,
                        "end": cue.end,
                        "text": cue.text,
                    }
                )[:16],
                "segmentId": segment_id,
                "timingSource": cue_source,
                "tokens": token_payload,
            }
        )
        renderer_captions.append(cue_payload)
    return CaptionTimingResolution(
        cues=cues,
        renderer_captions=tuple(renderer_captions),
        manifest=timing,
        timing_source=timing_source,
        fallback_reason=fallback_reason,
    )
