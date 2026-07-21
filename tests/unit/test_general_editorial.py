from __future__ import annotations

from datetime import UTC, datetime

import pytest

from techshort.domain.hashing import stable_hash
from techshort.domain.models import (
    AngleCandidate,
    AngleSelection,
    AnglesManifest,
    Claim,
    ClaimsManifest,
    EvidenceManifest,
    EvidenceSpan,
    ReviewStatus,
    ScriptManifest,
    ScriptSegment,
    derive_angle_selection_id,
    derive_angles_version_id,
    derive_script_version_id,
)
from techshort.generation.editorial.general import (
    build_provider_neutral_editorial_artifacts,
)


def _evidence(evidence_id: str, excerpt: str, offset: int) -> EvidenceSpan:
    return EvidenceSpan(
        evidence_id=evidence_id,
        source_id="source-battery-note",
        section_heading="Bench observations",
        char_start=offset,
        char_end=offset + len(excerpt),
        excerpt=excerpt,
        context=excerpt,
        source_hash="a" * 64,
        extraction_confidence=1,
        locator=f"section:bench-observations:{offset}",
    )


def _approve(claim: Claim, evidence_by_id: dict[str, EvidenceSpan]) -> Claim:
    claim.review_status = ReviewStatus.APPROVED
    claim.approval_timestamp = datetime.now(UTC)
    spans = [evidence_by_id[evidence_id] for evidence_id in claim.evidence_span_ids]
    claim.approval_hash = stable_hash(
        {
            "claim": claim.model_dump(
                exclude={"approval_hash", "approval_timestamp", "review_status"}
            ),
            "evidence": [span.model_dump(mode="json") for span in spans],
        }
    )
    return claim


def _segments() -> list[ScriptSegment]:
    rows = [
        (
            "segment-open",
            "Faster battery charging changes the clock, and it can change the cell's thermal load.",
            "hook",
            ["claim-temperature"],
            5,
        ),
        (
            "segment-mechanism",
            "Inside the cell, charging current moves lithium ions between electrodes while the control circuit watches voltage and temperature.",
            "factual",
            ["claim-ion-motion"],
            7,
        ),
        (
            "segment-receipt",
            "In the cited bench example, raising current from one amp to two amps shortened charge time by twenty minutes.",
            "factual",
            ["claim-measured-time"],
            7,
        ),
        (
            "segment-rehook-one",
            "But what else moved in that same test, and how does that constrain the faster result?",
            "hook",
            ["claim-measured-time", "claim-temperature"],
            7,
        ),
        (
            "segment-rehook-two",
            "Now change the question: can the charger keep the speed while holding the temperature boundary?",
            "hook",
            ["claim-control", "claim-temperature"],
            6,
        ),
        (
            "segment-control",
            "The control circuit can taper current near the voltage limit, trading peak charging speed for bounded operation.",
            "factual",
            ["claim-control"],
            7,
        ),
        (
            "segment-limitation",
            "The measurement applies only to the tested cell and room-temperature setup; it does not guarantee other batteries behave identically.",
            "limitation",
            ["claim-test-boundary"],
            7,
        ),
        (
            "segment-resolution",
            "So the useful takeaway is specific: current, temperature, and control limits must be read together when comparing charge time.",
            "cta",
            ["claim-ion-motion", "claim-control"],
            6,
        ),
    ]
    return [
        ScriptSegment(
            segment_id=segment_id,
            text=text,
            segment_type=segment_type,  # type: ignore[arg-type]
            claim_ids=claim_ids,
            approximate_duration=duration,
        )
        for segment_id, text, segment_type, claim_ids, duration in rows
    ]


def _inputs(
    *, explicit_limitation: bool = True
) -> tuple[ClaimsManifest, EvidenceManifest, AnglesManifest, AngleSelection, ScriptManifest]:
    spans = [
        _evidence(
            "ev-ion-motion",
            "Charging current moves lithium ions between the cell electrodes.",
            0,
        ),
        _evidence(
            "ev-measured-time",
            "At 1 A the charge took 80 minutes; at 2 A it took 60 minutes.",
            80,
        ),
        _evidence(
            "ev-temperature",
            "The higher-current run reached a higher measured cell temperature.",
            170,
        ),
        _evidence(
            "ev-control",
            "The charger tapered current as cell voltage approached its configured limit.",
            250,
        ),
        _evidence(
            "ev-boundary",
            "The observations cover one cell tested at room temperature.",
            340,
        ),
    ]
    evidence = EvidenceManifest(version_id="evidence-battery-v1", evidence=spans)
    evidence_by_id = {span.evidence_id: span for span in spans}
    boundary_text = (
        "The comparison applies only to one cell tested at room temperature."
        if explicit_limitation
        else "The comparison used one cell at room temperature."
    )
    boundary_limitation = (
        "Results from one tested cell and room-temperature setup do not guarantee other batteries behave identically."
        if explicit_limitation
        else None
    )
    claims = [
        Claim(
            claim_id="claim-ion-motion",
            text="Charging current moves lithium ions between the cell electrodes.",
            evidence_span_ids=["ev-ion-motion"],
            relationship="direct",
            evidence_label="documented",
            confidence=0.95,
        ),
        Claim(
            claim_id="claim-measured-time",
            text="In the bench example, 2 A charging took twenty fewer minutes than 1 A charging.",
            evidence_span_ids=["ev-measured-time"],
            relationship="direct",
            evidence_label="measured",
            scope="One cell in the documented bench example.",
            confidence=0.98,
        ),
        Claim(
            claim_id="claim-temperature",
            text="The higher-current run reached a higher measured cell temperature.",
            evidence_span_ids=["ev-temperature"],
            relationship="direct",
            evidence_label="measured",
            confidence=0.96,
        ),
        Claim(
            claim_id="claim-control",
            text="The charger tapered current near its configured voltage limit.",
            evidence_span_ids=["ev-control"],
            relationship="direct",
            evidence_label="documented",
            confidence=0.95,
        ),
        Claim(
            claim_id="claim-test-boundary",
            text=boundary_text,
            evidence_span_ids=["ev-boundary"],
            relationship="direct",
            evidence_label="documented",
            limitation=boundary_limitation,
            confidence=0.99,
        ),
    ]
    approved_claims = [_approve(claim, evidence_by_id) for claim in claims]
    claims_manifest = ClaimsManifest(
        version_id="claims-battery-v1",
        evidence_version_id=evidence.version_id,
        claims=approved_claims,
    )
    candidates = [
        AngleCandidate(
            angle="surprising-result",
            title="The faster result",
            rationale="Lead with the measured time difference, then establish its test boundary.",
            central_claim_ids=["claim-measured-time"],
        ),
        AngleCandidate(
            angle="everyday-mechanism",
            title="Current inside the cell",
            rationale="Follow ion motion and temperature while keeping the bench result in scope.",
            central_claim_ids=["claim-ion-motion", "claim-temperature"],
        ),
        AngleCandidate(
            angle="engineering-tradeoff",
            title="Speed and control",
            rationale="Compare charging speed with controller limits and the documented boundary.",
            central_claim_ids=["claim-control", "claim-test-boundary"],
        ),
    ]
    angles_version = derive_angles_version_id(claims_manifest.version_id, candidates)
    angles = AnglesManifest(
        version_id=angles_version,
        claims_version_id=claims_manifest.version_id,
        candidates=candidates,
    )
    selected = candidates[1]
    selected_hash = stable_hash(selected)
    selection = AngleSelection(
        selection_id=derive_angle_selection_id(angles.version_id, selected.angle, selected_hash),
        angles_version_id=angles.version_id,
        selected_angle=selected.angle,
        selected_candidate_hash=selected_hash,
    )
    segments = _segments()
    script = ScriptManifest(
        version_id=derive_script_version_id(
            claims_manifest.version_id,
            angles.version_id,
            selection.selection_id,
            selection.selected_angle,
            segments,
        ),
        claims_version_id=claims_manifest.version_id,
        angles_version_id=angles.version_id,
        angle_selection_id=selection.selection_id,
        angle=selection.selected_angle,
        segments=segments,
    )
    return claims_manifest, evidence, angles, selection, script


def test_builds_provider_neutral_locked_retention_chain() -> None:
    claims, evidence, angles, selection, script = _inputs()

    artifacts = build_provider_neutral_editorial_artifacts(
        claims, evidence, angles, selection, script
    )

    assert artifacts.narrative_brief.version_id.startswith("brief-")
    assert "ev-measured-time" in artifacts.narrative_brief.visible_evidence
    assert artifacts.narrative_brief.evidence_claim_ids == ["claim-measured-time"]
    assert artifacts.narrative_brief.limitation_claim_ids == ["claim-test-boundary"]
    assert len(artifacts.beat_plan.beats) == len(script.segments)
    assert {beat.role for beat in artifacts.beat_plan.beats} >= {
        "hook",
        "re-hook",
        "evidence",
        "limitation",
        "resolution",
    }
    plan = artifacts.retention_plan
    assert plan.cold_open.text == script.segments[0].text
    assert plan.cold_open.duration_seconds <= 5
    assert plan.attention_events[0].scheduled_at_seconds <= 2
    markers = [
        0,
        *(event.scheduled_at_seconds for event in plan.attention_events),
        plan.cadence.total_duration_seconds,
    ]
    assert max(later - earlier for earlier, later in zip(markers, markers[1:], strict=False)) <= 5
    midpoint_rehooks = [
        event
        for event in plan.attention_events
        if event.event_kind == "re-hook"
        and plan.cadence.total_duration_seconds * 0.35
        <= event.scheduled_at_seconds
        <= plan.cadence.total_duration_seconds * 0.65
    ]
    assert len({event.beat_id for event in midpoint_rehooks}) == 2
    assert {
        "evidence-payoff",
        "limitation-reframe",
        "final-payoff",
    } <= {event.event_kind for event in plan.attention_events}
    assert artifacts.retention_critique.blocking is False


def test_rejects_stale_claim_approval() -> None:
    claims, evidence, angles, selection, script = _inputs()
    claims.claims[0].approval_hash = "0" * 64

    with pytest.raises(ValueError, match="current evidence-bound approval"):
        build_provider_neutral_editorial_artifacts(claims, evidence, angles, selection, script)


def test_rejects_missing_second_mid_video_hook() -> None:
    claims, evidence, angles, selection, script = _inputs()
    script.segments[4].segment_type = "factual"
    script.version_id = derive_script_version_id(
        claims.version_id,
        angles.version_id,
        selection.selection_id,
        selection.selected_angle,
        script.segments,
    )

    with pytest.raises(ValueError, match="two distinct mid-video hook"):
        build_provider_neutral_editorial_artifacts(claims, evidence, angles, selection, script)


def test_rejects_missing_opening_hook() -> None:
    claims, evidence, angles, selection, script = _inputs()
    script.segments[0].segment_type = "factual"
    script.version_id = derive_script_version_id(
        claims.version_id,
        angles.version_id,
        selection.selection_id,
        selection.selected_angle,
        script.segments,
    )

    with pytest.raises(ValueError, match="begin with an honestly classified hook"):
        build_provider_neutral_editorial_artifacts(claims, evidence, angles, selection, script)


def test_rejects_six_segments_as_infeasible_with_duration_cap() -> None:
    claims, evidence, angles, selection, script = _inputs()
    script.segments = [*script.segments[:5], script.segments[6]]
    script.version_id = derive_script_version_id(
        claims.version_id,
        angles.version_id,
        selection.selection_id,
        selection.selected_angle,
        script.segments,
    )

    with pytest.raises(ValueError, match="requires 7 to 12 script segments"):
        build_provider_neutral_editorial_artifacts(claims, evidence, angles, selection, script)


def test_rejects_limitation_without_approved_caveat() -> None:
    claims, evidence, angles, selection, script = _inputs(explicit_limitation=False)

    with pytest.raises(ValueError, match="explicit caveat or scope"):
        build_provider_neutral_editorial_artifacts(claims, evidence, angles, selection, script)


def test_rejects_claim_with_missing_exact_evidence() -> None:
    claims, evidence, angles, selection, script = _inputs()
    evidence.evidence = [
        span for span in evidence.evidence if span.evidence_id != "ev-measured-time"
    ]

    with pytest.raises(ValueError, match="references missing evidence"):
        build_provider_neutral_editorial_artifacts(claims, evidence, angles, selection, script)


def test_builds_full_75_second_retention_cadence() -> None:
    claims, evidence, angles, selection, script = _inputs()
    extra = [
        ScriptSegment(
            segment_id="segment-extra-one",
            text="Keep the documented setup visible throughout this comparison.",
            segment_type="factual",
            claim_ids=["claim-test-boundary"],
            approximate_duration=6,
        ),
        ScriptSegment(
            segment_id="segment-extra-two",
            text="Separate measured timing from claims about untested cells.",
            segment_type="factual",
            claim_ids=["claim-ion-motion", "claim-test-boundary"],
            approximate_duration=6,
        ),
        ScriptSegment(
            segment_id="segment-extra-three",
            text="Use the controller boundary as a visible checkpoint.",
            segment_type="factual",
            claim_ids=["claim-control"],
            approximate_duration=6,
        ),
        ScriptSegment(
            segment_id="segment-extra-four",
            text="Return to the cited conditions before the final takeaway.",
            segment_type="factual",
            claim_ids=["claim-test-boundary"],
            approximate_duration=6,
        ),
    ]
    script.segments = [
        *script.segments[:3],
        extra[0],
        *script.segments[3:6],
        *extra[1:],
        *script.segments[6:],
    ]
    duration_after_open = 70 / 11
    for segment in script.segments[1:]:
        segment.approximate_duration = duration_after_open
    script.segments[0].approximate_duration = 5
    script.version_id = derive_script_version_id(
        claims.version_id,
        angles.version_id,
        selection.selection_id,
        selection.selected_angle,
        script.segments,
    )

    artifacts = build_provider_neutral_editorial_artifacts(
        claims, evidence, angles, selection, script
    )

    assert artifacts.retention_plan.cadence.total_duration_seconds == pytest.approx(75)
    assert len(artifacts.retention_plan.attention_events) == 15
    assert artifacts.retention_plan.attention_events[-1].scheduled_at_seconds > 60
    assert artifacts.retention_critique.blocking is False
