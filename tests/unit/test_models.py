from __future__ import annotations

import pytest
from pydantic import ValidationError

from techshort.domain.hashing import stable_hash
from techshort.domain.models import Asset, Scene, ScriptManifest, ScriptSegment, VisualSpec
from techshort.domain.storage import sanitize_filename, validate_slug


def test_schema_rejects_unknown_version_and_fields() -> None:
    with pytest.raises(ValidationError):
        ScriptSegment.model_validate(
            {
                "schema_version": "2.0.0",
                "segment_id": "x",
                "text": "fact",
                "segment_type": "factual",
                "claim_ids": ["c"],
                "approximate_duration": 1,
            }
        )
    with pytest.raises(ValidationError):
        VisualSpec(title="safe", arbitrary_javascript="alert(1)")  # type: ignore[call-arg]


def test_factual_segment_and_limitation_are_required() -> None:
    with pytest.raises(ValidationError, match="requires at least one claim"):
        ScriptSegment(
            segment_id="s1",
            text="unsupported",
            segment_type="factual",
            approximate_duration=1,
        )
    factual = ScriptSegment(
        segment_id="s1",
        text="supported",
        segment_type="factual",
        claim_ids=["c1"],
        approximate_duration=1,
    )
    with pytest.raises(ValidationError, match="meaningful limitation"):
        ScriptManifest(
            version_id="v1",
            claims_version_id="c1",
            angle="everyday-mechanism",
            segments=[factual],
        )


@pytest.mark.parametrize("segment_type", ["transition", "cta"])
def test_nonfactual_label_cannot_bypass_claim_link(segment_type: str) -> None:
    with pytest.raises(ValidationError, match="requires at least one claim"):
        ScriptSegment(
            segment_id="misclassified",
            text="This factual conclusion has been deliberately misclassified.",
            segment_type=segment_type,  # type: ignore[arg-type]
            approximate_duration=1,
        )


def test_stable_hash_and_filename_safety() -> None:
    assert stable_hash({"b": 2, "a": 1}) == stable_hash({"a": 1, "b": 2})
    assert sanitize_filename("../hostile name.md") == "hostile-name.md"
    with pytest.raises(ValueError):
        validate_slug("../../escape")


def test_unknown_rights_can_be_represented_but_not_assumed_safe() -> None:
    asset = Asset(
        asset_id="asset-1",
        asset_type="image",
        local_path="assets/originals/image.png",
        sha256="a" * 64,
        origin="unknown",
        creator="unknown",
        license="unknown",
        rights_status="unknown",
        embedding_allowed=False,
    )
    assert not asset.embedding_allowed


def test_scene_numbers_must_be_finite() -> None:
    with pytest.raises(ValidationError, match="finite number"):
        VisualSpec(title="safe", series=[1.0, float("nan")])


def test_scene_theme_overrides_are_color_token_allowlisted() -> None:
    base = {
        "scene_id": "scene-1",
        "order": 0,
        "start_time": 0,
        "duration": 1,
        "primitive": "KineticText",
        "script_segment_ids": ["segment-1"],
        "on_screen_text": "Safe",
        "visual": {"title": "Safe"},
        "accessibility_description": "Safe title card",
        "dependency_hash": "a" * 64,
    }
    Scene.model_validate({**base, "theme_overrides": {"accent": "#123ABC"}})
    with pytest.raises(ValidationError, match="not allowlisted"):
        Scene.model_validate({**base, "theme_overrides": {"font": "#123ABC"}})
    with pytest.raises(ValidationError, match="hexadecimal"):
        Scene.model_validate({**base, "theme_overrides": {"accent": "red"}})
