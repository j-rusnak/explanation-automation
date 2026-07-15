from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from techshort.domain.hashing import stable_hash
from techshort.domain.models import RenderManifest, ScriptManifest, SourceIndex, StoryboardManifest
from techshort.domain.storage import ProjectStore, atomic_write_model, load_model


def renderer_payload(store: ProjectStore, watermarked: bool, preview: bool) -> dict[str, object]:
    project = store.project()
    script = load_model(store.path("script/script.json"), ScriptManifest)
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    return {
        "schemaVersion": "1.0.0",
        "title": project.title,
        "width": 360 if preview else project.width,
        "height": 640 if preview else project.height,
        "fps": project.fps,
        "watermarked": watermarked,
        "segments": [segment.model_dump(mode="json", by_alias=True) for segment in script.segments],
        "scenes": [scene.model_dump(mode="json", by_alias=True) for scene in storyboard.scenes],
    }


def render_video(store: ProjectStore, preview: bool) -> Path:
    project = store.project()
    if not shutil.which("node") or not shutil.which("npm.cmd"):
        raise ValueError("Node.js and npm.cmd are required for rendering")
    if not Path("renderer/package.json").exists():
        raise ValueError("renderer is not installed in this checkout")
    watermarked = preview or project.approvals.final != "approved"
    payload = renderer_payload(store, watermarked=watermarked, preview=preview)
    data_path = Path("renderer/public/project-data.json")
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    output = store.path("renders/previews/preview.mp4" if preview else "renders/final/final.mp4")
    args = [
        "npm.cmd",
        "run",
        "render:preview" if preview else "render:final",
        "--",
        "--output",
        str(output.resolve()),
    ]
    result = subprocess.run(
        args, cwd=Path.cwd(), capture_output=True, text=True, timeout=900, check=False
    )
    if result.returncode:
        raise RuntimeError(f"renderer failed ({result.returncode}): {result.stderr[-2000:]}")
    script = load_model(store.path("script/script.json"), ScriptManifest)
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    sources = load_model(store.path("sources/source-index.json"), SourceIndex)
    manifest = RenderManifest(
        render_id=f"render-{stable_hash(payload)[:12]}",
        width=360 if preview else project.width,
        height=640 if preview else project.height,
        fps=project.fps,
        duration=sum(scene.duration for scene in storyboard.scenes),
        codec="h264",
        script_hash=stable_hash(script),
        storyboard_hash=stable_hash(storyboard),
        scene_versions={scene.scene_id: scene.dependency_hash for scene in storyboard.scenes},
        asset_hashes={},
        renderer_version="pending-lock",
        prompt_versions={"fixture": "fixture-v1"},
        source_hashes={s.source_id: s.content_hash for s in sources.sources},
        output_paths=[output.relative_to(store.root).as_posix()],
    )
    atomic_write_model(
        store.path(
            "renders/previews/render-manifest.json"
            if preview
            else "renders/final/render-manifest.json"
        ),
        manifest,
    )
    return output


def safe_subprocess_args(executable: str, *values: str) -> list[str]:
    """Return an argument array; callers must pass it directly with shell=False."""
    return [executable, *values]
