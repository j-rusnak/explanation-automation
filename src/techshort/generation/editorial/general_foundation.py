from __future__ import annotations

import re
from dataclasses import dataclass

from techshort.domain.creative import (
    Beat,
    BeatPlan,
    NarrativeBrief,
    derive_creative_id,
)
from techshort.domain.hashing import stable_hash
from techshort.domain.models import (
    AngleSelection,
    AnglesManifest,
    Claim,
    ClaimsManifest,
    EvidenceManifest,
    EvidenceSpan,
    ReviewStatus,
    ScriptManifest,
    derive_angles_version_id,
    derive_script_version_id,
)
from techshort.generation.editorial.common import claim_locks, selected_candidate

_LIMITATION_LANGUAGE = re.compile(
    r"\b(?:but|cannot|does not|do not|except|limited|limitation|not guarantee|"
    r"only applies|scope|unless)\b",
    re.IGNORECASE,
)
_NUMBER_OR_UNIT = re.compile(
    r"(?:\d|%|\b(?:ms|seconds?|minutes?|hz|khz|mhz|volts?|amps?|watts?|"
    r"degrees?|pixels?|bytes?)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _EditorialContext:
    claims_by_id: dict[str, Claim]
    evidence_by_id: dict[str, EvidenceSpan]
    central_claim_ids: list[str]
    evidence_segment_index: int
    evidence_claim_ids: list[str]
    limitation_segment_index: int
    limitation_claim_ids: list[str]
    mid_hook_indices: list[int]
    starts_at: list[float]
    total_duration: float


def _claim_review_hash(claim: Claim, evidence_by_id: dict[str, EvidenceSpan]) -> str:
    spans = [evidence_by_id[evidence_id] for evidence_id in claim.evidence_span_ids]
    return stable_hash(
        {
            "claim": claim.model_dump(
                exclude={"approval_hash", "approval_timestamp", "review_status"}
            ),
            "evidence": [span.model_dump(mode="json") for span in spans],
        }
    )


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


def _segment_starts(script: ScriptManifest) -> tuple[list[float], float]:
    elapsed = 0.0
    starts: list[float] = []
    for segment in script.segments:
        starts.append(elapsed)
        elapsed += segment.approximate_duration
    return starts, elapsed


def _explicit_limitation(claim: Claim) -> str | None:
    if claim.limitation and _clean(claim.limitation):
        return _clean(claim.limitation)
    text = _clean(claim.text)
    return text if _LIMITATION_LANGUAGE.search(text) else None


def _evidence_score(
    index: int,
    script: ScriptManifest,
    claims_by_id: dict[str, Claim],
    evidence_by_id: dict[str, EvidenceSpan],
    central_claim_ids: set[str],
) -> tuple[int, int]:
    segment = script.segments[index]
    score = 0
    for claim_id in segment.claim_ids:
        claim = claims_by_id[claim_id]
        score += 5 if claim.evidence_label == "measured" else 3
        score += 2 if claim.relationship == "direct" else 0
        score += 1 if claim_id in central_claim_ids else 0
        excerpts = " ".join(evidence_by_id[item].excerpt for item in claim.evidence_span_ids)
        score += 3 if _NUMBER_OR_UNIT.search(f"{claim.text} {excerpts}") else 0
    # Prefer an early receipt when two candidates are equally concrete.
    return score, -index


def _validate_and_classify(
    claims: ClaimsManifest,
    evidence: EvidenceManifest,
    angles: AnglesManifest,
    selection: AngleSelection,
    script: ScriptManifest,
) -> _EditorialContext:
    if claims.evidence_version_id != evidence.version_id:
        raise ValueError("claims and evidence versions do not match")
    evidence_ids = [span.evidence_id for span in evidence.evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("evidence IDs must be unique")
    evidence_by_id = {span.evidence_id: span for span in evidence.evidence}
    if not evidence_by_id:
        raise ValueError("provider-neutral editorial planning requires exact evidence")

    claim_ids = [claim.claim_id for claim in claims.claims]
    if len(claim_ids) != len(set(claim_ids)):
        raise ValueError("claim IDs must be unique")
    claims_by_id = {claim.claim_id: claim for claim in claims.claims}
    if not claims_by_id:
        raise ValueError("provider-neutral editorial planning requires approved claims")
    for claim in claims.claims:
        missing_evidence = set(claim.evidence_span_ids) - evidence_by_id.keys()
        if missing_evidence:
            raise ValueError(
                f"claim {claim.claim_id} references missing evidence: "
                + ", ".join(sorted(missing_evidence))
            )
        expected_approval = _claim_review_hash(claim, evidence_by_id)
        if (
            claim.review_status != ReviewStatus.APPROVED
            or claim.approval_timestamp is None
            or claim.approval_hash != expected_approval
        ):
            raise ValueError(f"claim {claim.claim_id} lacks a current evidence-bound approval")

    if angles.claims_version_id != claims.version_id:
        raise ValueError("angles target a different claims version")
    expected_angles = derive_angles_version_id(claims.version_id, angles.candidates)
    if angles.version_id != expected_angles:
        raise ValueError("angles content does not match its version ID")
    central_claim_ids = selected_candidate(angles, selection)
    unknown_central = set(central_claim_ids) - claims_by_id.keys()
    if unknown_central:
        raise ValueError(f"selected angle references unknown claims: {sorted(unknown_central)}")

    if (
        script.claims_version_id != claims.version_id
        or script.angles_version_id != angles.version_id
        or script.angle_selection_id != selection.selection_id
        or script.angle != selection.selected_angle
    ):
        raise ValueError("script provenance does not bind the supplied approved inputs")
    expected_script = derive_script_version_id(
        claims.version_id,
        angles.version_id,
        selection.selection_id,
        selection.selected_angle,
        script.segments,
    )
    if script.version_id != expected_script:
        raise ValueError("script content does not match its version ID")
    if not 7 <= len(script.segments) <= 12:
        raise ValueError("retention planning requires 7 to 12 script segments")
    segment_ids = [segment.segment_id for segment in script.segments]
    if len(segment_ids) != len(set(segment_ids)):
        raise ValueError("script segment IDs must be unique")
    if script.segments[0].segment_type != "hook":
        raise ValueError("script must begin with an honestly classified hook")
    if script.segments[0].approximate_duration > 5:
        raise ValueError("the opening hook must be no longer than five seconds")
    overlong = [
        segment.segment_id for segment in script.segments if segment.approximate_duration > 7
    ]
    if overlong:
        raise ValueError(
            "every retention segment must be at most seven seconds: " + ", ".join(overlong)
        )

    starts_at, total_duration = _segment_starts(script)
    if not 45 <= total_duration <= 75:
        raise ValueError("script duration must be between 45 and 75 seconds")
    linked_claim_ids = {claim_id for segment in script.segments for claim_id in segment.claim_ids}
    unknown_script_claims = linked_claim_ids - claims_by_id.keys()
    if unknown_script_claims:
        raise ValueError(
            "script references unknown or unapproved claims: "
            + ", ".join(sorted(unknown_script_claims))
        )
    missing_central = set(central_claim_ids) - linked_claim_ids
    if missing_central:
        raise ValueError(
            "script omits selected-angle central claims: " + ", ".join(sorted(missing_central))
        )

    limitation_indices = [
        index
        for index, segment in enumerate(script.segments)
        if segment.segment_type == "limitation"
    ]
    if not limitation_indices:
        raise ValueError("script requires an evidence-linked meaningful limitation segment")
    limitation_candidates: list[tuple[int, list[str]]] = []
    for index in limitation_indices:
        qualified = [
            claim_id
            for claim_id in script.segments[index].claim_ids
            if _explicit_limitation(claims_by_id[claim_id]) is not None
        ]
        if qualified:
            limitation_candidates.append((index, qualified))
    if not limitation_candidates:
        raise ValueError(
            "limitation narration must link an approved claim with an explicit caveat or scope"
        )
    limitation_index, limitation_claim_ids = limitation_candidates[0]

    midpoint_low = total_duration * 0.35
    midpoint_high = total_duration * 0.65
    mid_hook_indices = [
        index
        for index, segment in enumerate(script.segments[1:], start=1)
        if segment.segment_type == "hook"
        and starts_at[index] <= midpoint_high
        and starts_at[index] + segment.approximate_duration >= midpoint_low
    ]
    if len(mid_hook_indices) < 2:
        raise ValueError("script requires two distinct mid-video hook segments")
    mid_hook_indices = mid_hook_indices[:2]

    excluded = {0, limitation_index, *mid_hook_indices, len(script.segments) - 1}
    evidence_indices = [
        index
        for index, segment in enumerate(script.segments)
        if index not in excluded and segment.segment_type != "hook"
    ]
    if not evidence_indices:
        raise ValueError("script has no distinct segment available for a visible evidence payoff")
    evidence_index = max(
        evidence_indices,
        key=lambda index: _evidence_score(
            index,
            script,
            claims_by_id,
            evidence_by_id,
            set(central_claim_ids),
        ),
    )
    evidence_claim_ids = _unique(script.segments[evidence_index].claim_ids)
    if not any(
        evidence_by_id[evidence_id].excerpt.strip()
        for claim_id in evidence_claim_ids
        for evidence_id in claims_by_id[claim_id].evidence_span_ids
    ):
        raise ValueError("visible evidence claims do not resolve to a non-empty excerpt")

    return _EditorialContext(
        claims_by_id=claims_by_id,
        evidence_by_id=evidence_by_id,
        central_claim_ids=central_claim_ids,
        evidence_segment_index=evidence_index,
        evidence_claim_ids=evidence_claim_ids,
        limitation_segment_index=limitation_index,
        limitation_claim_ids=_unique(limitation_claim_ids),
        mid_hook_indices=mid_hook_indices,
        starts_at=starts_at,
        total_duration=total_duration,
    )


def build_provider_neutral_narrative_brief(
    claims: ClaimsManifest,
    evidence: EvidenceManifest,
    angles: AnglesManifest,
    selection: AngleSelection,
    script: ScriptManifest,
) -> NarrativeBrief:
    """Build a source-bounded brief without using provider prose as evidence."""
    context = _validate_and_classify(claims, evidence, angles, selection, script)
    central_assertions = [
        context.claims_by_id[claim_id].text for claim_id in context.central_claim_ids
    ]
    evidence_spans = _unique(
        [
            evidence_id
            for claim_id in context.evidence_claim_ids
            for evidence_id in context.claims_by_id[claim_id].evidence_span_ids
        ]
    )
    visible_span = context.evidence_by_id[evidence_spans[0]]
    limitation_text = "; ".join(
        _explicit_limitation(context.claims_by_id[claim_id]) or ""
        for claim_id in context.limitation_claim_ids
    )
    payload: dict[str, object] = {
        "claims_version_id": claims.version_id,
        "evidence_version_id": evidence.version_id,
        "angles_version_id": angles.version_id,
        "angle_selection_id": selection.selection_id,
        "angle": selection.selected_angle,
        "audience": "Curious non-specialists seeking a concise, evidence-linked explanation.",
        "promise": _bounded("Explain this approved claim: ", central_assertions[0], 400),
        "central_mechanism": _bounded("Approved mechanism: ", "; ".join(central_assertions), 800),
        "central_claim_ids": context.central_claim_ids,
        "evidence_claim_ids": context.evidence_claim_ids,
        "limitation_claim_ids": context.limitation_claim_ids,
        "visible_evidence": _bounded(
            f"Cited evidence {visible_span.evidence_id}: ", visible_span.excerpt, 600
        ),
        "meaningful_limitation": _bounded("Approved limitation: ", limitation_text, 600),
        "visual_motif": (
            "Use original editable diagrams, a short source receipt, a bounded comparison, "
            "and a visibly separate limitation card."
        ),
        "target_word_count": (130, 170),
        "target_duration_seconds": (45.0, 75.0),
        "factual_locks": claim_locks(claims),
    }
    payload["version_id"] = derive_creative_id("brief", payload)
    return NarrativeBrief.model_validate(payload)


def _beat_role(index: int, context: _EditorialContext, script: ScriptManifest) -> str:
    if index == 0:
        return "hook"
    if index == context.evidence_segment_index:
        return "evidence"
    if index == context.limitation_segment_index:
        return "limitation"
    if index in context.mid_hook_indices:
        return "re-hook"
    if index == len(script.segments) - 1:
        return "resolution"
    return {
        "analogy": "mechanism",
        "caveat": "tradeoff",
        "cta": "consequence",
        "transition": "setup",
    }.get(script.segments[index].segment_type, "mechanism")


def _visual_contract(role: str) -> tuple[str, str, str, list[str]]:
    contracts = {
        "hook": (
            "KineticText",
            "hero",
            "Open immediately with legible text and one claim-bounded visual contrast.",
            ["show-result", "pose-bounded-question"],
        ),
        "re-hook": (
            "Comparison",
            "split-comparison",
            "Change visual mode while restating a bounded question from the linked claims.",
            ["switch-layout", "hold-question"],
        ),
        "evidence": (
            "SourceReceipt",
            "evidence-receipt",
            "Reveal only the linked short excerpt and its stable evidence locator.",
            ["show-receipt", "highlight-excerpt"],
        ),
        "limitation": (
            "LimitationCard",
            "limitation",
            "Separate the approved caveat from the main result without minimizing it.",
            ["pause-motion", "reveal-limitation"],
        ),
        "resolution": (
            "KineticText",
            "hero",
            "Resolve the opening using only the linked approved claims.",
            ["return-to-opening", "resolve"],
        ),
    }
    return contracts.get(
        role,
        (
            "MechanismDiagram",
            "full-diagram",
            "Advance one editable, claim-bounded mechanism state at a time.",
            ["show-state", "advance-state"],
        ),
    )


def build_provider_neutral_beat_plan(
    brief: NarrativeBrief,
    claims: ClaimsManifest,
    evidence: EvidenceManifest,
    angles: AnglesManifest,
    selection: AngleSelection,
    script: ScriptManifest,
) -> BeatPlan:
    """Map normalized script segments to deterministic, claim-locked beats."""
    context = _validate_and_classify(claims, evidence, angles, selection, script)
    if (
        brief.claims_version_id != claims.version_id
        or brief.evidence_version_id != evidence.version_id
        or brief.angles_version_id != angles.version_id
        or brief.angle_selection_id != selection.selection_id
    ):
        raise ValueError("narrative brief does not bind the supplied provider-neutral inputs")
    expected_locks = {lock.claim_id: lock.claim_state_hash for lock in claim_locks(claims)}
    actual_locks = {lock.claim_id: lock.claim_state_hash for lock in brief.factual_locks}
    if actual_locks != expected_locks:
        raise ValueError("narrative brief factual locks are stale")

    beats: list[Beat] = []
    for index, segment in enumerate(script.segments):
        role = _beat_role(index, context, script)
        primitive, layout, visual, animation = _visual_contract(role)
        evidence_span_ids = (
            _unique(
                [
                    evidence_id
                    for claim_id in segment.claim_ids
                    for evidence_id in context.claims_by_id[claim_id].evidence_span_ids
                ]
            )
            if role == "evidence"
            else []
        )
        primary_claim = context.claims_by_id[segment.claim_ids[0]]
        beats.append(
            Beat.model_validate(
                {
                    "beat_id": f"beat-{index + 1:02d}",
                    "order": index,
                    "role": role,
                    "purpose": f"Advance the claim-linked {role} without adding factual scope.",
                    "narration_guidance": segment.text,
                    "on_screen_text": _bounded("", primary_claim.text, 100),
                    "visual_guidance": visual,
                    "primitive_hint": primitive,
                    "layout_family": layout,
                    "animation_beats": animation,
                    "claim_ids": segment.claim_ids,
                    "evidence_span_ids": evidence_span_ids,
                    "approximate_duration": segment.approximate_duration,
                }
            )
        )
    payload: dict[str, object] = {
        "narrative_brief_version_id": brief.version_id,
        "claims_version_id": claims.version_id,
        "angle": selection.selected_angle,
        "factual_locks": brief.factual_locks,
        "beats": beats,
    }
    payload["version_id"] = derive_creative_id("beats", payload)
    return BeatPlan.model_validate(payload)
