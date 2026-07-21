from __future__ import annotations

import re

from techshort.domain.creative import (
    AntiClickbaitPolicy,
    BeatCadence,
    BeatPlan,
    CadenceBeat,
    CuriosityThread,
    HonestColdOpen,
    NarrativeBrief,
    RetentionCritique,
    RetentionEvent,
    RetentionFinding,
    RetentionPlan,
    derive_creative_id,
)
from techshort.domain.hashing import stable_hash
from techshort.domain.models import ScriptManifest

_WORD_RE = re.compile(r"[\w%]+(?:[-'][\w%]+)*", re.UNICODE)
_CLICKBAIT_PATTERNS = (
    re.compile(r"\byou won['’]t believe\b", re.IGNORECASE),
    re.compile(r"\bwait (?:until|for) the end\b", re.IGNORECASE),
    re.compile(r"\bwhat happens next\b", re.IGNORECASE),
    re.compile(r"\bwill shock you\b", re.IGNORECASE),
    re.compile(r"\bchanges everything\b", re.IGNORECASE),
    re.compile(r"\bthey don['’]t want you to know\b", re.IGNORECASE),
    re.compile(r"\bbefore it['’]s too late\b", re.IGNORECASE),
    re.compile(r"\bmust watch\b", re.IGNORECASE),
    re.compile(r"\bthis proves\b", re.IGNORECASE),
    re.compile(r"\bthe shocking truth\b", re.IGNORECASE),
)
_WITHHOLDING_PATTERNS = (
    re.compile(r"\bkeep watching\b", re.IGNORECASE),
    re.compile(r"\bstay (?:until|to) (?:find out|see|learn)\b", re.IGNORECASE),
    re.compile(r"\bwe['’]ll reveal (?:it|that|the answer) later\b", re.IGNORECASE),
    re.compile(r"\bi won['’]t tell you yet\b", re.IGNORECASE),
)


def _cadence_role(role: str, order: int) -> str:
    if order == 0:
        return "open"
    return {
        "re-hook": "re-hook",
        "evidence": "evidence-payoff",
        "limitation": "limitation",
        "resolution": "resolve",
    }.get(role, "develop")


def _cadence(beat_plan: BeatPlan) -> BeatCadence:
    starts_at = 0.0
    cadence_beats: list[CadenceBeat] = []
    for beat in beat_plan.beats:
        role = _cadence_role(beat.role, beat.order)
        cadence_beats.append(
            CadenceBeat.model_validate(
                {
                    "beat_id": beat.beat_id,
                    "starts_at_seconds": starts_at,
                    "duration_seconds": beat.approximate_duration,
                    "energy": (
                        "high"
                        if role in {"open", "re-hook"}
                        else "low"
                        if role == "limitation"
                        else "medium"
                    ),
                    "cadence_role": role,
                    "ends_with_forward_motion": role != "resolve",
                }
            )
        )
        starts_at += beat.approximate_duration
    return BeatCadence(
        total_duration_seconds=starts_at,
        max_attention_gap_seconds=5,
        beats=cadence_beats,
    )


def _angle_engagement_copy(angle: str) -> dict[str, str]:
    return {
        "surprising-result": {
            "strategy": "show-result-then-explain",
            "promise": (
                "Resolve the curved-looking blade as a row-timing effect, then show the exact "
                "20 ms evidence example."
            ),
            "primary_question": (
                "How can a blade remain unbent while its recorded shape becomes curved?"
            ),
            "primary_payoff": (
                "Successive rows map motion across time into apparent curvature without proving "
                "that the blade bent."
            ),
            "evidence_question": "How large can the row-to-row timing offset become?",
            "evidence_payoff": (
                "The source's bounded example reaches about 2% image-width offset by the bottom row."
            ),
        },
        "everyday-mechanism": {
            "strategy": "state-mechanism-then-demonstrate",
            "promise": (
                "Use a moving-page scanner analogy, then verify it with the exact sequential-row "
                "and 20 ms evidence."
            ),
            "primary_question": (
                "Why can individually faithful scan lines assemble into a skewed camera frame?"
            ),
            "primary_payoff": (
                "The rows are faithful to different moments, so one assembled frame acts like a "
                "compact timeline."
            ),
            "evidence_question": "What does the scanner analogy predict numerically?",
            "evidence_payoff": (
                "The source's 20 ms example moves from 0% at the top to about 2% at the bottom."
            ),
        },
        "engineering-tradeoff": {
            "strategy": "ask-bounded-question",
            "promise": (
                "Compare sequential and simultaneous row timing, quantify the rolling case, and "
                "state what global exposure still cannot guarantee."
            ),
            "primary_question": (
                "Which distortion changes when rows represent a sequence instead of one instant?"
            ),
            "primary_payoff": (
                "Global exposure avoids this specific row-timing skew, while other distortions "
                "remain separate engineering concerns."
            ),
            "evidence_question": "What scale does the rolling timing example produce?",
            "evidence_payoff": (
                "The documented 20 ms example produces about 2% bottom-row displacement."
            ),
        },
    }[angle]


def _event(
    number: int,
    beat_id: str,
    when: float,
    kind: str,
    device: str,
    purpose: str,
    claim_ids: list[str],
    *,
    resolves: list[str] | None = None,
    sound: str | None = None,
) -> RetentionEvent:
    return RetentionEvent.model_validate(
        {
            "event_id": f"retention-event-{number:02d}",
            "beat_id": beat_id,
            "scheduled_at_seconds": when,
            "event_kind": kind,
            "device": device,
            "purpose": purpose,
            "claim_ids": claim_ids,
            "resolves_thread_ids": resolves or [],
            "sound_design": sound,
        }
    )


def build_rolling_shutter_retention_plan(
    brief: NarrativeBrief,
    beat_plan: BeatPlan,
    script: ScriptManifest,
) -> RetentionPlan:
    """Build an evidence-locked cadence and payoff plan for the fixture narrative."""
    if beat_plan.narrative_brief_version_id != brief.version_id:
        raise ValueError("beat plan does not bind the narrative brief")
    if script.claims_version_id != brief.claims_version_id or script.angle != brief.angle:
        raise ValueError("script does not bind the narrative brief")
    if len(beat_plan.beats) != 8 or len(script.segments) != 8:
        raise ValueError("rolling-shutter retention fixture requires exactly eight compact beats")
    for beat, segment in zip(beat_plan.beats, script.segments, strict=True):
        if abs(beat.approximate_duration - segment.approximate_duration) > 0.01:
            raise ValueError("fixture beat and script durations must stay aligned")
    cadence = _cadence(beat_plan)
    if cadence.beats[0].duration_seconds > 5:
        raise ValueError("fixture cold open must be no longer than five seconds")
    copy = _angle_engagement_copy(brief.angle)
    beats = cadence.beats
    plan_beats = beat_plan.beats
    cold_open = HonestColdOpen.model_validate(
        {
            "hook_id": "cold-open-01",
            "beat_id": beats[0].beat_id,
            "text": script.segments[0].text,
            "claim_ids": script.segments[0].claim_ids,
            "reveal_strategy": copy["strategy"],
            "truth_up_front": True,
            "deceptive_withholding": False,
            "promised_payoff": copy["promise"],
            "payoff_beat_id": beats[7].beat_id,
            "duration_seconds": beats[0].duration_seconds,
        }
    )
    curiosity_threads = [
        CuriosityThread(
            thread_id="thread-primary",
            question=copy["primary_question"],
            opened_at_beat_id=beats[0].beat_id,
            payoff_beat_id=beats[7].beat_id,
            payoff=copy["primary_payoff"],
            claim_ids=list(
                dict.fromkeys([*script.segments[0].claim_ids, *script.segments[7].claim_ids])
            ),
        ),
        CuriosityThread(
            thread_id="thread-evidence",
            question=copy["evidence_question"],
            opened_at_beat_id=beats[1].beat_id,
            payoff_beat_id=beats[3].beat_id,
            payoff=copy["evidence_payoff"],
            claim_ids=plan_beats[3].claim_ids,
        ),
    ]
    attention_events = [
        _event(
            1,
            beats[0].beat_id,
            2,
            "pattern-interrupt",
            "visual-mode-change",
            "Move from the honest opening result into the timing question.",
            plan_beats[0].claim_ids,
            sound="soft-hit",
        ),
        _event(
            2,
            beats[1].beat_id,
            beats[1].starts_at_seconds + 2,
            "re-hook",
            "question-pivot",
            "Turn the opening result into a bounded mechanism question.",
            plan_beats[1].claim_ids,
        ),
        _event(
            3,
            beats[2].beat_id,
            beats[2].starts_at_seconds,
            "pattern-interrupt",
            "visual-mode-change",
            "Switch from the setup view to row-by-row capture.",
            plan_beats[2].claim_ids,
            sound="scan-pulse",
        ),
        _event(
            4,
            beats[2].beat_id,
            beats[2].starts_at_seconds + 5,
            "pattern-interrupt",
            "parameter-change",
            "Change one bounded visual parameter before presenting the evidence receipt.",
            plan_beats[2].claim_ids,
        ),
        _event(
            5,
            beats[3].beat_id,
            beats[3].starts_at_seconds + 3,
            "evidence-payoff",
            "source-receipt",
            "Pay off the numeric question with exact visible evidence.",
            plan_beats[3].claim_ids,
            resolves=["thread-evidence"],
            sound="source-click",
        ),
        _event(
            6,
            beats[4].beat_id,
            beats[4].starts_at_seconds + 1,
            "re-hook",
            "misconception-correction",
            "Reframe the image as a timing record before the comparison.",
            plan_beats[4].claim_ids,
        ),
        _event(
            7,
            beats[5].beat_id,
            beats[5].starts_at_seconds,
            "re-hook",
            "comparison-switch",
            "Ask a second bounded question while switching to the shutter-timing comparison.",
            plan_beats[5].claim_ids,
            sound="contrast-shift",
        ),
        _event(
            8,
            beats[5].beat_id,
            beats[5].starts_at_seconds + 1,
            "pattern-interrupt",
            "visual-mode-change",
            "Change visual mode as the second bounded question begins to resolve.",
            plan_beats[5].claim_ids,
        ),
        _event(
            9,
            beats[5].beat_id,
            beats[5].starts_at_seconds + 6,
            "pattern-interrupt",
            "parameter-change",
            "Hold the comparison while one bounded parameter changes.",
            plan_beats[5].claim_ids,
        ),
        _event(
            10,
            beats[6].beat_id,
            beats[6].starts_at_seconds + 4,
            "limitation-reframe",
            "misconception-correction",
            "Protect the explanation from becoming a perfect-image claim.",
            plan_beats[6].claim_ids,
        ),
        _event(
            11,
            beats[7].beat_id,
            beats[7].starts_at_seconds + 2,
            "pattern-interrupt",
            "callback",
            "Return to the opening visual with the mechanism now visible.",
            plan_beats[7].claim_ids,
        ),
        _event(
            12,
            beats[7].beat_id,
            cadence.total_duration_seconds - 2,
            "final-payoff",
            "callback",
            "Resolve the opening promise without asking for engagement.",
            plan_beats[7].claim_ids,
            resolves=["thread-primary"],
            sound="resolve-tone",
        ),
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
        "evidence_payoff_beat_id": beats[3].beat_id,
        "evidence_claim_ids": brief.evidence_claim_ids,
        "meaningful_limitation_beat_id": beats[6].beat_id,
        "meaningful_limitation_claim_ids": brief.limitation_claim_ids,
        "target_word_count": (130, 170),
    }
    payload["version_id"] = derive_creative_id("retention", payload)
    return RetentionPlan.model_validate(payload)


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _contains_pattern(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def critique_retention(
    plan: RetentionPlan,
    brief: NarrativeBrief,
    beat_plan: BeatPlan,
    script: ScriptManifest,
) -> RetentionCritique:
    """Deterministically enforce honest retention without treating engagement as proof."""
    findings: list[RetentionFinding] = []
    if (
        plan.narrative_brief_version_id != brief.version_id
        or plan.beat_plan_version_id != beat_plan.version_id
        or plan.script_version_id != script.version_id
        or plan.claims_version_id != brief.claims_version_id
    ):
        findings.append(
            RetentionFinding(
                category="payoff-drift",
                severity="error",
                message="Retention plan does not bind the current brief, beat plan, and script.",
            )
        )
    locks = {lock.claim_id: lock.claim_state_hash for lock in brief.factual_locks}
    if {lock.claim_id: lock.claim_state_hash for lock in plan.factual_locks} != locks:
        findings.append(
            RetentionFinding(
                category="unsupported-engagement-claim",
                severity="error",
                message="Retention factual locks differ from the narrative brief.",
            )
        )
    if set(plan.evidence_claim_ids) != set(brief.evidence_claim_ids):
        findings.append(
            RetentionFinding(
                category="missing-evidence",
                severity="error",
                message="Retention evidence-payoff claims differ from the narrative brief.",
            )
        )
    if set(plan.meaningful_limitation_claim_ids) != set(brief.limitation_claim_ids):
        findings.append(
            RetentionFinding(
                category="missing-limitation",
                severity="error",
                message="Retention limitation claims differ from the narrative brief.",
            )
        )
    first_segment = script.segments[0] if script.segments else None
    if (
        first_segment is None
        or first_segment.segment_type != "hook"
        or first_segment.text != plan.cold_open.text
        or first_segment.claim_ids != plan.cold_open.claim_ids
        or first_segment.approximate_duration > 5
    ):
        findings.append(
            RetentionFinding(
                category="hook-drift",
                severity="error",
                message="Script opening no longer matches the approved honest cold open.",
                segment_id=first_segment.segment_id if first_segment else None,
            )
        )
    all_copy = [
        plan.cold_open.text,
        plan.cold_open.promised_payoff,
        *(thread.question for thread in plan.curiosity_threads),
        *(thread.payoff for thread in plan.curiosity_threads),
        *(segment.text for segment in script.segments),
    ]
    if any(_contains_pattern(text, _CLICKBAIT_PATTERNS) for text in all_copy):
        findings.append(
            RetentionFinding(
                category="clickbait-language",
                severity="error",
                message="Opening, curiosity, payoff, or narration contains clickbait language.",
            )
        )
    if any(_contains_pattern(text, _WITHHOLDING_PATTERNS) for text in all_copy):
        findings.append(
            RetentionFinding(
                category="deceptive-withholding",
                severity="error",
                message="Narrative asks for continued attention instead of giving an honest promise.",
            )
        )
    spoken_word_count = sum(len(_words(segment.text)) for segment in script.segments)
    spoken_words_per_minute = spoken_word_count / plan.cadence.total_duration_seconds * 60
    if not 130 <= spoken_word_count <= 170:
        findings.append(
            RetentionFinding(
                category="word-count",
                severity="error",
                message=f"Script has {spoken_word_count} words; retention target is 130–170.",
            )
        )
    if spoken_words_per_minute > 175:
        findings.append(
            RetentionFinding(
                category="cadence",
                severity="error",
                message=(
                    f"Narration pace is {spoken_words_per_minute:.1f} words per minute; "
                    "readable target is at most 175."
                ),
            )
        )
    elif spoken_words_per_minute < 145:
        findings.append(
            RetentionFinding(
                category="cadence",
                severity="warning",
                message=(
                    f"Narration pace is {spoken_words_per_minute:.1f} words per minute; "
                    "the brisk target is approximately 150–175."
                ),
            )
        )
    for index, segment in enumerate(script.segments):
        segment_rate = len(_words(segment.text)) / segment.approximate_duration * 60
        rate_ceiling = 175 if index == 0 else 190
        if segment_rate > rate_ceiling + 0.01:
            findings.append(
                RetentionFinding(
                    category="cadence",
                    severity="error",
                    message=(
                        f"Segment {segment.segment_id} is {segment_rate:.1f} words per minute; "
                        f"its readable ceiling is {rate_ceiling}."
                    ),
                    segment_id=segment.segment_id,
                )
            )
    script_claims = {claim_id for segment in script.segments for claim_id in segment.claim_ids}
    unknown_claims = script_claims - set(locks)
    if unknown_claims:
        findings.append(
            RetentionFinding(
                category="unsupported-engagement-claim",
                severity="error",
                message=f"Script references unlocked claims: {sorted(unknown_claims)}",
            )
        )
    if not (set(brief.evidence_claim_ids) & script_claims):
        findings.append(
            RetentionFinding(
                category="missing-evidence",
                severity="error",
                message="Retention draft omits the brief's visible evidence claims.",
            )
        )
    limitation_segments = [
        segment for segment in script.segments if segment.segment_type == "limitation"
    ]
    if not limitation_segments or not any(
        set(segment.claim_ids) & set(brief.limitation_claim_ids) for segment in limitation_segments
    ):
        findings.append(
            RetentionFinding(
                category="missing-limitation",
                severity="error",
                message="Retention draft omits the evidence-linked meaningful limitation.",
            )
        )
    if len(script.segments) != len(plan.cadence.beats):
        findings.append(
            RetentionFinding(
                category="cadence",
                severity="error",
                message="Script segment count no longer matches the approved cadence.",
            )
        )
    else:
        for segment, cadence_beat in zip(script.segments, plan.cadence.beats, strict=True):
            if abs(segment.approximate_duration - cadence_beat.duration_seconds) > 0.01:
                findings.append(
                    RetentionFinding(
                        category="cadence",
                        severity="error",
                        message="Script timing no longer matches the approved compact cadence.",
                        segment_id=segment.segment_id,
                        beat_id=cadence_beat.beat_id,
                    )
                )
    mid_rehook_ids = {
        event.beat_id
        for event in plan.attention_events
        if event.event_kind == "re-hook"
        and plan.cadence.total_duration_seconds * 0.35
        <= event.scheduled_at_seconds
        <= plan.cadence.total_duration_seconds * 0.65
    }
    for cadence_beat, segment in zip(plan.cadence.beats, script.segments, strict=False):
        if cadence_beat.beat_id in mid_rehook_ids and segment.segment_type != "hook":
            findings.append(
                RetentionFinding(
                    category="cadence",
                    severity="error",
                    message="Mid-video retention event is not represented as a script re-hook.",
                    beat_id=cadence_beat.beat_id,
                    segment_id=segment.segment_id,
                )
            )
    events_by_thread: dict[str, list[RetentionEvent]] = {}
    for event in plan.attention_events:
        for thread_id in event.resolves_thread_ids:
            events_by_thread.setdefault(thread_id, []).append(event)
    for thread in plan.curiosity_threads:
        payoff_events = events_by_thread.get(thread.thread_id, [])
        if not payoff_events:
            findings.append(
                RetentionFinding(
                    category="missing-payoff",
                    severity="error",
                    message=f"Curiosity thread {thread.thread_id} has no explicit payoff event.",
                    beat_id=thread.payoff_beat_id,
                )
            )
        elif any(event.beat_id != thread.payoff_beat_id for event in payoff_events) or not any(
            set(event.claim_ids) & set(thread.claim_ids) for event in payoff_events
        ):
            findings.append(
                RetentionFinding(
                    category="payoff-drift",
                    severity="error",
                    message=f"Curiosity thread {thread.thread_id} resolves at the wrong beat or claim.",
                    beat_id=thread.payoff_beat_id,
                )
            )
    times = [0.0, *(event.scheduled_at_seconds for event in plan.attention_events)]
    times.append(plan.cadence.total_duration_seconds)
    allowed_attention_gap = min(plan.cadence.max_attention_gap_seconds, 5)
    if any(
        later - earlier > allowed_attention_gap + 0.01
        for earlier, later in zip(times, times[1:], strict=False)
    ):
        findings.append(
            RetentionFinding(
                category="attention-gap",
                severity="error",
                message="Attention-event cadence has a gap longer than five seconds.",
            )
        )
    input_hash = stable_hash(
        {
            "retention_plan_version_id": plan.version_id,
            "narrative_brief_version_id": brief.version_id,
            "beat_plan_version_id": beat_plan.version_id,
            "script_version_id": script.version_id,
        }
    )
    payload: dict[str, object] = {
        "retention_plan_version_id": plan.version_id,
        "narrative_brief_version_id": brief.version_id,
        "beat_plan_version_id": beat_plan.version_id,
        "script_version_id": script.version_id,
        "input_hash": input_hash,
        "spoken_word_count": spoken_word_count,
        "spoken_words_per_minute": spoken_words_per_minute,
        "findings": findings,
        "blocking": any(item.severity == "error" for item in findings),
    }
    payload["critique_id"] = derive_creative_id("retention-critique", payload)
    return RetentionCritique.model_validate(payload)
