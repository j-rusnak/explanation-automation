from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from techshort.audio import NarrationVoice, SynthesizedNarration
from techshort.cli.app import app
from techshort.domain.hashing import sha256_file
from techshort.domain.storage import ProjectStore
from techshort.experiments import (
    ExperimentStore,
    ExperimentVariable,
    OrganicPlatform,
    VariantRole,
    approve_experiment,
    build_variant,
    initialize_experiment,
)
from techshort.publication import GRANT_CONFIRMATION

runner = CliRunner()


def _experiment(tmp_path: Path, monkeypatch: Any) -> tuple[ProjectStore, ExperimentStore]:
    root = tmp_path / "projects"
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(root))
    project = ProjectStore(root, "cli-experiment")
    project.initialize("CLI experiment")
    control_path = project.path("renders/final/control.mp4")
    treatment_path = project.path("renders/final/treatment.mp4")
    control_path.write_bytes(b"control-video")
    treatment_path.write_bytes(b"treatment-video")
    locked = {
        "locked_factual_hash": "1" * 64,
        "evidence_hash": "2" * 64,
        "claims_hash": "3" * 64,
        "limitation_hash": "4" * 64,
        "rights_hash": "5" * 64,
    }
    variants = [
        build_variant(
            label="Control hook",
            role=VariantRole.CONTROL,
            variable=ExperimentVariable.HOOK,
            variable_value="direct question",
            media_path="renders/final/control.mp4",
            media_hash=sha256_file(control_path),
            **locked,
        ),
        build_variant(
            label="Treatment hook",
            role=VariantRole.TREATMENT,
            variable=ExperimentVariable.HOOK,
            variable_value="visual surprise",
            media_path="renders/final/treatment.mp4",
            media_hash=sha256_file(treatment_path),
            **locked,
        ),
    ]
    manifest = initialize_experiment(
        project,
        name="CLI hook experiment",
        hypothesis="The visual surprise will improve completion rate.",
        platform=OrganicPlatform.TIKTOK,
        variable=ExperimentVariable.HOOK,
        variants=variants,
        minimum_views_per_variant=500,
    )
    return project, ExperimentStore(project, manifest.experiment_id)


def _request_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "experiment_id": "exp-1111111111111111",
        "variant_id": "var-2222222222222222",
        "platform": "tiktok",
        "final_mp4": "renders/final/video.mp4",
        "expected_media_hash": "1" * 64,
        "cover_png": "export/cover.png",
        "expected_cover_hash": "2" * 64,
        "captions_srt": "captions/captions.srt",
        "captions_vtt": "captions/captions.vtt",
        "title": "A reviewed technical explanation",
        "post_copy": "This package preserves the reviewed explanation and its limitation.",
        "alt_text": "A vertical technical animation with captions.",
        "hashtags": ["Engineering"],
    }


def test_engagement_commands_are_discoverable() -> None:
    main = runner.invoke(app, ["--help"])
    assert main.exit_code == 0
    assert "experiment" in main.stdout
    assert "publication" in main.stdout

    audio = runner.invoke(app, ["audio", "--help"])
    assert audio.exit_code == 0
    for command in ("voices", "synthesize", "sound-design"):
        assert command in audio.stdout

    experiment = runner.invoke(app, ["experiment", "--help"])
    assert experiment.exit_code == 0
    for command in (
        "create-cover",
        "approve",
        "status",
        "import-observations",
        "analyze",
        "approve-recommendation",
        "apply-recommendation",
    ):
        assert command in experiment.stdout

    publication = runner.invoke(app, ["publication", "--help"])
    assert publication.exit_code == 0
    for command in ("diagnostics", "prepare-request", "package", "consent-package"):
        assert command in publication.stdout


def test_cover_creation_and_application_commands_delegate_reviewed_workflow(
    tmp_path: Path, monkeypatch: Any
) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(root))
    ProjectStore(root, "cover-cli").initialize("Cover CLI")
    observed: dict[str, object] = {}

    class FakeManifest:
        experiment_id = "exp-1111111111111111"
        variants = [object(), object(), object()]

        def model_dump_json(self, *, indent: int) -> str:
            return json.dumps({"experiment_id": self.experiment_id}, indent=indent)

    class FakeReceipt:
        application_id = "application-1111111111111111"
        applied_candidate_id = "cover-comparison"
        changed_production_default = True

        def model_dump_json(self, *, indent: int) -> str:
            return json.dumps({"application_id": self.application_id}, indent=indent)

    def fake_create(project: ProjectStore, **options: object) -> FakeManifest:
        observed["create_slug"] = project.slug
        observed["create_options"] = options
        return FakeManifest()

    def fake_apply(
        experiment_store: ExperimentStore, recommendation_id: str, reviewer: str
    ) -> FakeReceipt:
        observed["apply"] = (
            experiment_store.experiment_id,
            recommendation_id,
            reviewer,
        )
        return FakeReceipt()

    monkeypatch.setattr("techshort.cli.app.create_cover_experiment", fake_create)
    monkeypatch.setattr("techshort.cli.app.apply_approved_cover_recommendation", fake_apply)
    created = runner.invoke(
        app,
        [
            "experiment",
            "create-cover",
            "cover-cli",
            "--name",
            "Reviewed covers",
            "--hypothesis",
            "A mechanism cover will improve completion rate.",
            "--platform",
            "instagram-reels",
            "--candidate",
            "cover-scanline",
            "--candidate",
            "cover-comparison",
            "--json",
        ],
    )
    assert created.exit_code == 0, created.stdout
    create_options = observed["create_options"]
    assert isinstance(create_options, dict)
    assert create_options["platform"] is OrganicPlatform.INSTAGRAM_REELS
    assert create_options["candidate_ids"] == ["cover-scanline", "cover-comparison"]

    applied = runner.invoke(
        app,
        [
            "experiment",
            "apply-recommendation",
            "cover-cli",
            "exp-1111111111111111",
            "rec-2222222222222222",
            "--reviewer",
            "human-reviewer",
            "--json",
        ],
    )
    assert applied.exit_code == 0, applied.stdout
    assert observed["apply"] == (
        "exp-1111111111111111",
        "rec-2222222222222222",
        "human-reviewer",
    )


def test_audio_voice_discovery_and_synthesis_are_machine_readable(
    tmp_path: Path, monkeypatch: Any
) -> None:
    voice = NarrationVoice("windows-sapi", "Fixture Voice", "en-US", "Neutral", "Adult")

    class FixtureProvider:
        provider_id = "windows-sapi"

        def list_voices(self) -> list[NarrationVoice]:
            return [voice]

    monkeypatch.setattr("techshort.cli.app.WindowsSapiNarrationProvider", FixtureProvider)
    voices = runner.invoke(app, ["audio", "voices", "--json"])
    assert voices.exit_code == 0
    assert json.loads(voices.stdout)["voices"][0]["name"] == "Fixture Voice"

    root = tmp_path / "projects"
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(root))
    ProjectStore(root, "audio-cli").initialize("Audio CLI")
    observed: dict[str, Any] = {}

    def fake_synthesize(project: ProjectStore, **options: Any) -> SynthesizedNarration:
        observed["slug"] = project.slug
        observed.update(options)
        return SynthesizedNarration(
            provider="windows-sapi",
            voice=voice,
            audio_path=project.path("audio/narration.wav"),
            transcript_path=project.path("audio/narration.txt"),
            receipt_path=project.path("audio/narration-synthesis.json"),
            duration_seconds=52.5,
            rate=2,
            volume=90,
        )

    monkeypatch.setattr("techshort.cli.app.synthesize_local_narration", fake_synthesize)
    synthesized = runner.invoke(
        app,
        [
            "audio",
            "synthesize",
            "audio-cli",
            "--voice",
            "Fixture Voice",
            "--rate",
            "2",
            "--volume",
            "90",
            "--json",
        ],
    )
    assert synthesized.exit_code == 0, synthesized.stdout
    payload = json.loads(synthesized.stdout)
    assert payload["duration_seconds"] == 52.5
    assert payload["rights_status"] == "unknown"
    assert observed == {
        "slug": "audio-cli",
        "voice_name": "Fixture Voice",
        "rate": 2,
        "volume": 90,
        "rights_status": "unknown",
        "license_name": None,
        "required_attribution": None,
    }


def test_sound_design_command_uses_allowlisted_preset(tmp_path: Path, monkeypatch: Any) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(root))
    ProjectStore(root, "sound-cli").initialize("Sound CLI")
    observed: dict[str, object] = {}

    class FakeReceipt:
        preset = "present"
        events = [1, 2, 3]
        output_path = "audio/sound-design.wav"

        def model_dump_json(self, *, indent: int) -> str:
            return json.dumps({"preset": self.preset, "events": 3}, indent=indent)

    def fake_generate(project: ProjectStore, preset: str) -> FakeReceipt:
        observed.update(slug=project.slug, preset=preset)
        return FakeReceipt()

    monkeypatch.setattr("techshort.cli.app.generate_sound_design", fake_generate)
    result = runner.invoke(
        app, ["audio", "sound-design", "sound-cli", "--preset", "present", "--json"]
    )
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["preset"] == "present"
    assert observed == {"slug": "sound-cli", "preset": "present"}


def test_experiment_cli_runs_approval_import_analysis_and_recommendation_review(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _, experiment_store = _experiment(tmp_path, monkeypatch)
    experiment_id = experiment_store.experiment_id

    listed = runner.invoke(app, ["experiment", "list", "cli-experiment", "--json"])
    assert listed.exit_code == 0
    assert json.loads(listed.stdout)["experiments"] == [experiment_id]

    approved = runner.invoke(
        app,
        ["experiment", "approve", "cli-experiment", experiment_id, "--json"],
    )
    assert approved.exit_code == 0, approved.stdout
    approved_payload = json.loads(approved.stdout)
    assert approved_payload["review_status"] == "approved"

    manifest = experiment_store.manifest()
    started = datetime(2026, 7, 1, 12, tzinfo=UTC)
    ended = started + timedelta(hours=24)
    captured = ended + timedelta(minutes=5)
    observations = [
        {
            "experiment_id": experiment_id,
            "variant_id": variant.variant_id,
            "platform": "tiktok",
            "publication_reference": f"manual-post-{index}",
            "window_started_at": started.isoformat(),
            "window_ended_at": ended.isoformat(),
            "captured_at": captured.isoformat(),
            "view_count": 2000,
            "completed_view_count": 650 if index == 0 else 1350,
        }
        for index, variant in enumerate(manifest.variants)
    ]
    observations_file = tmp_path / "observations.json"
    observations_file.write_text(json.dumps(observations), encoding="utf-8")
    imported = runner.invoke(
        app,
        [
            "experiment",
            "import-observations",
            "cli-experiment",
            experiment_id,
            str(observations_file),
            "--json",
        ],
    )
    assert imported.exit_code == 0, imported.stdout
    assert len(json.loads(imported.stdout)) == 2

    analyzed = runner.invoke(
        app, ["experiment", "analyze", "cli-experiment", experiment_id, "--json"]
    )
    assert analyzed.exit_code == 0, analyzed.stdout
    recommendation = json.loads(analyzed.stdout)
    assert recommendation["action"] == "adopt-variant"
    approved_recommendation = runner.invoke(
        app,
        [
            "experiment",
            "approve-recommendation",
            "cli-experiment",
            experiment_id,
            recommendation["recommendation_id"],
            "--json",
        ],
    )
    assert approved_recommendation.exit_code == 0, approved_recommendation.stdout
    assert json.loads(approved_recommendation.stdout)["review_status"] == "approved"

    status = runner.invoke(app, ["experiment", "status", "cli-experiment", experiment_id, "--json"])
    assert status.exit_code == 0
    assert json.loads(status.stdout)["blockers"] == []


def test_publication_diagnostics_never_claim_automated_upload() -> None:
    for provider, status in (("manual", "manual-ready"), ("official", "unavailable")):
        result = runner.invoke(
            app,
            [
                "publication",
                "diagnostics",
                "tiktok",
                "--provider",
                provider,
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["status"] == status
        assert not payload["automated_publication_supported"]
        assert not payload["credentials_read"]
        assert not payload["credentials_stored"]


def test_prepare_request_derives_locked_paths_from_approved_variant(
    tmp_path: Path, monkeypatch: Any
) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(root))
    project = ProjectStore(root, "request-cli")
    project.initialize("Request CLI")
    media = project.path("export/request-cli.mp4")
    media.write_bytes(b"reviewed-video")
    covers = []
    for name in ("control", "treatment"):
        path = project.path(f"experiments/cover-{name}.png")
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + name.encode("ascii"))
        covers.append(path)
    project.path("export/request-cli.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nReviewed.\n", encoding="utf-8"
    )
    project.path("export/request-cli.vtt").write_text(
        "WEBVTT\n\n00:00.000 --> 00:01.000\nReviewed.\n", encoding="utf-8"
    )
    locks = {
        "locked_factual_hash": "1" * 64,
        "evidence_hash": "2" * 64,
        "claims_hash": "3" * 64,
        "limitation_hash": "4" * 64,
        "rights_hash": "5" * 64,
    }
    variants = [
        build_variant(
            label=f"{role.value.title()} cover",
            role=role,
            variable=ExperimentVariable.COVER,
            variable_value=f"cover-{role.value}",
            media_path="export/request-cli.mp4",
            media_hash=sha256_file(media),
            cover_path=path.relative_to(project.root).as_posix(),
            cover_hash=sha256_file(path),
            **locks,
        )
        for role, path in zip((VariantRole.CONTROL, VariantRole.TREATMENT), covers, strict=True)
    ]
    manifest = initialize_experiment(
        project,
        name="Publication request covers",
        hypothesis="The treatment cover will improve completion rate.",
        platform=OrganicPlatform.TIKTOK,
        variable=ExperimentVariable.COVER,
        variants=variants,
    )
    manifest = approve_experiment(ExperimentStore(project, manifest.experiment_id), "reviewer")
    variant = manifest.variants[0]

    result = runner.invoke(
        app,
        [
            "publication",
            "prepare-request",
            "request-cli",
            manifest.experiment_id,
            variant.variant_id,
            "--post-copy",
            "One frame can contain many capture times, with an important limitation.",
            "--alt-text",
            "A vertical diagram shows image rows captured at successive times.",
            "--hashtag",
            "CameraTech",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    request = payload["request"]
    assert request["final_mp4"] == variant.media_path
    assert request["cover_png"] == variant.cover_path
    assert request["expected_media_hash"] == variant.media_hash
    assert request["expected_cover_hash"] == variant.cover_hash
    assert request["hashtags"] == ["CameraTech"]
    assert project.path(payload["request_path"]).is_file()


def test_publication_commands_build_only_local_immutable_packages(
    tmp_path: Path, monkeypatch: Any
) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("TECHSHORT_PROJECTS_ROOT", str(root))
    ProjectStore(root, "publication-cli").initialize("Publication CLI")
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(_request_payload()), encoding="utf-8")
    package_file = tmp_path / "package-manifest.json"
    package_file.write_text("{}", encoding="utf-8")
    calls: list[tuple[str, object]] = []

    class FakeResult:
        package_directory = "experiments/exp/publication/package"

        def model_dump_json(self, *, indent: int) -> str:
            return json.dumps({"package_directory": self.package_directory}, indent=indent)

    def fake_build(
        _project: ProjectStore, _request: object, *, consent: object | None = None
    ) -> FakeResult:
        calls.append(("build", consent))
        return FakeResult()

    class FakePackageModel:
        @classmethod
        def model_validate_json(cls, _payload: str) -> object:
            return object()

    consent = object()
    monkeypatch.setattr("techshort.cli.app.build_organic_publication_package", fake_build)
    monkeypatch.setattr("techshort.cli.app.OrganicPublicationPackage", FakePackageModel)
    monkeypatch.setattr(
        "techshort.cli.app.record_publication_consent",
        lambda *_args, **_kwargs: consent,
    )

    pending = runner.invoke(
        app,
        ["publication", "package", "publication-cli", str(request_file)],
    )
    assert pending.exit_code == 0, pending.stdout
    assert "No upload occurred" in pending.stdout

    authorized = runner.invoke(
        app,
        [
            "publication",
            "consent-package",
            "publication-cli",
            str(request_file),
            str(package_file),
            "--state",
            "granted",
            "--confirmation",
            GRANT_CONFIRMATION,
        ],
    )
    assert authorized.exit_code == 0, authorized.stdout
    assert "no upload occurred" in authorized.stdout
    assert calls == [("build", None), ("build", consent)]
