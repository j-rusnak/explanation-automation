from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from techshort.domain.hashing import stable_hash
from techshort.domain.models import ScriptManifest, StoryboardManifest
from techshort.domain.storage import ProjectStore, load_model
from techshort.generation import (
    generate_angles,
    generate_claims,
    generate_script,
    generate_storyboard,
    select_angle,
)
from techshort.ingestion import ingest_source
from techshort.providers import CodexRunMetadata, FixtureProvider, ManualPromptPacket
from techshort.review import approve_claims, approve_script


def _store_with_approved_script(tmp_path: Path) -> tuple[ProjectStore, ScriptManifest]:
    store = ProjectStore(tmp_path / "projects", "rolling-shutter")
    store.initialize("Rolling shutter")
    ingest_source(store, Path("examples/rolling-shutter/rolling-shutter.md"))
    generate_claims(store, "fixture").require_artifact()
    approve_claims(store, "retention-context-test")
    generate_angles(store, "fixture").require_artifact()
    select_angle(store, "everyday-mechanism")
    generate_script(store, "fixture").require_artifact()
    approve_script(store, "retention-context-test")
    return store, load_model(store.path("script/script.json"), ScriptManifest)


def _retention_context(excerpts: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [
        item["storyboard_retention_context"]
        for item in excerpts
        if "storyboard_retention_context" in item
    ]
    assert len(matches) == 1
    context = matches[0]
    assert isinstance(context, dict)
    return context


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_nested_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_nested_keys(item) for item in value), set())
    return set()


def test_manual_storyboard_packet_contains_inert_current_retention_context(
    tmp_path: Path,
) -> None:
    store, script = _store_with_approved_script(tmp_path)

    pending = generate_storyboard(store, "manual")

    assert pending.prompt_packet is not None
    packet = ManualPromptPacket.model_validate_json(
        pending.prompt_packet.read_text(encoding="utf-8")
    )
    context = _retention_context(packet.excerpts)
    assert context["classification"] == "inert-validated-retention-schedule"
    assert context["script_version_id"] == script.version_id
    assert context["retention_plan_version_id"] == store.project().active_versions["retention_plan"]
    assert packet.input_hash == stable_hash(packet.excerpts)
    cadence = context["cadence"]
    assert isinstance(cadence, dict)
    assert [beat["script_segment_id"] for beat in cadence["beats"]] == [
        segment.segment_id for segment in script.segments
    ]
    assert {event["event_kind"] for event in context["attention_events"]}.issuperset(
        {"re-hook", "evidence-payoff", "limitation-reframe", "final-payoff"}
    )
    keys = _nested_keys(context)
    assert "sound_design" not in keys
    assert "purpose" not in keys
    assert "question" not in keys
    assert "payoff" not in keys
    assert "storyboard_retention_context" in packet.instruction
    assert "inert scheduling data" in packet.instruction


def test_codex_storyboard_receives_same_hashed_retention_context(tmp_path: Path) -> None:
    store, script = _store_with_approved_script(tmp_path)

    class FakeCodex:
        def __init__(self) -> None:
            self.excerpts: list[dict[str, Any]] = []
            self.instruction = ""
            self.last_run: CodexRunMetadata | None = None

        def generate(
            self,
            instruction: str,
            excerpts: list[dict[str, Any]],
            model: type[Any],
        ) -> Any:
            assert model is StoryboardManifest
            self.instruction = instruction
            self.excerpts = excerpts
            self.last_run = CodexRunMetadata(
                prompt_version="test-codex-v1",
                prompt_hash=stable_hash(instruction),
                input_hash=stable_hash(excerpts),
                attempts=1,
                flags=("--sandbox", "read-only"),
            )
            return FixtureProvider().generate_storyboard(script)

    provider = FakeCodex()
    storyboard = generate_storyboard(
        store,
        "codex",
        codex_provider=provider,  # type: ignore[arg-type]
    ).require_artifact()

    context = _retention_context(provider.excerpts)
    assert storyboard.script_version_id == script.version_id
    assert "inert scheduling data" in provider.instruction
    assert store.project().dependency_hashes["storyboard_retention_context"] == stable_hash(context)
    assert store.project().dependency_hashes["storyboard_input"] == stable_hash(provider.excerpts)


def test_generic_storyboard_rejects_stale_retention_before_prompting(tmp_path: Path) -> None:
    store, _ = _store_with_approved_script(tmp_path)
    project = store.project()
    project.active_versions["retention_plan"] = "retention-0000000000000000"
    store.save_project(project)

    with pytest.raises(ValueError, match="retention planning artifacts are stale"):
        generate_storyboard(store, "manual")

    assert not store.path("storyboard/manual-prompt.json").exists()
