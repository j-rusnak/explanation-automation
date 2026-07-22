from __future__ import annotations

from techshort.domain.creative import NarrativeBrief, derive_creative_id
from techshort.domain.models import AngleSelection, AnglesManifest, ClaimsManifest
from techshort.generation.editorial.common import (
    claim_locks,
    selected_candidate,
    validate_claims_exist,
)


def build_rolling_shutter_brief(
    claims: ClaimsManifest,
    angles: AnglesManifest,
    selection: AngleSelection,
) -> NarrativeBrief:
    """Build a deterministic, angle-specific brief from immutable claim snapshots."""
    central_claim_ids = selected_candidate(angles, selection)
    required = {
        "claim-row-timing",
        "claim-motion-skew",
        "claim-parameters",
        "claim-global",
        "claim-limitation",
        "claim-numeric-demo",
        "claim-scan-analogy",
        "claim-timing-interpretation",
    }
    validate_claims_exist(claims, required)
    angle_copy = {
        "surprising-result": {
            "promise": (
                "Resolve why a rotating blade can look curved without claiming that "
                "the blade physically changed shape."
            ),
            "mechanism": (
                "A frame assembled from rows captured at successive moments maps moving "
                "geometry into apparent bend or skew."
            ),
            "evidence": (
                "Show the source-backed 20 ms readout example, then reveal the approximately "
                "2% bottom-row displacement."
            ),
            "motif": (
                "Hold a straight blade silhouette beside its scanline-by-scanline curved "
                "recording, using a moving time cursor as the reveal."
            ),
        },
        "everyday-mechanism": {
            "promise": (
                "Make rolling shutter intuitive by treating the sensor like a scanner that "
                "reads a moving page one line at a time."
            ),
            "mechanism": (
                "Successive sensor rows preserve different instants, just as lines scanned "
                "while a page slides preserve different page positions."
            ),
            "evidence": (
                "Expose the exact source sentence about sequential rows, followed by the 20 ms "
                "and approximately 2% worked example."
            ),
            "motif": (
                "Use one persistent scanline traveling down a sensor grid while a straight "
                "edge moves sideways and the captured samples assemble."
            ),
        },
        "engineering-tradeoff": {
            "promise": (
                "Compare rolling and global shutter timing precisely without implying that "
                "either design guarantees a perfect image."
            ),
            "mechanism": (
                "Rolling shutter records rows successively; global shutter exposes rows "
                "together and therefore avoids this specific row-timing skew."
            ),
            "evidence": (
                "Use the documented rolling-versus-global statements and quantify the rolling "
                "case with the source's 20 ms example."
            ),
            "motif": (
                "Keep matched sensor grids side by side: a traveling scanline for rolling and "
                "a single synchronized flash for global."
            ),
        },
    }[selection.selected_angle]
    evidence_claim_ids = (
        ["claim-numeric-demo", "claim-motion-skew"]
        if selection.selected_angle == "surprising-result"
        else ["claim-row-timing", "claim-numeric-demo"]
        if selection.selected_angle == "everyday-mechanism"
        else ["claim-global", "claim-numeric-demo"]
    )
    payload: dict[str, object] = {
        "claims_version_id": claims.version_id,
        "evidence_version_id": claims.evidence_version_id,
        "angles_version_id": angles.version_id,
        "angle_selection_id": selection.selection_id,
        "angle": selection.selected_angle,
        "audience": "Curious non-specialists who use cameras but do not design image sensors.",
        "promise": angle_copy["promise"],
        "central_mechanism": angle_copy["mechanism"],
        "central_claim_ids": central_claim_ids,
        "evidence_claim_ids": evidence_claim_ids,
        "limitation_claim_ids": ["claim-limitation"],
        "visible_evidence": angle_copy["evidence"],
        "meaningful_limitation": (
            "Reducing or avoiding row-timing skew does not remove motion blur, lens distortion, "
            "stabilization, resampling, or other image-processing changes."
        ),
        "visual_motif": angle_copy["motif"],
        "target_word_count": (130, 170),
        "target_duration_seconds": (45.0, 75.0),
        "factual_locks": claim_locks(claims),
    }
    payload["version_id"] = derive_creative_id("brief", payload)
    return NarrativeBrief.model_validate(payload)
