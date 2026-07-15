from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from techshort.domain.models import Scene


def _scene_payload() -> dict[str, object]:
    return {
        "scene_id": "scene-1",
        "order": 0,
        "start_time": 0,
        "duration": 5,
        "primitive": "MechanismDiagram",
        "script_segment_ids": ["segment-1"],
        "claim_ids": ["claim-1"],
        "on_screen_text": "Safe title",
        "visual": {
            "title": "Safe diagram",
            "body": "Rows are sampled over time.",
            "nodes": [
                {"id": "a", "label": "Sensor", "x": 0.2, "y": 0.5},
                {"id": "b", "label": "Object", "x": 0.8, "y": 0.5},
            ],
            "edges": [{"source": "a", "target": "b", "label": "time"}],
            "labels": ["early", "late"],
        },
        "accessibility_description": "A safe technical diagram.",
        "evidence_label": "DOCUMENTED",
        "theme_overrides": {},
        "dependency_hash": "a" * 64,
    }


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (("on_screen_text",), '<script src="evil.js"></script>'),
        (("accessibility_description",), '<img src=x onerror="steal()">'),
        (("evidence_label",), "javascript:alert(1)"),
        (("script_segment_ids",), ["segment-1", "<svg onload=evil>"]),
        (("visual", "title"), "data:text/html,<script>evil()</script>"),
        (("visual", "body"), "eval('evil')"),
        (("visual", "labels"), ["safe", "<iframe src=evil></iframe>"]),
        (("visual", "nodes", 0, "label"), "vbscript:evil"),
        (("visual", "edges", 0, "label"), "<a href=javascript:evil>run</a>"),
        (("accessibility_description",), "; powershell.exe -Command steal-secrets"),
    ],
)
def test_active_content_is_rejected_across_scene_fields(
    path: tuple[str | int, ...], payload: object
) -> None:
    scene = deepcopy(_scene_payload())
    target: object = scene
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = payload  # type: ignore[index]

    # A closed enum may reject hostile text before the inert-text validator runs;
    # either validation path is a safe deterministic rejection.
    with pytest.raises(ValidationError):
        Scene.model_validate(scene)


@pytest.mark.parametrize(
    "overrides",
    [
        {"<script>": "red"},
        {"background": "url(javascript:alert(1))"},
        {"background;position": "red"},
    ],
)
def test_active_or_unstructured_theme_overrides_are_rejected(
    overrides: dict[str, str],
) -> None:
    scene = _scene_payload()
    scene["theme_overrides"] = overrides
    with pytest.raises(ValidationError):
        Scene.model_validate(scene)
