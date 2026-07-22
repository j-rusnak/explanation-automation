from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from techshort.domain.hashing import stable_hash
from techshort.publication.models import (
    HumanPublicationConsent,
    OrganicPackageRequest,
    OrganicPlatform,
    OrganicPostMetadata,
    PlatformProviderDiagnostic,
)


class PlatformUnavailableError(RuntimeError):
    """Raised when an official posting integration is intentionally unavailable."""


@dataclass(frozen=True)
class PreparedOrganicPackage:
    metadata: OrganicPostMetadata
    checklist_markdown: str


class OrganicPlatformProvider(Protocol):
    platform: OrganicPlatform
    provider_name: str

    def diagnostics(self) -> PlatformProviderDiagnostic: ...

    def prepare(
        self,
        request: OrganicPackageRequest,
        package_input_hash: str,
        consent: HumanPublicationConsent,
    ) -> PreparedOrganicPackage: ...


class ManualOrganicProvider:
    """Build paste-ready local handoff files without contacting a platform."""

    provider_name = "manual-organic"

    def __init__(self, platform: OrganicPlatform) -> None:
        self.platform = platform

    def diagnostics(self) -> PlatformProviderDiagnostic:
        return PlatformProviderDiagnostic(
            provider_name=self.provider_name,
            platform=self.platform,
            status="manual-ready",
            local_package_supported=True,
            reason=(
                "Local package generation is available. Publication remains a deliberate "
                "human action in the platform's own composer."
            ),
            next_steps=[
                "Build and inspect the local organic package.",
                "Record explicit consent for the exact immutable variant.",
                "Complete the platform checklist and upload manually.",
            ],
        )

    def prepare(
        self,
        request: OrganicPackageRequest,
        package_input_hash: str,
        consent: HumanPublicationConsent,
    ) -> PreparedOrganicPackage:
        if request.platform != self.platform:
            raise ValueError("manual organic provider platform does not match the request")
        if (
            consent.experiment_id != request.experiment_id
            or consent.variant_id != request.variant_id
            or consent.platform != request.platform
            or consent.package_input_hash != package_input_hash
        ):
            raise ValueError("human publication consent does not bind this exact variant input")
        hashtags = [f"#{item}" for item in request.hashtags]
        caption_text = request.post_copy.strip()
        if hashtags:
            caption_text += "\n\n" + " ".join(hashtags)
        if len(caption_text) > 2200:
            raise ValueError("platform caption package exceeds the conservative 2200-character cap")
        metadata_payload: dict[str, object] = {
            "schema_version": "1.0.0",
            "experiment_id": request.experiment_id,
            "variant_id": request.variant_id,
            "platform": request.platform,
            "title": request.title,
            "caption_text": caption_text,
            "alt_text": request.alt_text,
            "hashtags": request.hashtags,
            "evidence_url": request.evidence_url,
            "video_filename": "video.mp4",
            "cover_filename": "cover.png",
            "captions_srt_filename": "captions.srt",
            "captions_vtt_filename": "captions.vtt",
            "aspect_ratio": "9:16",
            "expected_dimensions": "1080x1920",
            "duration_window_seconds": (45, 75),
            "consent_receipt_id": consent.receipt_id,
            "consent_state": consent.state,
            "manual_upload_authorized": consent.state == "granted",
            "automated_upload": False,
            "claimed_posted": False,
        }
        metadata_hash = stable_hash(metadata_payload)
        metadata_payload.update(
            {
                "metadata_id": f"organic-metadata-{metadata_hash[:16]}",
                "metadata_hash": metadata_hash,
            }
        )
        metadata = OrganicPostMetadata.model_validate(metadata_payload)
        return PreparedOrganicPackage(
            metadata=metadata,
            checklist_markdown=self._checklist(request, consent),
        )

    def _checklist(self, request: OrganicPackageRequest, consent: HumanPublicationConsent) -> str:
        platform_name = "TikTok" if request.platform == "tiktok" else "Instagram Reels"
        consent_checked = "x" if consent.state == "granted" else " "
        evidence_checked = "x" if request.evidence_url else " "
        platform_steps = (
            [
                "Open TikTok's own upload composer and select video.mp4.",
                "Use cover.png as the approved reference; select or recreate the matching "
                "cover/frame only if the current composer supports it, then inspect the crop.",
            ]
            if request.platform == "tiktok"
            else [
                "Open Instagram's own Reels composer and select video.mp4.",
                "Use cover.png as the approved reference; select or recreate the matching "
                "cover/frame only if the current composer supports it, then inspect all crops.",
            ]
        )
        lines = [
            f"# Manual organic publication checklist — {platform_name}",
            "",
            "**This package has not been posted. No automated upload was attempted.**",
            "",
            f"Experiment: `{request.experiment_id}`  ",
            f"Variant: `{request.variant_id}`  ",
            f"Consent: **{consent.state}** (`{consent.receipt_id}`)",
            "",
            "## Required human checks",
            "",
            "- [x] Package files were copied locally and checksummed.",
            f"- [{consent_checked}] Explicit human publication consent is granted for this exact package hash.",
            "- [ ] Watch the complete local MP4 with sound and confirm it is the intended variant.",
            "- [ ] Confirm factual meaning, evidence labels, and the limitation remain accurate.",
            "- [ ] Confirm captions are readable and important content stays inside platform safe zones.",
            "- [ ] Confirm the cover is accurate, legible, and not misleading.",
            "- [ ] Confirm music, voice, fonts, imagery, and other assets remain rights-cleared.",
            f"- [{evidence_checked}] Add the public evidence/correction link where the platform permits it.",
            "- [ ] Review the platform's current synthetic-media and branded-content disclosures.",
            "- [ ] Choose the intended account, audience, privacy, comments, and remix settings manually.",
            "",
            "## Manual composer steps",
            "",
            *[f"- [ ] {step}" for step in platform_steps],
            "- [ ] Paste caption_text from post-metadata.json; do not add unsupported factual claims.",
            "- [ ] Confirm the burned captions and audio work in the platform preview.",
            "- [ ] Publish only after every required item above is complete.",
            "- [ ] After publication, record the public URL and observations outside this immutable package.",
            "",
        ]
        return "\n".join(lines)


class UnavailablePlatformProvider:
    """Diagnostic placeholder for official APIs that are not locally configured."""

    def __init__(self, platform: OrganicPlatform) -> None:
        self.platform = platform
        self.provider_name = (
            "tiktok-official-content-posting-api"
            if platform == "tiktok"
            else "instagram-official-graph-api"
        )

    def diagnostics(self) -> PlatformProviderDiagnostic:
        return PlatformProviderDiagnostic(
            provider_name=self.provider_name,
            platform=self.platform,
            status="unavailable",
            local_package_supported=False,
            reason=(
                "Official automated publication is unavailable: it requires separately "
                "provisioned platform access and credentials. techshort did not read or store "
                "any credentials."
            ),
            next_steps=[
                "Use ManualOrganicProvider for a local human-reviewed package.",
                "Provision and approve a future official integration separately if needed.",
            ],
        )

    def prepare(
        self,
        request: OrganicPackageRequest,
        package_input_hash: str,
        consent: HumanPublicationConsent,
    ) -> PreparedOrganicPackage:
        del request, package_input_hash, consent
        diagnostic = self.diagnostics()
        raise PlatformUnavailableError(
            f"{diagnostic.provider_name} is unavailable for {diagnostic.platform}: "
            f"{diagnostic.reason}"
        )


def official_api_provider(platform: OrganicPlatform) -> UnavailablePlatformProvider:
    """Return a non-networking diagnostic provider; no credentials are accepted."""

    return UnavailablePlatformProvider(platform)
