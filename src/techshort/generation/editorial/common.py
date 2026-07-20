from __future__ import annotations

from techshort.domain.creative import FactualLock
from techshort.domain.hashing import stable_hash
from techshort.domain.models import AngleSelection, AnglesManifest, ClaimsManifest


def claim_locks(claims: ClaimsManifest) -> list[FactualLock]:
    return [
        FactualLock(
            claim_id=claim.claim_id,
            claim_state_hash=stable_hash(
                {
                    "claim": claim,
                    "claims_version_id": claims.version_id,
                    "evidence_version_id": claims.evidence_version_id,
                }
            ),
            approval_hash=claim.approval_hash,
            assertion=claim.text,
            evidence_span_ids=claim.evidence_span_ids,
        )
        for claim in claims.claims
    ]


def selected_candidate(angles: AnglesManifest, selection: AngleSelection) -> list[str]:
    if selection.angles_version_id != angles.version_id:
        raise ValueError("angle selection does not bind the supplied angles manifest")
    candidate = next(
        (item for item in angles.candidates if item.angle == selection.selected_angle), None
    )
    if candidate is None or stable_hash(candidate) != selection.selected_candidate_hash:
        raise ValueError("angle selection candidate hash is stale or invalid")
    return candidate.central_claim_ids


def validate_claims_exist(claims: ClaimsManifest, required: set[str]) -> None:
    available = {claim.claim_id for claim in claims.claims}
    missing = required - available
    if missing:
        raise ValueError(f"rolling-shutter creative fixture is missing claims: {sorted(missing)}")
