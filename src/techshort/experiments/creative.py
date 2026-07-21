from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from techshort.domain.hashing import sha256_file, stable_hash
from techshort.domain.models import (
    AssetManifest,
    ClaimsManifest,
    CoverManifest,
    CoverSelection,
    EvidenceManifest,
    QAReport,
    RenderManifest,
    ReviewStatus,
    ScriptManifest,
    SourceIndex,
    StoryboardManifest,
    StrictModel,
    now_utc,
)
from techshort.domain.storage import (
    ProjectStore,
    atomic_copy_file,
    atomic_write_model,
    load_model,
)
from techshort.experiments.models import (
    ExperimentManifest,
    ExperimentVariable,
    MetricName,
    OrganicPlatform,
    RecommendationAction,
    VariantRole,
    derive_experiment_id,
)
from techshort.experiments.service import build_variant, initialize_experiment
from techshort.experiments.storage import ExperimentStore
from techshort.generation.design import select_cover, selected_cover_payload
from techshort.rendering.service import renderer_payload
from techshort.review import current_artifact_hashes, final_review_hash, has_current_approval

_SAFE_CANDIDATE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


@dataclass(frozen=True)
class ExportExperimentContract:
    media_path: str
    media_hash: str
    captions_srt_path: str
    captions_vtt_path: str
    locked_factual_hash: str
    evidence_hash: str
    claims_hash: str
    limitation_hash: str
    rights_hash: str


class RecommendationApplication(StrictModel):
    application_id: str = Field(pattern=r"^application-[0-9a-f]{16}$")
    experiment_id: str = Field(pattern=r"^exp-[0-9a-f]{16}$")
    recommendation_id: str = Field(pattern=r"^rec-[0-9a-f]{16}$")
    recommendation_approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    action: RecommendationAction
    variant_id: str = Field(pattern=r"^var-[0-9a-f]{16}$")
    variable: Literal[ExperimentVariable.COVER] = ExperimentVariable.COVER
    previous_candidate_id: str
    applied_candidate_id: str
    previous_selection_id: str
    resulting_selection_id: str
    changed_production_default: bool
    invalidated_gates: list[
        Literal["storyboard", "rights", "final"]
    ] = Field(default_factory=list, max_length=3)
    reviewer_identifier: str = Field(min_length=1, max_length=80)
    applied_at: datetime
    application_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "previous_candidate_id",
        "applied_candidate_id",
        "previous_selection_id",
        "resulting_selection_id",
    )
    @classmethod
    def identifiers_are_inert(cls, value: str) -> str:
        if not value or len(value) > 160 or "\x00" in value:
            raise ValueError("application identifiers must be bounded inert text")
        return value

    @field_validator("applied_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("application timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def identity_matches_content(self) -> RecommendationApplication:
        if self.changed_production_default:
            if self.previous_candidate_id == self.applied_candidate_id:
                raise ValueError("a changed default must select a different cover")
            if self.invalidated_gates != ["storyboard", "rights", "final"]:
                raise ValueError("a changed cover must invalidate all downstream gates")
        elif self.previous_candidate_id != self.applied_candidate_id:
            raise ValueError("an unchanged default cannot identify a different cover")
        expected_hash = stable_hash(
            self.model_dump(mode="json", exclude={"application_id", "application_hash"})
        )
        if self.application_hash != expected_hash:
            raise ValueError("recommendation application hash does not match its content")
        if self.application_id != f"application-{expected_hash[:16]}":
            raise ValueError("recommendation application ID does not match its content")
        return self


class RecommendationApplicationLog(StrictModel):
    experiment_id: str = Field(pattern=r"^exp-[0-9a-f]{16}$")
    applications: list[RecommendationApplication] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def applications_are_unique_and_scoped(self) -> RecommendationApplicationLog:
        if any(item.experiment_id != self.experiment_id for item in self.applications):
            raise ValueError("recommendation application belongs to another experiment")
        ids = [item.application_id for item in self.applications]
        if len(ids) != len(set(ids)):
            raise ValueError("recommendation application IDs must be unique")
        recommendation_ids = [item.recommendation_id for item in self.applications]
        if len(recommendation_ids) != len(set(recommendation_ids)):
            raise ValueError("a recommendation can be applied only once")
        return self


def create_cover_experiment(
    store: ProjectStore,
    *,
    name: str,
    hypothesis: str,
    platform: OrganicPlatform,
    candidate_ids: list[str] | None = None,
    primary_metric: MetricName = MetricName.COMPLETION_RATE,
    minimum_views_per_variant: int = 500,
) -> ExperimentManifest:
    """Render reviewed cover candidates around one identical approved export."""

    contract = _validated_export_contract(store)
    covers, selection = _current_cover_context(store)
    requested = candidate_ids or [item.candidate_id for item in covers.candidates]
    if len(requested) < 2 or len(requested) > len(covers.candidates):
        raise ValueError("cover experiments require two or three reviewed candidates")
    if len(requested) != len(set(requested)):
        raise ValueError("cover experiment candidate IDs must be unique")
    if selection.selected_candidate_id not in requested:
        raise ValueError("cover experiment must include the current selected cover as control")
    candidates = {item.candidate_id: item for item in covers.candidates}
    for candidate_id in requested:
        if not _SAFE_CANDIDATE_ID.fullmatch(candidate_id) or candidate_id not in candidates:
            raise ValueError(f"unknown or unsafe cover candidate: {candidate_id}")

    experiment_id = derive_experiment_id(
        store.project().project_id,
        name,
        ExperimentVariable.COVER,
        contract.locked_factual_hash,
    )
    experiment_store = ExperimentStore(store, experiment_id)
    if experiment_store.manifest_path.is_file():
        existing = experiment_store.manifest()
        _validate_existing_cover_experiment(
            existing,
            store=store,
            contract=contract,
            platform=platform,
            name=name,
            hypothesis=hypothesis,
            requested=requested,
            primary_metric=primary_metric,
            minimum_views_per_variant=minimum_views_per_variant,
        )
        return existing

    cover_directory = store.path(f"experiments/{experiment_id}/variants")
    cover_directory.mkdir(parents=True, exist_ok=True)
    rendered: dict[str, Path] = {}
    with tempfile.TemporaryDirectory(prefix=".cover-variants-", dir=cover_directory) as stage_name:
        stage = Path(stage_name)
        for candidate_id in requested:
            output = stage / f"{candidate_id}.png"
            _render_cover_candidate(store, candidate_id, output)
            if not output.is_file() or output.stat().st_size <= 8:
                raise RuntimeError(f"cover renderer produced no usable image for {candidate_id}")
            with output.open("rb") as handle:
                if handle.read(8) != b"\x89PNG\r\n\x1a\n":
                    raise RuntimeError(f"cover renderer produced a non-PNG file for {candidate_id}")
            destination = cover_directory / f"{candidate_id}.png"
            if destination.exists():
                if sha256_file(destination) != sha256_file(output):
                    raise FileExistsError(
                        f"cover variant already exists with different bytes: {candidate_id}"
                    )
            else:
                atomic_copy_file(output, destination)
            rendered[candidate_id] = destination

    variants = []
    for candidate_id in requested:
        candidate = candidates[candidate_id]
        destination = rendered[candidate_id]
        variants.append(
            build_variant(
                label=candidate.headline,
                role=(
                    VariantRole.CONTROL
                    if candidate_id == selection.selected_candidate_id
                    else VariantRole.TREATMENT
                ),
                variable=ExperimentVariable.COVER,
                variable_value=candidate_id,
                media_path=contract.media_path,
                media_hash=contract.media_hash,
                cover_path=destination.relative_to(store.root).as_posix(),
                cover_hash=sha256_file(destination),
                locked_factual_hash=contract.locked_factual_hash,
                evidence_hash=contract.evidence_hash,
                claims_hash=contract.claims_hash,
                limitation_hash=contract.limitation_hash,
                rights_hash=contract.rights_hash,
            )
        )
    return initialize_experiment(
        store,
        name=name,
        hypothesis=hypothesis,
        platform=platform,
        variable=ExperimentVariable.COVER,
        variants=variants,
        primary_metric=primary_metric,
        minimum_views_per_variant=minimum_views_per_variant,
    )


def apply_approved_cover_recommendation(
    experiment_store: ExperimentStore,
    recommendation_id: str,
    reviewer_identifier: str,
) -> RecommendationApplication:
    """Apply one approved cover result through the normal invalidation boundary."""

    if not reviewer_identifier.strip():
        raise ValueError("application reviewer identifier cannot be empty")
    log = _load_application_log(experiment_store)
    existing = next(
        (item for item in log.applications if item.recommendation_id == recommendation_id), None
    )
    if existing is not None:
        _, selection = _current_cover_context(experiment_store.project_store)
        if selection.selection_id != existing.resulting_selection_id:
            raise ValueError("the applied cover recommendation is historical; current cover changed")
        return existing

    manifest = experiment_store.manifest()
    if manifest.variable is not ExperimentVariable.COVER:
        raise ValueError("only cover recommendations have a safe production application path")
    if manifest.review_status is not ReviewStatus.APPROVED:
        raise ValueError("experiment approval is missing or stale")
    recommendation = next(
        (
            item
            for item in experiment_store.recommendations().recommendations
            if item.recommendation_id == recommendation_id
        ),
        None,
    )
    if recommendation is None:
        raise ValueError("recommendation does not exist")
    if recommendation.review_status is not ReviewStatus.APPROVED:
        raise ValueError("recommendation requires explicit human approval before application")
    if recommendation.approval_hash is None:
        raise ValueError("approved recommendation is missing its approval hash")
    if recommendation.action is RecommendationAction.COLLECT_MORE_DATA:
        raise ValueError("an inconclusive recommendation cannot change production")
    variant = next(
        (item for item in manifest.variants if item.variant_id == recommendation.proposed_variant_id),
        None,
    )
    if variant is None or variant.review_status is not ReviewStatus.APPROVED:
        raise ValueError("recommendation does not identify a current approved variant")
    if not _SAFE_CANDIDATE_ID.fullmatch(variant.variable_value):
        raise ValueError("recommended cover candidate ID is unsafe")
    contract = _validated_export_contract(experiment_store.project_store)
    _validate_variant_contract(variant, contract)
    recommended_cover = experiment_store.project_store.path(variant.cover_path or "")
    if (
        not recommended_cover.is_file()
        or variant.cover_hash is None
        or sha256_file(recommended_cover) != variant.cover_hash
    ):
        raise ValueError("recommended cover artifact is missing")

    covers, previous = _current_cover_context(experiment_store.project_store)
    if variant.variable_value not in {item.candidate_id for item in covers.candidates}:
        raise ValueError("recommended cover candidate is no longer available")
    changed = previous.selected_candidate_id != variant.variable_value
    resulting = (
        select_cover(experiment_store.project_store, variant.variable_value)
        if changed
        else previous
    )
    applied_at = now_utc()
    payload = {
        "schema_version": "1.0.0",
        "experiment_id": manifest.experiment_id,
        "recommendation_id": recommendation.recommendation_id,
        "recommendation_approval_hash": recommendation.approval_hash,
        "action": recommendation.action,
        "variant_id": variant.variant_id,
        "variable": ExperimentVariable.COVER,
        "previous_candidate_id": previous.selected_candidate_id,
        "applied_candidate_id": variant.variable_value,
        "previous_selection_id": previous.selection_id,
        "resulting_selection_id": resulting.selection_id,
        "changed_production_default": changed,
        "invalidated_gates": ["storyboard", "rights", "final"] if changed else [],
        "reviewer_identifier": reviewer_identifier.strip(),
        "applied_at": applied_at.isoformat().replace("+00:00", "Z"),
    }
    application_hash = stable_hash(payload)
    receipt = RecommendationApplication.model_validate(
        {
            **payload,
            "application_id": f"application-{application_hash[:16]}",
            "application_hash": application_hash,
        }
    )
    log.applications.append(receipt)
    atomic_write_model(_application_log_path(experiment_store), log)
    return receipt


def _validated_export_contract(store: ProjectStore) -> ExportExperimentContract:
    project = store.project()
    for gate in ("claims", "script", "storyboard", "rights", "final"):
        if getattr(project.approvals, gate) is not ReviewStatus.APPROVED:
            raise ValueError(f"cover experiment requires the approved {gate} gate")
    if not has_current_approval(store, "final", project.project_id):
        raise ValueError("cover experiment requires a current final approval")
    if project.dependency_hashes.get("final_approval") != final_review_hash(store):
        raise ValueError("cover experiment final approval is stale")

    paths = {
        "media": store.path(f"export/{store.slug}.mp4"),
        "srt": store.path(f"export/{store.slug}.srt"),
        "vtt": store.path(f"export/{store.slug}.vtt"),
        "cover": store.path("export/cover.png"),
        "rights": store.path("export/asset-rights.json"),
        "qa": store.path("export/qa-report.json"),
        "render_manifest": store.path("export/render-manifest.json"),
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise ValueError(f"cover experiment requires a complete export: missing {missing[0]}")
    current_pairs = (
        (paths["media"], store.path("renders/final/final.mp4")),
        (paths["srt"], store.path("captions/captions.srt")),
        (paths["vtt"], store.path("captions/captions.vtt")),
        (paths["cover"], store.path("renders/final/cover.png")),
        (paths["rights"], store.path("assets/asset-manifest.json")),
        (paths["render_manifest"], store.path("renders/final/render-manifest.json")),
    )
    for exported, current in current_pairs:
        if not current.is_file() or sha256_file(exported) != sha256_file(current):
            raise ValueError(f"exported artifact is missing or stale: {exported.name}")

    report = load_model(paths["qa"], QAReport)
    if not report.passed or report.export_blockers:
        raise ValueError("cover experiment requires a passing final QA report")
    final_video = store.path("renders/final/final.mp4")
    if report.media_hash != sha256_file(final_video):
        raise ValueError("exported QA report does not match the final video")
    if report.artifact_hashes != current_artifact_hashes(store):
        raise ValueError("exported QA report does not match current reviewed artifacts")
    render_manifest = load_model(paths["render_manifest"], RenderManifest)
    final_relative = final_video.relative_to(store.root).as_posix()
    if render_manifest.watermarked:
        raise ValueError("cover experiments cannot use a watermarked final render")
    if render_manifest.output_hashes.get(final_relative) != sha256_file(paths["media"]):
        raise ValueError("exported render manifest does not bind the experiment video")

    source_index = load_model(store.path("sources/source-index.json"), SourceIndex)
    load_model(store.path("evidence/evidence.json"), EvidenceManifest)
    load_model(store.path("claims/claims.json"), ClaimsManifest)
    script = load_model(store.path("script/script.json"), ScriptManifest)
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    load_model(store.path("assets/asset-manifest.json"), AssetManifest)
    limitation_segments = [
        {
            "segment_id": item.segment_id,
            "text": item.text,
            "claim_ids": item.claim_ids,
        }
        for item in script.segments
        if item.segment_type == "limitation"
    ]
    if not limitation_segments:
        raise ValueError("cover experiment requires the approved meaningful limitation")
    evidence_hash = sha256_file(store.path("evidence/evidence.json"))
    claims_hash = sha256_file(store.path("claims/claims.json"))
    rights_hash = sha256_file(store.path("assets/asset-manifest.json"))
    media_hash = sha256_file(paths["media"])
    return ExportExperimentContract(
        media_path=paths["media"].relative_to(store.root).as_posix(),
        media_hash=media_hash,
        captions_srt_path=paths["srt"].relative_to(store.root).as_posix(),
        captions_vtt_path=paths["vtt"].relative_to(store.root).as_posix(),
        locked_factual_hash=stable_hash(
            {
                "sources": source_index,
                "evidence": evidence_hash,
                "claims": claims_hash,
                "script": script,
                "storyboard": storyboard,
                "media": media_hash,
            }
        ),
        evidence_hash=evidence_hash,
        claims_hash=claims_hash,
        limitation_hash=stable_hash(limitation_segments),
        rights_hash=rights_hash,
    )


def _current_cover_context(store: ProjectStore) -> tuple[CoverManifest, CoverSelection]:
    selected_cover_payload(store)
    covers = load_model(store.path("storyboard/covers.json"), CoverManifest)
    selection = load_model(store.path("storyboard/cover-selection.json"), CoverSelection)
    return covers, selection


def _render_cover_candidate(store: ProjectStore, candidate_id: str, output: Path) -> None:
    if not _SAFE_CANDIDATE_ID.fullmatch(candidate_id):
        raise ValueError("cover candidate ID is unsafe")
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not shutil.which("node") or not npm:
        raise ValueError("Node.js and npm are required to render cover variants")
    repository = Path(__file__).resolve().parents[3]
    if not (repository / "package.json").is_file():
        raise ValueError("cover renderer package is missing")
    payload = renderer_payload(store, watermarked=False, preview=False)
    cover_payload = payload.get("cover")
    if not isinstance(cover_payload, dict):
        raise ValueError("renderer payload has no reviewed cover candidates")
    known = cover_payload.get("candidates")
    if not isinstance(known, list) or candidate_id not in {
        item.get("candidate_id") for item in known if isinstance(item, dict)
    }:
        raise ValueError("cover candidate is missing from the renderer payload")
    cover_payload["selected_candidate_id"] = candidate_id
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cover-props-", dir=output.parent) as temp_name:
        props = Path(temp_name) / "project-data.json"
        props.write_text(json.dumps(payload, indent=2), encoding="utf-8", newline="\n")
        result = subprocess.run(
            [
                npm,
                "run",
                "render:cover",
                "--",
                "--output",
                str(output.resolve()),
                "--props",
                str(props.resolve()),
                "--scale",
                "1",
            ],
            cwd=repository,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
    if result.returncode:
        details = (result.stderr + "\n" + result.stdout)[-3000:]
        raise RuntimeError(f"cover variant renderer failed ({result.returncode}): {details}")


def _validate_existing_cover_experiment(
    manifest: ExperimentManifest,
    *,
    store: ProjectStore,
    contract: ExportExperimentContract,
    platform: OrganicPlatform,
    name: str,
    hypothesis: str,
    requested: list[str],
    primary_metric: MetricName,
    minimum_views_per_variant: int,
) -> None:
    actual_values = [item.variable_value for item in manifest.variants]
    if (
        manifest.name != name
        or manifest.hypothesis != hypothesis
        or manifest.platform is not platform
        or manifest.variable is not ExperimentVariable.COVER
        or manifest.primary_metric is not primary_metric
        or manifest.minimum_views_per_variant != minimum_views_per_variant
        or set(actual_values) != set(requested)
    ):
        raise FileExistsError("existing cover experiment does not match the requested contract")
    for variant in manifest.variants:
        _validate_variant_contract(variant, contract)
        media = store.path(variant.media_path)
        cover = store.path(variant.cover_path or "")
        if not media.is_file() or sha256_file(media) != variant.media_hash:
            raise ValueError("existing cover experiment media is stale")
        if (
            variant.cover_hash is None
            or not cover.is_file()
            or sha256_file(cover) != variant.cover_hash
        ):
            raise ValueError("existing cover experiment artifact is stale")


def _validate_variant_contract(variant: object, contract: ExportExperimentContract) -> None:
    required = {
        "media_path": contract.media_path,
        "media_hash": contract.media_hash,
        "locked_factual_hash": contract.locked_factual_hash,
        "evidence_hash": contract.evidence_hash,
        "claims_hash": contract.claims_hash,
        "limitation_hash": contract.limitation_hash,
        "rights_hash": contract.rights_hash,
    }
    for field_name, expected in required.items():
        if getattr(variant, field_name, None) != expected:
            raise ValueError(f"experiment variant has stale {field_name.replace('_', ' ')}")


def _application_log_path(experiment_store: ExperimentStore) -> Path:
    return experiment_store.root / "applications.json"


def _load_application_log(experiment_store: ExperimentStore) -> RecommendationApplicationLog:
    path = _application_log_path(experiment_store)
    if not path.is_file():
        return RecommendationApplicationLog(experiment_id=experiment_store.experiment_id)
    return load_model(path, RecommendationApplicationLog)


__all__ = [
    "ExportExperimentContract",
    "RecommendationApplication",
    "RecommendationApplicationLog",
    "apply_approved_cover_recommendation",
    "create_cover_experiment",
]
