from __future__ import annotations

from techshort.domain.creative import BeatPlan, NarrativeBrief
from techshort.domain.models import (
    ScriptManifest,
    ScriptSegment,
    derive_script_version_id,
)

_DURATIONS = (5.0, 7.0, 7.0, 7.0, 6.0, 7.0, 7.0, 6.0)


def _segment(
    number: int,
    text: str,
    segment_type: str,
    claims: list[str],
) -> ScriptSegment:
    return ScriptSegment.model_validate(
        {
            "segment_id": f"segment-{number:02d}",
            "text": text,
            "segment_type": segment_type,
            "claim_ids": claims,
            "approximate_duration": _DURATIONS[number - 1],
        }
    )


def rolling_shutter_script_segments(angle: str) -> list[ScriptSegment]:
    """Return the brisk, evidence-linked fixture narration for one selected angle."""
    if angle == "surprising-result":
        content = [
            (
                "A rotating blade can look curved without bending. The source points to capture timing.",
                "hook",
                ["claim-motion-skew", "claim-timing-interpretation"],
            ),
            (
                "Rolling shutter records sensor rows in sequence, so one frame contains slightly different moments from top to bottom.",
                "factual",
                ["claim-row-timing"],
            ),
            (
                "While the blade or camera moves, each row catches a new position. Assembled together, those rows turn straight motion into skew.",
                "factual",
                ["claim-row-timing", "claim-motion-skew"],
            ),
            (
                "The source's 20-millisecond example starts at zero percent offset and reaches about two percent by the bottom row.",
                "factual",
                ["claim-numeric-demo"],
            ),
            (
                "So did the blade bend? No—the frame can be mapping motion across readout time.",
                "hook",
                ["claim-motion-skew", "claim-timing-interpretation"],
            ),
            (
                "What changes the effect? Faster motion or a longer readout increases skew; exposing all rows together avoids this timing effect.",
                "hook",
                ["claim-parameters", "claim-global", "claim-row-timing"],
            ),
            (
                "That does not guarantee perfect geometry. Motion blur, lens distortion, stabilization, resampling, and image processing can still change the recorded result.",
                "limitation",
                ["claim-limitation"],
            ),
            (
                "The curved image is therefore a timing map of motion, not proof that the blade physically bent.",
                "cta",
                ["claim-timing-interpretation"],
            ),
        ]
    elif angle == "everyday-mechanism":
        content = [
            (
                "A rolling-shutter frame is a page scanned while it moves—not one frozen instant.",
                "hook",
                ["claim-row-timing", "claim-scan-analogy"],
            ),
            (
                "The sensor reads rows in sequence, so neighboring lines can describe different instants.",
                "factual",
                ["claim-row-timing"],
            ),
            (
                "Picture paper sliding sideways under a scanner. Every line can be accurate while the assembled page becomes skewed.",
                "analogy",
                ["claim-scan-analogy", "claim-motion-skew"],
            ),
            (
                "The source shows a 20-millisecond readout moving from zero percent offset at the top to about two percent at the bottom.",
                "factual",
                ["claim-row-timing", "claim-numeric-demo"],
            ),
            (
                "What controls that skew? The distance the subject moves while the rows are being read.",
                "hook",
                ["claim-parameters", "claim-row-timing", "claim-numeric-demo"],
            ),
            (
                "Would shared timing change it? Faster motion or longer readout increases skew; a global shutter exposes rows together and avoids it.",
                "hook",
                ["claim-parameters", "claim-global"],
            ),
            (
                "This explains one distortion, not every distortion. Blur, lens effects, stabilization, resampling, and processing can still alter recorded geometry.",
                "limitation",
                ["claim-limitation"],
            ),
            (
                "The useful model is one frame assembled from many row-level moments—like a tiny timeline.",
                "cta",
                ["claim-row-timing", "claim-motion-skew"],
            ),
        ]
    elif angle == "engineering-tradeoff":
        content = [
            (
                "A camera frame can hold one shared instant—or a sequence of row-level instants.",
                "hook",
                ["claim-row-timing", "claim-global"],
            ),
            (
                "A rolling shutter records rows in sequence across a frame-readout interval.",
                "factual",
                ["claim-row-timing"],
            ),
            (
                "During motion, successive rows capture different positions. Assembly can turn a straight edge into a slant or curved blade.",
                "factual",
                ["claim-motion-skew"],
            ),
            (
                "The source's 20-millisecond example quantifies it: zero percent offset at the top and about two percent at the bottom.",
                "factual",
                ["claim-numeric-demo"],
            ),
            (
                "Does simultaneous exposure solve image distortion? It solves this row-timing skew, not every geometry error.",
                "hook",
                ["claim-global", "claim-limitation"],
            ),
            (
                "What can engineers change? A global shutter exposes rows together; faster motion or longer readout increases visible rolling skew.",
                "hook",
                ["claim-global", "claim-parameters", "claim-numeric-demo"],
            ),
            (
                "Neither statement guarantees a perfect image. Blur, lens distortion, stabilization, resampling, and processing can still change recorded geometry.",
                "limitation",
                ["claim-limitation"],
            ),
            (
                "The precise engineering distinction is shared-instant exposure versus sequential row timing, with other distortions reviewed separately.",
                "cta",
                ["claim-row-timing", "claim-global", "claim-limitation"],
            ),
        ]
    else:
        raise ValueError(f"unsupported fixture angle: {angle}")
    return [
        _segment(index, text, segment_type, claim_ids)
        for index, (text, segment_type, claim_ids) in enumerate(content, 1)
    ]


def build_rolling_shutter_script(brief: NarrativeBrief, plan: BeatPlan) -> ScriptManifest:
    """Draft angle-specific narration while retaining exact claim-ID constraints."""
    if plan.narrative_brief_version_id != brief.version_id or plan.angle != brief.angle:
        raise ValueError("beat plan does not bind the supplied narrative brief")
    segments = rolling_shutter_script_segments(brief.angle)
    allowed = {lock.claim_id for lock in brief.factual_locks}
    unknown = {claim_id for segment in segments for claim_id in segment.claim_ids} - allowed
    if unknown:
        raise ValueError(f"script would escape factual locks: {sorted(unknown)}")
    version_id = derive_script_version_id(
        brief.claims_version_id,
        brief.angles_version_id,
        brief.angle_selection_id,
        brief.angle,
        segments,
    )
    return ScriptManifest(
        version_id=version_id,
        claims_version_id=brief.claims_version_id,
        angles_version_id=brief.angles_version_id,
        angle_selection_id=brief.angle_selection_id,
        angle=brief.angle,
        segments=segments,
    )
