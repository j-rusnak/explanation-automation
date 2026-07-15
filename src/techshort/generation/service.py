from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Literal, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field

from techshort.assets import ensure_builtin_assets
from techshort.domain.hashing import stable_hash
from techshort.domain.models import (
    AngleKind,
    AngleSelection,
    AnglesManifest,
    AssetManifest,
    Claim,
    ClaimCritiqueIssue,
    ClaimCritiqueReport,
    ClaimsManifest,
    EvidenceManifest,
    EvidenceSpan,
    ReviewStatus,
    ScriptManifest,
    SourceDocument,
    StoryboardManifest,
    derive_angle_selection_id,
    derive_angles_version_id,
    derive_script_version_id,
)
from techshort.domain.storage import ProjectStore, atomic_write_model, load_model
from techshort.evidence import unsupported_assertion_tokens
from techshort.ingestion import get_active_source, get_source, verify_source_integrity
from techshort.providers.codex_cli import CodexCliProvider
from techshort.providers.fixture import FixtureProvider
from techshort.providers.manual import ManualPromptPacket, ManualProvider, ManualTask
from techshort.review import (
    claim_review_hash,
    has_current_approval,
    script_segment_review_hash,
)

ProviderName = Literal["fixture", "manual", "codex"]
ArtifactT = TypeVar("ArtifactT", bound=BaseModel)

MAX_EVIDENCE_SPANS = 32
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SECTION_MARKER = re.compile(r"(?m)^--- (?P<heading>[^\r\n]+) ---\n")
SENTENCE = re.compile(r"\S.*?(?:[.!?](?=\s|$)|(?=\n{2,})|$)", re.DOTALL)


CLAIMS_INSTRUCTION = (
    "Create 3 to 8 concise candidate claims. Every claim must cite one or more exact "
    "evidence_id values from the excerpts. Preserve scope, hedging, causal wording, numbers, "
    "and units. Use relationship 'inferred' or 'synthesis' only with explicit reasoning. "
    "Include a meaningful caveat or limitation when the evidence supports one. Set "
    "evidence_version_id exactly to the supplied value and leave all review fields pending."
)
CRITIQUE_INSTRUCTION = (
    "Independently critique every supplied candidate claim against only its cited evidence. "
    "Report genuine unsupported or partially supported claims, missing scope, incorrect causal "
    "wording, omitted uncertainty, mismatched numbers or units, and conflicting evidence. Do not "
    "approve or rewrite claims. Use only supplied claim_id and evidence_id values, set provider to "
    "'codex', and set claims_version_id exactly to the supplied value."
)
SCRIPT_INSTRUCTION = (
    "Write an evidence-linked 130 to 170 word explainer lasting 45 to 75 seconds. Use only "
    "approved claim_id values supplied in the excerpts. Every factual, hook, analogy, caveat, "
    "and limitation segment must cite supporting claims. Include one meaningful limitation, "
    "plain language, honest uncertainty, and no engagement bait. Set claims_version_id, "
    "angles_version_id, angle_selection_id, and angle exactly to the supplied values and leave "
    "review fields pending."
)
ANGLES_INSTRUCTION = (
    "Create exactly three genuinely distinct explainer angles: one surprising-result angle, "
    "one everyday-mechanism angle, and one engineering-tradeoff angle. Give each a meaningful "
    "title, a concise rationale, and one or more central_claim_ids chosen only from the supplied "
    "approved claims. Set claims_version_id exactly to the supplied value. Do not select an "
    "angle; selection is a separate human action."
)
STORYBOARD_INSTRUCTION = (
    "Create a deterministic vertical storyboard covering every supplied script segment. Use "
    "only the allowlisted scene primitives and structured visual fields in the schema. Every "
    "factual scene must carry the relevant approved claim IDs. Do not include paths, HTML, SVG, "
    "or executable text. Keep the total duration from 45 to 75 seconds. Set script_version_id "
    "exactly to the supplied value and leave review fields pending."
)


@dataclass(frozen=True)
class GenerationOutcome(Generic[ArtifactT]):
    """One coherent result shape for fixture, manual, and Codex generation."""

    provider: ProviderName
    artifact: ArtifactT | None = None
    prompt_packet: Path | None = None

    @property
    def requires_manual_import(self) -> bool:
        return self.provider == "manual" and self.artifact is None

    def require_artifact(self) -> ArtifactT:
        if self.artifact is None:
            location = f" at {self.prompt_packet}" if self.prompt_packet else ""
            raise ValueError(f"manual generation requires a validated result import{location}")
        return self.artifact


class GenerationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_version: Literal["1.0.0"] = "1.0.0"
    stage: ManualTask
    provider: ProviderName
    prompt_version: str
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_version: str


def _require_safe_id(value: str, label: str) -> str:
    if not SAFE_ID.fullmatch(value):
        raise ValueError(f"{label} must be a safe stable identifier")
    return value


def _archive(store: ProjectStore, relative: str, version_id: str) -> None:
    current = store.path(relative)
    if not current.exists():
        return
    _require_safe_id(version_id, "artifact version_id")
    versions = current.parent / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    archived = versions / f"{version_id}.json"
    if not archived.exists():
        shutil.copyfile(current, archived)


def _source(store: ProjectStore, source_id: str | None) -> tuple[SourceDocument, str]:
    source = get_active_source(store) if source_id is None else get_source(store, source_id)
    source = verify_source_integrity(store, source)
    if source.ocr_required:
        raise ValueError("source requires OCR, which is unsupported; claims were not generated")
    extracted = store.path(f"sources/extracted/{source.source_id}.txt")
    text = extracted.read_text(encoding="utf-8", errors="strict")
    return source, text


def _section_locations(store: ProjectStore, source: SourceDocument) -> list[dict[str, object]]:
    path = store.path(f"sources/extracted/{source.source_id}.sections.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("source section-location metadata is missing or invalid") from exc
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("source section-location metadata must be a list of objects")
    return [dict(item) for item in value]


def _bounded_ranges(text: str, start: int, end: int) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    body = text[start:end]
    for sentence in SENTENCE.finditer(body):
        left = start + sentence.start()
        right = start + sentence.end()
        while right > left and text[right - 1].isspace():
            right -= 1
        while left < right and text[left].isspace():
            left += 1
        while right - left > 500:
            split = text.rfind(" ", left, left + 500)
            if split <= left:
                split = left + 500
            ranges.append((left, split))
            left = split
            while left < right and text[left].isspace():
                left += 1
        if right > left:
            ranges.append((left, right))
    return ranges


def build_evidence_candidates(
    source_text: str,
    source: SourceDocument,
    *,
    maximum: int = MAX_EVIDENCE_SPANS,
    section_locations: list[dict[str, object]] | None = None,
) -> EvidenceManifest:
    """Create deterministic, exact-offset evidence candidates without model access."""

    if maximum < 1 or maximum > MAX_EVIDENCE_SPANS:
        raise ValueError(f"maximum evidence spans must be between 1 and {MAX_EVIDENCE_SPANS}")
    markers = list(SECTION_MARKER.finditer(source_text))
    sections: list[tuple[str | None, int, int, dict[str, object] | None]] = []
    if markers:
        for index, marker in enumerate(markers):
            end = markers[index + 1].start() if index + 1 < len(markers) else len(source_text)
            location = (
                section_locations[index]
                if section_locations is not None and index < len(section_locations)
                else None
            )
            if location is not None:
                if (
                    location.get("heading") != marker.group("heading")
                    or location.get("start") != marker.end()
                ):
                    raise ValueError("section location metadata does not match extracted text")
            sections.append((marker.group("heading"), marker.end(), end, location))
    else:
        sections.append((None, 0, len(source_text), None))

    spans: list[EvidenceSpan] = []
    for heading, start, end, location in sections:
        for left, right in _bounded_ranges(source_text, start, end):
            excerpt = source_text[left:right]
            if not excerpt:
                continue
            page_index: int | None = None
            printed_page_label: str | None = None
            if source.source_type == "pdf" and heading:
                stored_page_index = location.get("page_index") if location else None
                stored_printed_label = location.get("printed_page_label") if location else None
                if isinstance(stored_page_index, int) and stored_page_index >= 0:
                    page_index = stored_page_index
                else:
                    page_match = re.fullmatch(r"Page\s+(\d+)", heading, re.IGNORECASE)
                    if page_match:
                        page_index = int(page_match.group(1)) - 1
                if isinstance(stored_printed_label, str) and stored_printed_label:
                    printed_page_label = stored_printed_label
            evidence_id = f"evidence-{stable_hash({'source_hash': source.content_hash, 'start': left, 'end': right, 'excerpt': excerpt})[:16]}"
            span = EvidenceSpan(
                evidence_id=evidence_id,
                source_id=source.source_id,
                page_index=page_index,
                printed_page_label=printed_page_label,
                section_heading=heading,
                char_start=left,
                char_end=right,
                excerpt=excerpt,
                context=source_text[max(start, left - 180) : min(end, right + 180)],
                source_hash=source.content_hash,
                extraction_confidence=1.0,
                locator=f"techshort://source/{source.source_id}?start={left}&end={right}",
            )
            if source_text[span.char_start : span.char_end] != span.excerpt:
                raise ValueError("internal evidence locator did not resolve exactly")
            spans.append(span)
            if len(spans) >= maximum:
                break
        if len(spans) >= maximum:
            break
    if not spans:
        raise ValueError("source has no usable text evidence; OCR may be required")
    return EvidenceManifest(
        version_id=f"evidence-{stable_hash(spans)[:16]}",
        evidence=spans,
    )


def _evidence_excerpts(evidence: EvidenceManifest) -> list[dict[str, object]]:
    return [
        {
            "evidence_version_id": evidence.version_id,
            "evidence_id": span.evidence_id,
            "source_id": span.source_id,
            "page_index": span.page_index,
            "printed_page_label": span.printed_page_label,
            "section_heading": span.section_heading,
            "excerpt": span.excerpt,
            "context": span.context,
        }
        for span in evidence.evidence
    ]


def _claims_excerpts(claims: ClaimsManifest, evidence: EvidenceManifest) -> list[dict[str, object]]:
    evidence_by_id = {span.evidence_id: span for span in evidence.evidence}
    rows: list[dict[str, object]] = []
    for claim in claims.claims:
        rows.append(
            {
                "claims_version_id": claims.version_id,
                "claim_id": claim.claim_id,
                "claim": claim.text,
                "relationship": claim.relationship,
                "evidence_label": claim.evidence_label,
                "reasoning": claim.reasoning,
                "scope": claim.scope,
                "limitation": claim.limitation,
                "confidence": claim.confidence,
                "evidence": [
                    {
                        "evidence_id": evidence_id,
                        "excerpt": evidence_by_id[evidence_id].excerpt,
                        "section_heading": evidence_by_id[evidence_id].section_heading,
                        "page_index": evidence_by_id[evidence_id].page_index,
                        "printed_page_label": evidence_by_id[evidence_id].printed_page_label,
                        "locator": evidence_by_id[evidence_id].locator,
                    }
                    for evidence_id in claim.evidence_span_ids
                    if evidence_id in evidence_by_id
                ],
            }
        )
    return rows


def _script_excerpts(script: ScriptManifest) -> list[dict[str, object]]:
    return [
        {
            "script_version_id": script.version_id,
            "segment_id": segment.segment_id,
            "text": segment.text,
            "segment_type": segment.segment_type,
            "claim_ids": segment.claim_ids,
            "approximate_duration": segment.approximate_duration,
        }
        for segment in script.segments
    ]


def _manual_packet_path(store: ProjectStore, stage: ManualTask) -> Path:
    if stage == "angles":
        return store.path("script/angles-manual-prompt.json")
    return store.path(f"{stage}/manual-prompt.json")


def _manual_candidate(
    store: ProjectStore,
    stage: ManualTask,
    result_relative: str | Path,
    model: type[ArtifactT],
    *,
    expected_input_hash: str,
    expected_prompt_hash: str,
) -> ArtifactT:
    packet_path = _manual_packet_path(store, stage)
    if not packet_path.is_file():
        raise ValueError(f"export the {stage} manual prompt packet before importing a result")
    packet = ManualPromptPacket.model_validate_json(packet_path.read_text(encoding="utf-8"))
    if (
        packet.task != stage
        or packet.input_hash != expected_input_hash
        or packet.prompt_hash != expected_prompt_hash
    ):
        raise ValueError(f"the {stage} manual prompt packet is stale; export a new packet")
    result_path = store.path(str(result_relative))
    return ManualProvider.import_result(result_path, model)


def _prepare_manual(
    store: ProjectStore,
    stage: ManualTask,
    excerpts: list[dict[str, object]],
    model: type[BaseModel],
    instruction: str,
    input_hash: str,
) -> ManualPromptPacket:
    return ManualProvider.export_packet(
        _manual_packet_path(store, stage),
        stage,
        excerpts,
        model.model_json_schema(),
        instruction=instruction,
        input_hash=input_hash,
    )


def _numbers_are_supported(claim: Claim, evidence_by_id: dict[str, EvidenceSpan]) -> bool:
    support = [evidence_by_id[item].excerpt for item in claim.evidence_span_ids]
    claim_text = " ".join(
        item
        for item in (claim.text, claim.reasoning, claim.scope, claim.limitation)
        if item is not None
    )
    return not unsupported_assertion_tokens(claim_text, support)


def _normalize_claims(candidate: ClaimsManifest, evidence: EvidenceManifest) -> ClaimsManifest:
    if candidate.evidence_version_id != evidence.version_id:
        raise ValueError("generated claims target a stale or unknown evidence version")
    if not 1 <= len(candidate.claims) <= 12:
        raise ValueError("generated claims must contain between 1 and 12 candidates")
    evidence_by_id = {item.evidence_id: item for item in evidence.evidence}
    seen: set[str] = set()
    for claim in candidate.claims:
        _require_safe_id(claim.claim_id, "claim_id")
        if claim.claim_id in seen:
            raise ValueError(f"duplicate claim_id: {claim.claim_id}")
        seen.add(claim.claim_id)
        if len(claim.evidence_span_ids) != len(set(claim.evidence_span_ids)):
            raise ValueError(f"claim {claim.claim_id} repeats an evidence ID")
        missing = set(claim.evidence_span_ids) - evidence_by_id.keys()
        if missing:
            raise ValueError(
                f"claim {claim.claim_id} references unknown evidence: {', '.join(sorted(missing))}"
            )
        if not _numbers_are_supported(claim, evidence_by_id):
            raise ValueError(
                f"claim {claim.claim_id} contains a number or DOI absent from evidence"
            )
        claim.review_status = ReviewStatus.PENDING
        claim.approval_timestamp = None
        claim.approval_hash = None
        claim.reviewer_edits = None
    candidate.version_id = f"claims-{stable_hash(candidate.claims)[:16]}"
    return ClaimsManifest.model_validate(candidate.model_dump(mode="json"))


_CRITIQUE_WORD = re.compile(r"[a-z][a-z0-9-]{2,}", re.IGNORECASE)
_CRITIQUE_STOPWORDS = {
    "and",
    "are",
    "but",
    "for",
    "from",
    "has",
    "have",
    "into",
    "not",
    "that",
    "the",
    "their",
    "then",
    "this",
    "was",
    "when",
    "with",
}
_UNCERTAINTY_WORDS = re.compile(
    r"\b(?:appears?|approximately|can|could|likely|may|might|suggests?|uncertain)\b",
    re.IGNORECASE,
)
_CAUSAL_WORDS = re.compile(
    r"\b(?:causes?|caused|drives?|leads? to|results? in|therefore)\b", re.IGNORECASE
)


def _claim_words(value: str) -> set[str]:
    return {
        token.casefold()
        for token in _CRITIQUE_WORD.findall(value)
        if token.casefold() not in _CRITIQUE_STOPWORDS
    }


def _deterministic_critique_issues(
    claims: ClaimsManifest, evidence: EvidenceManifest
) -> list[ClaimCritiqueIssue]:
    """Run an independent lexical/support pass; human review remains authoritative."""

    evidence_by_id = {item.evidence_id: item for item in evidence.evidence}
    issues: list[ClaimCritiqueIssue] = []
    for claim in claims.claims:
        cited = [evidence_by_id[item] for item in claim.evidence_span_ids]
        claim_words = _claim_words(claim.text)
        evidence_words = _claim_words(" ".join(item.excerpt for item in cited))
        overlap = len(claim_words & evidence_words) / max(1, len(claim_words))
        if claim.relationship == "direct" and overlap < 0.35:
            issues.append(
                ClaimCritiqueIssue(
                    claim_id=claim.claim_id,
                    category="partial-support",
                    severity="warning",
                    message=(
                        "The direct claim has low lexical overlap with its cited excerpts; "
                        "a reviewer should verify that the paraphrase preserves meaning and scope."
                    ),
                    evidence_ids=claim.evidence_span_ids,
                )
            )
        if claim.relationship != "direct" and not _UNCERTAINTY_WORDS.search(claim.text):
            issues.append(
                ClaimCritiqueIssue(
                    claim_id=claim.claim_id,
                    category="uncertainty",
                    severity="warning",
                    message="The inferred or synthesis claim does not express uncertainty.",
                    evidence_ids=claim.evidence_span_ids,
                )
            )
        if claim.relationship != "direct" and _CAUSAL_WORDS.search(claim.text):
            issues.append(
                ClaimCritiqueIssue(
                    claim_id=claim.claim_id,
                    category="causal-wording",
                    severity="warning",
                    message=(
                        "Causal wording appears in a non-direct claim; verify that the cited "
                        "evidence supports causation rather than association."
                    ),
                    evidence_ids=claim.evidence_span_ids,
                )
            )
    return issues


def _normalize_critique(
    candidate: ClaimCritiqueReport,
    provider: ProviderName,
    claims: ClaimsManifest,
    evidence: EvidenceManifest,
) -> ClaimCritiqueReport:
    if candidate.provider != provider:
        raise ValueError("claim critique returned the wrong provider")
    if candidate.claims_version_id != claims.version_id:
        raise ValueError("claim critique targets a stale or unknown claims version")
    claims_by_id = {claim.claim_id: claim for claim in claims.claims}
    combined = [*_deterministic_critique_issues(claims, evidence), *candidate.issues]
    issues: list[ClaimCritiqueIssue] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in combined:
        claim = claims_by_id.get(issue.claim_id)
        if claim is None:
            raise ValueError(f"claim critique references unknown claim: {issue.claim_id}")
        unknown_evidence = set(issue.evidence_ids) - set(claim.evidence_span_ids)
        if unknown_evidence:
            raise ValueError(
                f"claim critique issue for {issue.claim_id} references uncited evidence: "
                + ", ".join(sorted(unknown_evidence))
            )
        key = (issue.claim_id, issue.category, issue.message)
        if key not in seen:
            issues.append(issue)
            seen.add(key)
    candidate.issues = issues
    candidate.version_id = f"critique-{stable_hash({'claims': claims.version_id, 'provider': provider, 'issues': issues})[:16]}"
    return ClaimCritiqueReport.model_validate(candidate.model_dump(mode="json"))


def _deterministic_claim_critique(
    provider: Literal["fixture", "manual"],
    claims: ClaimsManifest,
    evidence: EvidenceManifest,
) -> ClaimCritiqueReport:
    issues = _deterministic_critique_issues(claims, evidence)
    summary = (
        "Independent deterministic critique checked evidence references, exact locations, "
        "numbers and units, direct-claim lexical support, causal wording, and uncertainty. "
        "It found no candidate issues; semantic conflicts still require human review."
        if not issues
        else (
            f"Independent deterministic critique found {len(issues)} candidate issue(s). "
            "These warnings inform, but do not replace, human claim review."
        )
    )
    return ClaimCritiqueReport(
        version_id="critique-pending",
        claims_version_id=claims.version_id,
        provider=provider,
        summary=summary,
        issues=[],
    )


def _current_approved_claim_ids(
    store: ProjectStore,
    claims: ClaimsManifest,
    evidence: EvidenceManifest,
) -> set[str]:
    return {
        claim.claim_id
        for claim in claims.claims
        if claim.review_status == ReviewStatus.APPROVED
        and claim.approval_hash == claim_review_hash(claim, evidence)
        and has_current_approval(store, "claim", claim.claim_id)
    }


def _normalize_angles(
    candidate: AnglesManifest,
    claims: ClaimsManifest,
    approved_claim_ids: set[str],
) -> AnglesManifest:
    if candidate.claims_version_id != claims.version_id:
        raise ValueError("generated angles target a stale or unknown claims version")
    for angle in candidate.candidates:
        missing = set(angle.central_claim_ids) - approved_claim_ids
        if missing:
            raise ValueError(
                f"angle {angle.angle} references unapproved claims: " + ", ".join(sorted(missing))
            )
    candidate.version_id = derive_angles_version_id(claims.version_id, candidate.candidates)
    return AnglesManifest.model_validate(candidate.model_dump(mode="json"))


def _selection_for(angles: AnglesManifest, angle: AngleKind) -> AngleSelection:
    candidate = next((item for item in angles.candidates if item.angle == angle), None)
    if candidate is None:  # AnglesManifest validation normally makes this unreachable.
        raise ValueError(f"selected angle is absent from the current angle candidates: {angle}")
    candidate_hash = stable_hash(candidate)
    selection_id = derive_angle_selection_id(angles.version_id, angle, candidate_hash)
    return AngleSelection(
        selection_id=selection_id,
        angles_version_id=angles.version_id,
        selected_angle=angle,
        selected_candidate_hash=candidate_hash,
    )


def _normalize_script(
    candidate: ScriptManifest,
    claims: ClaimsManifest,
    angles: AnglesManifest,
    selection: AngleSelection,
    approved_claim_ids: set[str],
) -> ScriptManifest:
    if candidate.claims_version_id != claims.version_id:
        raise ValueError("generated script targets a stale or unknown claims version")
    if candidate.angles_version_id != angles.version_id:
        raise ValueError("generated script targets a stale or unknown angles version")
    if candidate.angle_selection_id != selection.selection_id:
        raise ValueError("generated script did not preserve the current angle selection")
    if candidate.angle != selection.selected_angle:
        raise ValueError("generated script did not preserve the selected angle")
    seen: set[str] = set()
    linked_claim_ids: set[str] = set()
    for segment in candidate.segments:
        _require_safe_id(segment.segment_id, "segment_id")
        if segment.segment_id in seen:
            raise ValueError(f"duplicate segment_id: {segment.segment_id}")
        seen.add(segment.segment_id)
        if len(segment.claim_ids) != len(set(segment.claim_ids)):
            raise ValueError(f"segment {segment.segment_id} repeats a claim ID")
        missing = set(segment.claim_ids) - approved_claim_ids
        if missing:
            raise ValueError(
                f"segment {segment.segment_id} references unapproved claims: "
                + ", ".join(sorted(missing))
            )
        segment.review_status = ReviewStatus.PENDING
        segment.approval_hash = None
        linked_claim_ids.update(segment.claim_ids)
    selected_candidate = next(
        item for item in angles.candidates if item.angle == selection.selected_angle
    )
    missing_central = set(selected_candidate.central_claim_ids) - linked_claim_ids
    if missing_central:
        raise ValueError(
            "generated script omits selected angle central claims: "
            + ", ".join(sorted(missing_central))
        )
    duration = sum(segment.approximate_duration for segment in candidate.segments)
    if not 45 <= duration <= 75:
        raise ValueError("generated script duration must be between 45 and 75 seconds")
    candidate.version_id = derive_script_version_id(
        claims.version_id,
        angles.version_id,
        selection.selection_id,
        selection.selected_angle,
        candidate.segments,
    )
    return ScriptManifest.model_validate(candidate.model_dump(mode="json"))


def _normalize_storyboard(
    candidate: StoryboardManifest,
    script: ScriptManifest,
    allowed_asset_ids: set[str],
) -> StoryboardManifest:
    if candidate.script_version_id != script.version_id:
        raise ValueError("generated storyboard targets a stale or unknown script version")
    segments = {segment.segment_id: segment for segment in script.segments}
    all_claims = {claim_id for segment in script.segments for claim_id in segment.claim_ids}
    scene_ids: set[str] = set()
    covered_segments: set[str] = set()
    elapsed = 0.0
    for expected_order, scene in enumerate(candidate.scenes):
        _require_safe_id(scene.scene_id, "scene_id")
        if scene.scene_id in scene_ids:
            raise ValueError(f"duplicate scene_id: {scene.scene_id}")
        scene_ids.add(scene.scene_id)
        if scene.order != expected_order:
            raise ValueError("storyboard scene order must be contiguous and start at zero")
        if len(scene.script_segment_ids) != len(set(scene.script_segment_ids)):
            raise ValueError(f"scene {scene.scene_id} repeats a script segment ID")
        if len(scene.claim_ids) != len(set(scene.claim_ids)):
            raise ValueError(f"scene {scene.scene_id} repeats a claim ID")
        if len(scene.asset_ids) != len(set(scene.asset_ids)):
            raise ValueError(f"scene {scene.scene_id} repeats an asset ID")
        for asset_id in scene.asset_ids:
            _require_safe_id(asset_id, "asset_id")
        unknown_assets = set(scene.asset_ids) - allowed_asset_ids
        if unknown_assets:
            raise ValueError(
                f"scene {scene.scene_id} references unknown assets: "
                + ", ".join(sorted(unknown_assets))
            )
        missing_segments = set(scene.script_segment_ids) - segments.keys()
        if missing_segments:
            raise ValueError(
                f"scene {scene.scene_id} references unknown segments: "
                + ", ".join(sorted(missing_segments))
            )
        covered_segments.update(scene.script_segment_ids)
        missing_claims = set(scene.claim_ids) - all_claims
        if missing_claims:
            raise ValueError(
                f"scene {scene.scene_id} references unknown claims: "
                + ", ".join(sorted(missing_claims))
            )
        required_claims = {
            claim_id
            for segment_id in scene.script_segment_ids
            for claim_id in segments[segment_id].claim_ids
        }
        if set(scene.claim_ids) != required_claims:
            raise ValueError(
                f"scene {scene.scene_id} must carry exactly the claims from its script segments"
            )
        scene.start_time = elapsed
        elapsed += scene.duration
        scene.review_status = ReviewStatus.PENDING
        linked_segments = [segments[item] for item in scene.script_segment_ids]
        scene.dependency_hash = (
            stable_hash(linked_segments[0])
            if len(linked_segments) == 1
            else stable_hash({"segments": linked_segments})
        )
    if covered_segments != segments.keys():
        missing = sorted(segments.keys() - covered_segments)
        raise ValueError(f"storyboard does not cover script segments: {', '.join(missing)}")
    if not 45 <= elapsed <= 75:
        raise ValueError("generated storyboard duration must be between 45 and 75 seconds")
    candidate.version_id = f"storyboard-{stable_hash(candidate.scenes)[:16]}"
    return StoryboardManifest.model_validate(candidate.model_dump(mode="json"))


def _receipt(
    stage: ManualTask,
    provider: ProviderName,
    prompt_version: str,
    prompt_hash: str,
    input_hash: str,
    artifact_version: str,
) -> GenerationReceipt:
    return GenerationReceipt(
        stage=stage,
        provider=provider,
        prompt_version=prompt_version,
        prompt_hash=prompt_hash,
        input_hash=input_hash,
        artifact_version=artifact_version,
    )


def _save_project_state(
    store: ProjectStore,
    stage: ManualTask,
    versions: dict[str, str],
    receipt: GenerationReceipt,
    *,
    dependency_hashes: dict[str, str] | None = None,
) -> None:
    atomic_write_model(store.path(f"{stage}/generation-receipt.json"), receipt)
    store.invalidate_from(stage, f"{stage} regenerated with {receipt.provider} provider")
    project = store.project()
    setattr(project.approvals, stage, ReviewStatus.PENDING)
    project.active_versions.update(versions)
    if "claims_critique" in versions:
        project.stale_artifacts = [
            item for item in project.stale_artifacts if item != "claims_critique"
        ]
    project.dependency_hashes[f"{stage}_prompt"] = receipt.prompt_hash
    project.dependency_hashes[f"{stage}_input"] = receipt.input_hash
    project.dependency_hashes.update(dependency_hashes or {})
    store.save_project(project)


def generate_claims(
    store: ProjectStore,
    provider: ProviderName = "fixture",
    *,
    source_id: str | None = None,
    manual_result: str | Path | None = None,
    codex_provider: CodexCliProvider | None = None,
) -> GenerationOutcome[ClaimsManifest]:
    source, text = _source(store, source_id)
    if provider == "fixture":
        fixture = FixtureProvider()
        evidence = fixture.evidence(text, source.source_id, source.content_hash)
        candidate = fixture.generate_claims(text, source.source_id, source.content_hash)
        prompt_version = "fixture-v1"
        prompt_hash = stable_hash("fixture rolling-shutter claims v1")
        input_hash = stable_hash({"source_id": source.source_id, "hash": source.content_hash})
    else:
        evidence = build_evidence_candidates(
            text,
            source,
            section_locations=_section_locations(store, source),
        )
        excerpts = _evidence_excerpts(evidence)
        input_hash = stable_hash(excerpts)
        schema = ClaimsManifest.model_json_schema()
        expected_prompt_hash = ManualProvider.template_hash("claims", CLAIMS_INSTRUCTION, schema)
        if provider == "manual":
            packet_path = _manual_packet_path(store, "claims")
            if manual_result is None:
                _prepare_manual(
                    store,
                    "claims",
                    excerpts,
                    ClaimsManifest,
                    CLAIMS_INSTRUCTION,
                    input_hash,
                )
                return GenerationOutcome(provider="manual", prompt_packet=packet_path)
            candidate = _manual_candidate(
                store,
                "claims",
                manual_result,
                ClaimsManifest,
                expected_input_hash=input_hash,
                expected_prompt_hash=expected_prompt_hash,
            )
            prompt_version = ManualProvider.prompt_version
            prompt_hash = expected_prompt_hash
        elif provider == "codex":
            client = codex_provider or CodexCliProvider()
            candidate = client.generate(CLAIMS_INSTRUCTION, excerpts, ClaimsManifest)
            if client.last_run is None:
                raise RuntimeError("Codex provider returned without generation metadata")
            prompt_version = client.last_run.prompt_version
            prompt_hash = client.last_run.prompt_hash
            input_hash = client.last_run.input_hash
        else:
            raise ValueError(f"unknown generation provider: {provider}")

    claims = _normalize_claims(candidate, evidence)
    critique_excerpts = _claims_excerpts(claims, evidence)
    critique_input_hash = stable_hash(critique_excerpts)
    if provider == "codex":
        critique_candidate = client.generate(
            CRITIQUE_INSTRUCTION,
            critique_excerpts,
            ClaimCritiqueReport,
        )
        if client.last_run is None:
            raise RuntimeError("Codex provider returned without critique metadata")
        critique_prompt_version = client.last_run.prompt_version
        critique_prompt_hash = client.last_run.prompt_hash
        critique_input_hash = client.last_run.input_hash
    elif provider in {"fixture", "manual"}:
        critique_candidate = _deterministic_claim_critique(provider, claims, evidence)
        critique_prompt_version = "deterministic-critique-v1"
        critique_prompt_hash = stable_hash(
            {
                "prompt_version": critique_prompt_version,
                "instruction": CRITIQUE_INSTRUCTION,
                "schema": ClaimCritiqueReport.model_json_schema(),
            }
        )
    else:  # pragma: no cover - provider is validated above
        raise ValueError(f"unknown generation provider: {provider}")
    critique = _normalize_critique(critique_candidate, provider, claims, evidence)
    evidence_path = store.path("evidence/evidence.json")
    claims_path = store.path("claims/claims.json")
    critique_path = store.path("claims/critique.json")
    if evidence_path.exists():
        previous_evidence = load_model(evidence_path, EvidenceManifest)
        _archive(store, "evidence/evidence.json", previous_evidence.version_id)
    if claims_path.exists():
        previous_claims = load_model(claims_path, ClaimsManifest)
        _archive(store, "claims/claims.json", previous_claims.version_id)
    if critique_path.exists():
        previous_critique = load_model(critique_path, ClaimCritiqueReport)
        _archive(store, "claims/critique.json", previous_critique.version_id)
    atomic_write_model(evidence_path, evidence)
    atomic_write_model(claims_path, claims)
    atomic_write_model(critique_path, critique)
    receipt = _receipt(
        "claims",
        provider,
        prompt_version,
        prompt_hash,
        input_hash,
        claims.version_id,
    )
    critique_receipt = _receipt(
        "claims",
        provider,
        critique_prompt_version,
        critique_prompt_hash,
        critique_input_hash,
        critique.version_id,
    )
    atomic_write_model(store.path("claims/critique-receipt.json"), critique_receipt)
    _save_project_state(
        store,
        "claims",
        {
            "evidence": evidence.version_id,
            "claims": claims.version_id,
            "claims_critique": critique.version_id,
        },
        receipt,
        dependency_hashes={
            "claims_critique_prompt": critique_prompt_hash,
            "claims_critique_input": critique_input_hash,
        },
    )
    return GenerationOutcome(provider=provider, artifact=claims)


def generate_angles(
    store: ProjectStore,
    provider: ProviderName = "fixture",
    *,
    manual_result: str | Path | None = None,
    codex_provider: CodexCliProvider | None = None,
) -> GenerationOutcome[AnglesManifest]:
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    project = store.project()
    if project.active_versions.get("claims") != claims.version_id:
        raise ValueError("claims manifest is not the active claims version")
    evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
    approved_claim_ids = _current_approved_claim_ids(store, claims, evidence)
    if not claims.claims or len(approved_claim_ids) != len(claims.claims):
        raise ValueError("all claims must have current approvals before angle generation")
    excerpts = _claims_excerpts(claims, evidence)
    input_hash = stable_hash(excerpts)

    if provider == "fixture":
        candidate = FixtureProvider().generate_angles(claims)
        prompt_version = "fixture-v1"
        prompt_hash = stable_hash("fixture rolling-shutter angles v1")
    elif provider == "manual":
        schema = AnglesManifest.model_json_schema()
        expected_prompt_hash = ManualProvider.template_hash("angles", ANGLES_INSTRUCTION, schema)
        packet_path = _manual_packet_path(store, "angles")
        if manual_result is None:
            _prepare_manual(
                store,
                "angles",
                excerpts,
                AnglesManifest,
                ANGLES_INSTRUCTION,
                input_hash,
            )
            return GenerationOutcome(provider="manual", prompt_packet=packet_path)
        candidate = _manual_candidate(
            store,
            "angles",
            manual_result,
            AnglesManifest,
            expected_input_hash=input_hash,
            expected_prompt_hash=expected_prompt_hash,
        )
        prompt_version = ManualProvider.prompt_version
        prompt_hash = expected_prompt_hash
    elif provider == "codex":
        client = codex_provider or CodexCliProvider()
        candidate = client.generate(ANGLES_INSTRUCTION, excerpts, AnglesManifest)
        if client.last_run is None:
            raise RuntimeError("Codex provider returned without generation metadata")
        prompt_version = client.last_run.prompt_version
        prompt_hash = client.last_run.prompt_hash
        input_hash = client.last_run.input_hash
    else:
        raise ValueError(f"unknown generation provider: {provider}")

    angles = _normalize_angles(candidate, claims, approved_claim_ids)
    angles_path = store.path("script/angles.json")
    if angles_path.exists():
        previous = load_model(angles_path, AnglesManifest)
        _archive(store, "script/angles.json", previous.version_id)
    atomic_write_model(angles_path, angles)
    receipt = _receipt(
        "angles",
        provider,
        prompt_version,
        prompt_hash,
        input_hash,
        angles.version_id,
    )
    atomic_write_model(store.path("script/angles-generation-receipt.json"), receipt)
    store.invalidate_from("script", f"angles regenerated with {provider} provider")
    project = store.project()
    project.active_versions["angles"] = angles.version_id
    project.active_versions.pop("angle_selection", None)
    project.dependency_hashes["angles_prompt"] = receipt.prompt_hash
    project.dependency_hashes["angles_input"] = receipt.input_hash
    project.dependency_hashes.pop("angle_selection", None)
    project.stale_artifacts = [item for item in project.stale_artifacts if item != "angles"]
    if "angle_selection" not in project.stale_artifacts:
        project.stale_artifacts.append("angle_selection")
    store.save_project(project)
    return GenerationOutcome(provider=provider, artifact=angles)


def select_angle(store: ProjectStore, angle: AngleKind) -> AngleSelection:
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
    angles = load_model(store.path("script/angles.json"), AnglesManifest)
    project = store.project()
    approved_claim_ids = _current_approved_claim_ids(store, claims, evidence)
    if not claims.claims or len(approved_claim_ids) != len(claims.claims):
        raise ValueError("all claims must have current approvals before angle selection")
    if angles.claims_version_id != claims.version_id:
        raise ValueError("angle candidates were generated from a different claims version")
    if (
        angles.version_id != derive_angles_version_id(claims.version_id, angles.candidates)
        or project.active_versions.get("angles") != angles.version_id
    ):
        raise ValueError("angle candidates are stale; generate a current angle artifact first")
    for angle_candidate in angles.candidates:
        missing = set(angle_candidate.central_claim_ids) - approved_claim_ids
        if missing:
            raise ValueError(
                f"angle {angle_candidate.angle} references unapproved claims: "
                + ", ".join(sorted(missing))
            )
    selection = _selection_for(angles, angle)
    selection_path = store.path("script/angle-selection.json")
    if selection_path.exists():
        previous = load_model(selection_path, AngleSelection)
        if (
            previous.selection_id == selection.selection_id
            and project.active_versions.get("angle_selection") == previous.selection_id
        ):
            return previous
        _archive(store, "script/angle-selection.json", previous.selection_id)
    atomic_write_model(selection_path, selection)
    store.invalidate_from("script", f"angle selected: {angle}")
    project = store.project()
    project.active_versions["angle_selection"] = selection.selection_id
    project.dependency_hashes["angle_selection"] = stable_hash(
        {
            "selection_id": selection.selection_id,
            "angles_version_id": selection.angles_version_id,
            "selected_angle": selection.selected_angle,
            "selected_candidate_hash": selection.selected_candidate_hash,
        }
    )
    project.stale_artifacts = [
        item for item in project.stale_artifacts if item != "angle_selection"
    ]
    store.save_project(project)
    return selection


def generate_script(
    store: ProjectStore,
    provider: ProviderName = "fixture",
    *,
    angle: AngleKind | None = None,
    manual_result: str | Path | None = None,
    codex_provider: CodexCliProvider | None = None,
) -> GenerationOutcome[ScriptManifest]:
    claims = load_model(store.path("claims/claims.json"), ClaimsManifest)
    evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
    approved_claim_ids = _current_approved_claim_ids(store, claims, evidence)
    if not claims.claims or len(approved_claim_ids) != len(claims.claims):
        raise ValueError("all claims must have current approvals before script generation")
    angles_path = store.path("script/angles.json")
    project = store.project()
    if not angles_path.is_file():
        raise ValueError(
            "current angle candidates are required; run `techshort script angles "
            f"{store.slug} --provider {provider}` first"
        )
    angles = load_model(angles_path, AnglesManifest)
    expected_angles_version = derive_angles_version_id(claims.version_id, angles.candidates)
    if (
        angles.claims_version_id != claims.version_id
        or angles.version_id != expected_angles_version
        or project.active_versions.get("angles") != angles.version_id
    ):
        raise ValueError("angle candidates are stale or have an invalid content version")
    for angle_candidate in angles.candidates:
        missing = set(angle_candidate.central_claim_ids) - approved_claim_ids
        if missing:
            raise ValueError(
                f"angle {angle_candidate.angle} references unapproved claims: "
                + ", ".join(sorted(missing))
            )
    selection_path = store.path("script/angle-selection.json")
    if not selection_path.is_file():
        raise ValueError(
            "select one current angle with `techshort script select-angle "
            f"{store.slug} <angle>` before script generation"
        )
    selection = load_model(selection_path, AngleSelection)
    if (
        selection.angles_version_id != angles.version_id
        or project.active_versions.get("angle_selection") != selection.selection_id
    ):
        raise ValueError("angle selection is stale; explicitly select a current angle")
    selected_candidate = next(
        (item for item in angles.candidates if item.angle == selection.selected_angle),
        None,
    )
    if (
        selected_candidate is None
        or stable_hash(selected_candidate) != selection.selected_candidate_hash
    ):
        raise ValueError("angle selection no longer matches its selected candidate")
    if angle is not None and angle != selection.selected_angle:
        raise ValueError(
            f"requested angle {angle} does not match explicit selection {selection.selected_angle}"
        )
    selected_angle = selection.selected_angle
    excerpts = _claims_excerpts(claims, evidence)
    excerpts.append(
        {
            "claims_version_id": claims.version_id,
            "angles_version_id": angles.version_id,
            "angle_selection_id": selection.selection_id,
            "selected_angle": selection.selected_angle,
            "selected_candidate": selected_candidate.model_dump(mode="json"),
        }
    )
    input_hash = stable_hash(excerpts)

    if provider == "fixture":
        candidate = FixtureProvider().generate_script(
            claims,
            selected_angle,
            angles_version_id=angles.version_id,
            angle_selection_id=selection.selection_id,
        )
        prompt_version = "fixture-v1"
        prompt_hash = stable_hash("fixture rolling-shutter script v1")
    elif provider == "manual":
        schema = ScriptManifest.model_json_schema()
        expected_prompt_hash = ManualProvider.template_hash("script", SCRIPT_INSTRUCTION, schema)
        packet_path = _manual_packet_path(store, "script")
        if manual_result is None:
            _prepare_manual(
                store,
                "script",
                excerpts,
                ScriptManifest,
                SCRIPT_INSTRUCTION,
                input_hash,
            )
            return GenerationOutcome(provider="manual", prompt_packet=packet_path)
        candidate = _manual_candidate(
            store,
            "script",
            manual_result,
            ScriptManifest,
            expected_input_hash=input_hash,
            expected_prompt_hash=expected_prompt_hash,
        )
        prompt_version = ManualProvider.prompt_version
        prompt_hash = expected_prompt_hash
    elif provider == "codex":
        client = codex_provider or CodexCliProvider()
        candidate = client.generate(SCRIPT_INSTRUCTION, excerpts, ScriptManifest)
        if client.last_run is None:
            raise RuntimeError("Codex provider returned without generation metadata")
        prompt_version = client.last_run.prompt_version
        prompt_hash = client.last_run.prompt_hash
        input_hash = client.last_run.input_hash
    else:
        raise ValueError(f"unknown generation provider: {provider}")

    script = _normalize_script(
        candidate,
        claims,
        angles,
        selection,
        approved_claim_ids,
    )
    script_path = store.path("script/script.json")
    if script_path.exists():
        previous = load_model(script_path, ScriptManifest)
        _archive(store, "script/script.json", previous.version_id)
    atomic_write_model(script_path, script)
    receipt = _receipt(
        "script",
        provider,
        prompt_version,
        prompt_hash,
        input_hash,
        script.version_id,
    )
    _save_project_state(
        store,
        "script",
        {
            "angles": angles.version_id,
            "angle_selection": selection.selection_id,
            "script": script.version_id,
        },
        receipt,
        dependency_hashes={
            "script_angles": angles.version_id,
            "script_angle_selection": selection.selection_id,
        },
    )
    return GenerationOutcome(provider=provider, artifact=script)


def generate_storyboard(
    store: ProjectStore,
    provider: ProviderName = "fixture",
    *,
    manual_result: str | Path | None = None,
    codex_provider: CodexCliProvider | None = None,
) -> GenerationOutcome[StoryboardManifest]:
    script = load_model(store.path("script/script.json"), ScriptManifest)
    project = store.project()
    segments_are_current = bool(script.segments) and all(
        segment.review_status == ReviewStatus.APPROVED
        and segment.approval_hash == script_segment_review_hash(segment)
        and has_current_approval(store, "script-segment", segment.segment_id)
        for segment in script.segments
    )
    if not segments_are_current:
        raise ValueError(
            "all script segments must have current approvals before storyboard generation"
        )
    if project.active_versions.get("script") != script.version_id:
        raise ValueError("script manifest is not the active script version")
    excerpts = _script_excerpts(script)
    input_hash = stable_hash(excerpts)

    if provider == "fixture":
        candidate = FixtureProvider().generate_storyboard(script)
        prompt_version = "fixture-v1"
        prompt_hash = stable_hash("fixture rolling-shutter storyboard v1")
    elif provider == "manual":
        schema = StoryboardManifest.model_json_schema()
        expected_prompt_hash = ManualProvider.template_hash(
            "storyboard", STORYBOARD_INSTRUCTION, schema
        )
        packet_path = _manual_packet_path(store, "storyboard")
        if manual_result is None:
            _prepare_manual(
                store,
                "storyboard",
                excerpts,
                StoryboardManifest,
                STORYBOARD_INSTRUCTION,
                input_hash,
            )
            return GenerationOutcome(provider="manual", prompt_packet=packet_path)
        candidate = _manual_candidate(
            store,
            "storyboard",
            manual_result,
            StoryboardManifest,
            expected_input_hash=input_hash,
            expected_prompt_hash=expected_prompt_hash,
        )
        prompt_version = ManualProvider.prompt_version
        prompt_hash = expected_prompt_hash
    elif provider == "codex":
        client = codex_provider or CodexCliProvider()
        candidate = client.generate(STORYBOARD_INSTRUCTION, excerpts, StoryboardManifest)
        if client.last_run is None:
            raise RuntimeError("Codex provider returned without generation metadata")
        prompt_version = client.last_run.prompt_version
        prompt_hash = client.last_run.prompt_hash
        input_hash = client.last_run.input_hash
    else:
        raise ValueError(f"unknown generation provider: {provider}")

    asset_path = store.path("assets/asset-manifest.json")
    allowed_asset_ids = (
        {asset.asset_id for asset in load_model(asset_path, AssetManifest).assets}
        if asset_path.exists()
        else set()
    )
    storyboard = _normalize_storyboard(candidate, script, allowed_asset_ids)
    storyboard_path = store.path("storyboard/storyboard.json")
    if storyboard_path.exists():
        previous = load_model(storyboard_path, StoryboardManifest)
        _archive(store, "storyboard/storyboard.json", previous.version_id)
    atomic_write_model(storyboard_path, storyboard)
    ensure_builtin_assets(store)
    receipt = _receipt(
        "storyboard",
        provider,
        prompt_version,
        prompt_hash,
        input_hash,
        storyboard.version_id,
    )
    _save_project_state(store, "storyboard", {"storyboard": storyboard.version_id}, receipt)
    return GenerationOutcome(provider=provider, artifact=storyboard)


def fixture_claims(store: ProjectStore) -> ClaimsManifest:
    return generate_claims(store, "fixture").require_artifact()


def fixture_script(store: ProjectStore, angle: str = "everyday-mechanism") -> ScriptManifest:
    if angle not in {"surprising-result", "everyday-mechanism", "engineering-tradeoff"}:
        raise ValueError(
            "angle must be surprising-result, everyday-mechanism, or engineering-tradeoff"
        )
    selected = cast(
        Literal["surprising-result", "everyday-mechanism", "engineering-tradeoff"], angle
    )
    return generate_script(store, "fixture", angle=selected).require_artifact()


def fixture_storyboard(store: ProjectStore) -> StoryboardManifest:
    return generate_storyboard(store, "fixture").require_artifact()
