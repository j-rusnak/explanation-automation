from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import product

from techshort.domain.creative import (
    AntiClickbaitPolicy,
    BeatCadence,
    BeatPlan,
    CadenceBeat,
    CuriosityThread,
    HonestColdOpen,
    NarrativeBrief,
    RetentionEvent,
    RetentionPlan,
    derive_creative_id,
)
from techshort.domain.models import ScriptManifest


@dataclass(frozen=True)
class _RequiredEvent:
    beat_id: str
    low: float
    high: float
    preferred: float
    event_kind: str
    device: str
    purpose: str
    claim_ids: list[str]
    resolves_thread_ids: list[str]
    sound_design: str | None = None


def _clean(value: str) -> str:
    return " ".join(value.split())


def _bounded(prefix: str, value: str, limit: int) -> str:
    clean = _clean(value)
    room = limit - len(prefix)
    if room <= 0:
        return prefix[:limit]
    if len(clean) > room:
        clean = clean[: max(1, room - 1)].rstrip() + "\u2026"
    return prefix + clean


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _cadence(beat_plan: BeatPlan) -> BeatCadence:
    starts_at = 0.0
    beats: list[CadenceBeat] = []
    for beat in beat_plan.beats:
        cadence_role = {
            "hook": "open",
            "re-hook": "re-hook",
            "evidence": "evidence-payoff",
            "limitation": "limitation",
            "resolution": "resolve",
        }.get(beat.role, "develop")
        beats.append(
            CadenceBeat.model_validate(
                {
                    "beat_id": beat.beat_id,
                    "starts_at_seconds": starts_at,
                    "duration_seconds": beat.approximate_duration,
                    "energy": (
                        "high"
                        if cadence_role in {"open", "re-hook", "evidence-payoff"}
                        else "low"
                        if cadence_role == "limitation"
                        else "medium"
                    ),
                    "cadence_role": cadence_role,
                    "ends_with_forward_motion": beat.order < len(beat_plan.beats) - 1,
                }
            )
        )
        starts_at += beat.approximate_duration
    return BeatCadence(
        total_duration_seconds=starts_at,
        max_attention_gap_seconds=5,
        beats=beats,
    )


def _interior_interval(low: float, high: float) -> tuple[float, float]:
    if high < low:
        raise ValueError("retention event has no valid time inside its required beat")
    width = high - low
    if width < 0.04:
        midpoint = (low + high) / 2
        return midpoint, midpoint
    margin = min(0.1, width / 4)
    return low + margin, high - margin


def _time_candidates(required: _RequiredEvent, lattice_origin: float) -> list[float]:
    low, high = _interior_interval(required.low, required.high)
    preferred = min(high, max(low, required.preferred))
    candidates = {round(low, 6), round(preferred, 6), round(high, 6)}
    first_step = math.ceil((low - lattice_origin) / 5)
    last_step = math.floor((high - lattice_origin) / 5)
    candidates.update(
        round(lattice_origin + step * 5, 6) for step in range(first_step, last_step + 1)
    )
    return sorted(candidates)


def _fill_attention_gaps(forced: list[float], total: float) -> list[float]:
    fillers: list[float] = []
    anchors = [0.0, *sorted(forced), total]
    for earlier, later in zip(anchors, anchors[1:], strict=False):
        gap = later - earlier
        count = max(0, math.ceil((gap - 1e-9) / 5) - 1)
        if count:
            spacing = gap / (count + 1)
            fillers.extend(round(earlier + spacing * step, 6) for step in range(1, count + 1))
    return fillers


def _schedule_required_events(
    required_events: list[_RequiredEvent], total: float
) -> tuple[list[tuple[float, _RequiredEvent]], list[float]]:
    lattice_origin = required_events[0].preferred
    candidate_sets = [_time_candidates(event, lattice_origin) for event in required_events]
    best: tuple[tuple[int, float, tuple[float, ...]], tuple[float, ...], list[float]] | None = None
    for values in product(*candidate_sets):
        if any(
            abs(left - right) < 0.01
            for index, left in enumerate(values)
            for right in values[index + 1 :]
        ):
            continue
        forced = sorted(values)
        fillers = _fill_attention_gaps(forced, total)
        event_count = len(forced) + len(fillers)
        deviation = sum(
            abs(value - required.preferred)
            for value, required in zip(values, required_events, strict=True)
        )
        score = (event_count, round(deviation, 6), tuple(round(item, 6) for item in values))
        candidate = (score, values, fillers)
        if best is None or candidate[0] < best[0]:
            best = candidate
    if best is None or best[0][0] > 15:
        raise ValueError(
            "script timing cannot satisfy five-second attention gaps within the "
            "RetentionPlan limit of 15 events"
        )
    values = best[1]
    scheduled = sorted(
        zip(values, required_events, strict=True),
        key=lambda item: item[0],
    )
    return scheduled, best[2]


def _beat_for_time(cadence: BeatCadence, when: float) -> CadenceBeat:
    for beat in cadence.beats:
        end = beat.starts_at_seconds + beat.duration_seconds
        if beat.starts_at_seconds <= when <= end:
            return beat
    return cadence.beats[-1]


def build_provider_neutral_retention_plan(
    brief: NarrativeBrief,
    beat_plan: BeatPlan,
    script: ScriptManifest,
) -> RetentionPlan:
    """Build honest curiosity, payoff, and event cadence from locked artifacts."""
    if (
        beat_plan.narrative_brief_version_id != brief.version_id
        or beat_plan.claims_version_id != brief.claims_version_id
        or beat_plan.angle != brief.angle
        or script.claims_version_id != brief.claims_version_id
        or script.angle != brief.angle
    ):
        raise ValueError("brief, beat plan, and script provenance do not match")
    if len(beat_plan.beats) != len(script.segments):
        raise ValueError("beat plan must contain exactly one beat per script segment")
    for beat, segment in zip(beat_plan.beats, script.segments, strict=True):
        if beat.claim_ids != segment.claim_ids:
            raise ValueError("beat claims must exactly match their script segment")
        if abs(beat.approximate_duration - segment.approximate_duration) > 0.01:
            raise ValueError("beat timing must exactly match its script segment")

    cadence = _cadence(beat_plan)
    evidence_beat = next((beat for beat in beat_plan.beats if beat.role == "evidence"), None)
    limitation_beat = next((beat for beat in beat_plan.beats if beat.role == "limitation"), None)
    rehook_beats = [beat for beat in beat_plan.beats if beat.role == "re-hook"]
    if evidence_beat is None or limitation_beat is None:
        raise ValueError("beat plan requires distinct evidence and limitation beats")
    if len(rehook_beats) < 2:
        raise ValueError("beat plan requires two distinct mid-video re-hook beats")
    rehook_beats = rehook_beats[:2]

    cadence_by_id = {beat.beat_id: beat for beat in cadence.beats}
    first_beat = cadence.beats[0]
    final_beat = cadence.beats[-1]
    lock_by_id = {lock.claim_id: lock for lock in brief.factual_locks}
    final_claims = script.segments[-1].claim_ids
    final_assertion = lock_by_id[final_claims[0]].assertion
    strategy = {
        "surprising-result": "show-result-then-explain",
        "everyday-mechanism": "state-mechanism-then-demonstrate",
        "engineering-tradeoff": "ask-bounded-question",
    }[brief.angle]
    cold_open = HonestColdOpen.model_validate(
        {
            "hook_id": "cold-open-01",
            "beat_id": first_beat.beat_id,
            "text": script.segments[0].text,
            "claim_ids": script.segments[0].claim_ids,
            "reveal_strategy": strategy,
            "truth_up_front": True,
            "deceptive_withholding": False,
            "promised_payoff": _bounded("Resolve with this approved claim: ", final_assertion, 500),
            "payoff_beat_id": final_beat.beat_id,
            "duration_seconds": first_beat.duration_seconds,
        }
    )
    primary_thread_claims = _unique([*cold_open.claim_ids, *final_claims])
    curiosity_threads = [
        CuriosityThread(
            thread_id="thread-primary",
            question="What approved mechanism connects the opening to the final result?",
            opened_at_beat_id=first_beat.beat_id,
            payoff_beat_id=final_beat.beat_id,
            payoff=_bounded("Approved payoff: ", final_assertion, 500),
            claim_ids=primary_thread_claims,
        ),
        CuriosityThread(
            thread_id="thread-evidence",
            question="What does the exact cited evidence establish within its stated scope?",
            opened_at_beat_id=beat_plan.beats[max(0, evidence_beat.order - 1)].beat_id,
            payoff_beat_id=evidence_beat.beat_id,
            payoff=brief.visible_evidence,
            claim_ids=brief.evidence_claim_ids,
        ),
    ]

    def interval(beat: CadenceBeat) -> tuple[float, float]:
        return beat.starts_at_seconds, beat.starts_at_seconds + beat.duration_seconds

    evidence_cadence = cadence_by_id[evidence_beat.beat_id]
    limitation_cadence = cadence_by_id[limitation_beat.beat_id]
    midpoint_low = cadence.total_duration_seconds * 0.35
    midpoint_high = cadence.total_duration_seconds * 0.65
    first_time = min(2.0, first_beat.duration_seconds / 2)
    required_events = [
        _RequiredEvent(
            beat_id=first_beat.beat_id,
            low=first_time,
            high=first_time,
            preferred=first_time,
            event_kind="pattern-interrupt",
            device="visual-mode-change",
            purpose="Turn the honest opening into a bounded mechanism question.",
            claim_ids=script.segments[0].claim_ids,
            resolves_thread_ids=[],
            sound_design="soft-hit",
        ),
        _RequiredEvent(
            beat_id=evidence_beat.beat_id,
            low=interval(evidence_cadence)[0],
            high=interval(evidence_cadence)[1],
            preferred=sum(interval(evidence_cadence)) / 2,
            event_kind="evidence-payoff",
            device="source-receipt",
            purpose="Pay off the evidence question with the exact linked source span.",
            claim_ids=evidence_beat.claim_ids,
            resolves_thread_ids=["thread-evidence"],
            sound_design="source-click",
        ),
    ]
    for rehook in rehook_beats:
        cadence_beat = cadence_by_id[rehook.beat_id]
        low, high = interval(cadence_beat)
        low = max(low, midpoint_low)
        high = min(high, midpoint_high)
        if high < low:
            raise ValueError("re-hook beat falls outside the middle 35 to 65 percent")
        required_events.append(
            _RequiredEvent(
                beat_id=rehook.beat_id,
                low=low,
                high=high,
                preferred=(low + high) / 2,
                event_kind="re-hook",
                device="question-pivot",
                purpose="Refresh attention with a second bounded, claim-linked question.",
                claim_ids=rehook.claim_ids,
                resolves_thread_ids=[],
            )
        )
    limitation_low, limitation_high = interval(limitation_cadence)
    required_events.extend(
        [
            _RequiredEvent(
                beat_id=limitation_beat.beat_id,
                low=limitation_low,
                high=limitation_high,
                preferred=(limitation_low + limitation_high) / 2,
                event_kind="limitation-reframe",
                device="misconception-correction",
                purpose="Make the approved limitation a meaningful part of the explanation.",
                claim_ids=limitation_beat.claim_ids,
                resolves_thread_ids=[],
                sound_design="contrast-shift",
            ),
            _RequiredEvent(
                beat_id=final_beat.beat_id,
                low=final_beat.starts_at_seconds,
                high=cadence.total_duration_seconds,
                preferred=max(
                    final_beat.starts_at_seconds,
                    cadence.total_duration_seconds - 2,
                ),
                event_kind="final-payoff",
                device="callback",
                purpose="Resolve the opening promise without engagement bait.",
                claim_ids=final_claims,
                resolves_thread_ids=["thread-primary"],
                sound_design="resolve-tone",
            ),
        ]
    )
    scheduled_required, filler_times = _schedule_required_events(
        required_events, cadence.total_duration_seconds
    )
    event_rows: list[tuple[float, _RequiredEvent]] = list(scheduled_required)
    filler_devices = ["parameter-change", "comparison-switch", "visual-mode-change"]
    for index, when in enumerate(filler_times):
        cadence_beat = _beat_for_time(cadence, when)
        source_beat = beat_plan.beats[
            next(
                position
                for position, item in enumerate(cadence.beats)
                if item.beat_id == cadence_beat.beat_id
            )
        ]
        event_rows.append(
            (
                when,
                _RequiredEvent(
                    beat_id=cadence_beat.beat_id,
                    low=when,
                    high=when,
                    preferred=when,
                    event_kind="pattern-interrupt",
                    device=filler_devices[index % len(filler_devices)],
                    purpose="Advance one bounded visual state before the next payoff.",
                    claim_ids=source_beat.claim_ids,
                    resolves_thread_ids=[],
                    sound_design="scan-pulse" if index % 3 == 0 else None,
                ),
            )
        )
    event_rows.sort(key=lambda item: item[0])
    attention_events = [
        RetentionEvent.model_validate(
            {
                "event_id": f"retention-event-{index + 1:02d}",
                "beat_id": event.beat_id,
                "scheduled_at_seconds": when,
                "event_kind": event.event_kind,
                "device": event.device,
                "purpose": event.purpose,
                "claim_ids": event.claim_ids,
                "resolves_thread_ids": event.resolves_thread_ids,
                "sound_design": event.sound_design,
            }
        )
        for index, (when, event) in enumerate(event_rows)
    ]
    payload: dict[str, object] = {
        "narrative_brief_version_id": brief.version_id,
        "beat_plan_version_id": beat_plan.version_id,
        "script_version_id": script.version_id,
        "claims_version_id": brief.claims_version_id,
        "angle": brief.angle,
        "factual_locks": brief.factual_locks,
        "cold_open": cold_open,
        "curiosity_threads": curiosity_threads,
        "attention_events": attention_events,
        "cadence": cadence,
        "policy": AntiClickbaitPolicy(),
        "evidence_payoff_beat_id": evidence_beat.beat_id,
        "evidence_claim_ids": brief.evidence_claim_ids,
        "meaningful_limitation_beat_id": limitation_beat.beat_id,
        "meaningful_limitation_claim_ids": brief.limitation_claim_ids,
        "target_word_count": (130, 170),
    }
    payload["version_id"] = derive_creative_id("retention", payload)
    return RetentionPlan.model_validate(payload)
