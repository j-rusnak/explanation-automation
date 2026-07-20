from __future__ import annotations

from techshort.domain.creative import BeatPlan, NarrativeBrief
from techshort.domain.models import (
    ScriptManifest,
    ScriptSegment,
    derive_script_version_id,
)


def _segment(
    number: int,
    text: str,
    segment_type: str,
    claims: list[str],
    seconds: float,
) -> ScriptSegment:
    return ScriptSegment.model_validate(
        {
            "segment_id": f"segment-{number:02d}",
            "text": text,
            "segment_type": segment_type,
            "claim_ids": claims,
            "approximate_duration": seconds,
        }
    )


def build_rolling_shutter_script(brief: NarrativeBrief, plan: BeatPlan) -> ScriptManifest:
    """Draft angle-specific narration while retaining exact claim-ID constraints."""
    if plan.narrative_brief_version_id != brief.version_id or plan.angle != brief.angle:
        raise ValueError("beat plan does not bind the supplied narrative brief")
    if brief.angle == "surprising-result":
        segments = [
            _segment(
                1,
                "A rotating blade can look curved in a camera frame, even when the blade itself did not bend.",
                "hook",
                ["claim-motion-skew", "claim-timing-interpretation"],
                7,
            ),
            _segment(
                2,
                "That strange shape can be a map of capture time, not physical geometry.",
                "factual",
                ["claim-timing-interpretation"],
                7,
            ),
            _segment(
                3,
                "A rolling-shutter sensor records rows in sequence. While the blade moves, each row captures a slightly different moment.",
                "factual",
                ["claim-row-timing", "claim-motion-skew"],
                11,
            ),
            _segment(
                4,
                "The source gives a simple example: over a 20-millisecond readout, steady motion leaves the top row at zero percent offset and the bottom about two percent later across the image width.",
                "factual",
                ["claim-numeric-demo"],
                10,
            ),
            _segment(
                5,
                "Stack those faithful row slices into one frame and the moving straight edge becomes slanted; a rotating blade can appear curved.",
                "factual",
                ["claim-motion-skew"],
                9,
            ),
            _segment(
                6,
                "A global shutter exposes rows together, so it avoids this row-timing skew.",
                "factual",
                ["claim-global"],
                7,
            ),
            _segment(
                7,
                "But that does not guarantee perfect geometry. Motion blur, lens distortion, stabilization, resampling, and image processing can still change the result.",
                "limitation",
                ["claim-limitation"],
                9,
            ),
            _segment(
                8,
                "So the curved-looking blade is useful evidence of motion plus row timing—not proof that the blade physically bent.",
                "cta",
                ["claim-timing-interpretation"],
                6,
            ),
        ]
    elif brief.angle == "everyday-mechanism":
        segments = [
            _segment(
                1,
                "Imagine scanning a page line by line while someone slides the paper sideways.",
                "hook",
                ["claim-scan-analogy"],
                7,
            ),
            _segment(
                2,
                "Each scanned line can be accurate, yet the assembled page looks skewed because every line captured a different position.",
                "analogy",
                ["claim-scan-analogy", "claim-motion-skew"],
                8,
            ),
            _segment(
                3,
                "A rolling-shutter camera works with the same timing idea: its sensor records image rows in sequence across a frame-readout interval.",
                "factual",
                ["claim-row-timing", "claim-scan-analogy"],
                9,
            ),
            _segment(
                4,
                "If the subject or camera moves during that interval, successive rows preserve different moments. A straight edge can look slanted, and a rotating blade can look curved.",
                "factual",
                ["claim-row-timing", "claim-motion-skew"],
                11,
            ),
            _segment(
                5,
                "In the source's 20-millisecond example, a steadily moving edge has zero percent offset at the top and about two percent by the bottom row.",
                "factual",
                ["claim-numeric-demo"],
                9,
            ),
            _segment(
                6,
                "Faster motion or a longer readout makes that visible skew larger.",
                "factual",
                ["claim-parameters"],
                8,
            ),
            _segment(
                7,
                "This explains one distortion, not every distortion. Blur, lens effects, stabilization, resampling, and processing can still alter recorded geometry.",
                "limitation",
                ["claim-limitation"],
                8,
            ),
            _segment(
                8,
                "The useful mental model is simple: one rolling-shutter frame can contain many row-level moments assembled as one picture.",
                "cta",
                ["claim-row-timing", "claim-motion-skew"],
                6,
            ),
        ]
    else:
        segments = [
            _segment(
                1,
                "Does a camera frame represent one instant, or a short sequence of instants? The shutter timing decides.",
                "hook",
                ["claim-row-timing", "claim-global"],
                7,
            ),
            _segment(
                2,
                "A rolling shutter records sensor rows in sequence over a frame-readout interval.",
                "factual",
                ["claim-row-timing"],
                10,
            ),
            _segment(
                3,
                "If the subject or camera moves during that interval, each row captures a different moment, so straight motion can appear skewed.",
                "factual",
                ["claim-motion-skew"],
                9,
            ),
            _segment(
                4,
                "A global shutter exposes all rows together, which avoids this specific row-timing skew.",
                "factual",
                ["claim-global"],
                9,
            ),
            _segment(
                5,
                "The source's rolling example makes the scale concrete: a 20-millisecond readout with steady motion produces zero percent top-row offset and about two percent at the bottom.",
                "factual",
                ["claim-numeric-demo"],
                10,
            ),
            _segment(
                6,
                "For rolling capture, faster motion or a longer readout increases visible skew.",
                "factual",
                ["claim-parameters"],
                8,
            ),
            _segment(
                7,
                "Avoiding row-timing skew is not a perfect-image guarantee. Motion blur, lens distortion, stabilization, resampling, and processing can still change recorded geometry.",
                "limitation",
                ["claim-limitation"],
                9,
            ),
            _segment(
                8,
                "The precise comparison is timing: rolling rows represent a sequence, while global rows share an exposure instant.",
                "cta",
                ["claim-row-timing", "claim-global"],
                6,
            ),
        ]
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
