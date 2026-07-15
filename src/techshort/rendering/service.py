from __future__ import annotations

import json
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path

from techshort.alignment import cues_from_script, write_caption_files
from techshort.audio.service import active_audio, probe_duration
from techshort.domain.hashing import sha256_file, stable_hash
from techshort.domain.models import (
    AssetManifest,
    EvidenceManifest,
    ProjectManifest,
    RenderManifest,
    ReviewStatus,
    ScriptManifest,
    SourceIndex,
    StoryboardManifest,
)
from techshort.domain.storage import (
    ProjectStore,
    atomic_copy_file,
    atomic_write_model,
    load_model,
)
from techshort.rendering.tools import media_tool

PREVIEW_WIDTH = 360
PREVIEW_HEIGHT = 640
SAFE_RENDER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class MediaMetadata:
    width: int
    height: int
    fps: float
    duration: float
    codec: str


def renderer_payload(
    store: ProjectStore,
    watermarked: bool,
    preview: bool,
    *,
    audio_public_path: str | None = None,
    target_duration: float | None = None,
) -> dict[str, object]:
    """Build validated renderer props on the full logical composition canvas.

    Preview resolution is an encoder concern.  Keeping project dimensions here
    means every layout uses identical coordinates; Remotion's output scale creates
    the 360x640 review file without cropping a full-size design.
    """
    del preview  # retained in the API because callers choose watermark and output mode together
    project = store.project()
    script = load_model(store.path("script/script.json"), ScriptManifest)
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    evidence = load_model(store.path("evidence/evidence.json"), EvidenceManifest)
    evidence_by_id = {span.evidence_id: span for span in evidence.evidence}
    source_duration = _storyboard_duration(storyboard)
    script_duration = sum(segment.approximate_duration for segment in script.segments)
    if target_duration is not None and target_duration <= 0:
        raise ValueError("target render duration must be positive")
    scene_timing_scale = target_duration / source_duration if target_duration is not None else 1.0
    segment_timing_scale = target_duration / script_duration if target_duration is not None else 1.0

    segments: list[dict[str, object]] = []
    for segment in script.segments:
        item = segment.model_dump(mode="json", by_alias=True)
        item["approximate_duration"] = segment.approximate_duration * segment_timing_scale
        segments.append(item)
    scenes: list[dict[str, object]] = []
    for scene in storyboard.scenes:
        item = scene.model_dump(mode="json", by_alias=True)
        item["start_time"] = scene.start_time * scene_timing_scale
        item["duration"] = scene.duration * scene_timing_scale
        if scene.primitive == "SourceReceipt":
            evidence_id = scene.visual.evidence_id
            if evidence_id is None or evidence_id not in evidence_by_id:
                raise ValueError(
                    f"SourceReceipt scene {scene.scene_id} requires a resolvable evidence_id"
                )
            span = evidence_by_id[evidence_id]
            visual = item.get("visual")
            if not isinstance(visual, dict):
                raise ValueError(f"scene {scene.scene_id} has an invalid visual specification")
            visual["evidence_excerpt"] = span.excerpt
            location = span.section_heading or "source"
            if span.printed_page_label:
                location = f"{location}, page {span.printed_page_label}"
            elif span.page_index is not None:
                location = f"{location}, PDF index {span.page_index}"
            visual["source_locator"] = f"{location} · {span.evidence_id}"
        scenes.append(item)
    captions = [asdict(cue) for cue in cues_from_script(script, target_duration=target_duration)]
    payload: dict[str, object] = {
        "schemaVersion": "1.0.0",
        "title": project.title,
        "width": project.width,
        "height": project.height,
        "fps": project.fps,
        "watermarked": watermarked,
        "segments": segments,
        "scenes": scenes,
        "captions": captions,
    }
    if audio_public_path is not None:
        payload["audioPath"] = audio_public_path
    return payload


def render_video(store: ProjectStore, preview: bool) -> Path:
    project = store.project()
    if not preview:
        _require_final_render_approval(store, project)
    repository = _repository_root()
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not shutil.which("node") or not npm:
        raise ValueError("Node.js and npm are required for rendering")
    if (
        not (repository / "package.json").exists()
        or not (repository / "renderer/src/index.ts").exists()
    ):
        raise ValueError("renderer is not installed in this checkout")

    narration = active_audio(store)
    narration_duration = probe_duration(narration) if narration is not None else None
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    expected_duration = narration_duration or _storyboard_duration(storyboard)
    watermarked = preview
    output = store.path("renders/previews/preview.mp4" if preview else "renders/final/final.mp4")
    output.parent.mkdir(parents=True, exist_ok=True)
    public_root = repository / "renderer/public"
    public_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="techshort-input-", dir=public_root) as input_stage:
        input_directory = Path(input_stage)
        audio_public_path: str | None = None
        if narration is not None:
            staged_audio = input_directory / f"narration{narration.suffix.lower()}"
            shutil.copyfile(narration, staged_audio)
            audio_public_path = staged_audio.relative_to(public_root).as_posix()
        payload = renderer_payload(
            store,
            watermarked=watermarked,
            preview=preview,
            audio_public_path=audio_public_path,
            target_duration=narration_duration,
        )
        props_path = input_directory / "project-data.json"
        props_path.write_text(json.dumps(payload, indent=2), encoding="utf-8", newline="\n")

        script = load_model(store.path("script/script.json"), ScriptManifest)
        cues = cues_from_script(script, target_duration=narration_duration)
        write_caption_files(store.path("captions"), cues)

        with tempfile.TemporaryDirectory(prefix="techshort-output-", dir=output.parent) as stage:
            output_stage = Path(stage)
            staged_video = output_stage / output.name
            scale = _preview_scale(project.width, project.height) if preview else 1.0
            args = [
                npm,
                "run",
                "render:preview" if preview else "render:final",
                "--",
                "--output",
                str(staged_video.resolve()),
                "--props",
                str(props_path.resolve()),
                "--scale",
                repr(scale),
            ]
            result = subprocess.run(
                args,
                cwd=repository,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=900,
                check=False,
            )
            if result.returncode:
                details = (result.stderr + "\n" + result.stdout)[-4000:]
                raise RuntimeError(f"renderer failed ({result.returncode}): {details}")
            if not staged_video.is_file() or staged_video.stat().st_size == 0:
                raise RuntimeError("renderer reported success but produced no video")

            metadata = probe_render_metadata(staged_video)
            derivative_names = _generate_derivatives(
                staged_video, output_stage, metadata.duration if metadata else expected_duration
            )
            output_paths = [output.relative_to(store.root).as_posix()]
            staged_outputs = {output_paths[0]: staged_video}
            for name in derivative_names:
                destination = output.parent / name
                relative = destination.relative_to(store.root).as_posix()
                output_paths.append(relative)
                staged_outputs[relative] = output_stage / name

            manifest = _build_render_manifest(
                store,
                staged_video,
                payload,
                preview=preview,
                expected_duration=expected_duration,
                narration=narration,
                staged_outputs=staged_outputs,
            )
            staged_manifest = output_stage / "render-manifest.json"
            atomic_write_model(staged_manifest, manifest)

            # No active file is replaced until the complete new bundle and its
            # validated manifest exist. Preserve the prior exact bundle first.
            _archive_active_render(store, preview=preview)
            for relative, staged_path in staged_outputs.items():
                destination = store.path(relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged_path, destination)
            os.replace(staged_manifest, _render_manifest_path(store, preview))
            _activate_render(store, preview=preview, manifest=manifest)
    return output


def probe_render_metadata(path: Path) -> MediaMetadata | None:
    ffprobe = media_tool("ffprobe")
    if not ffprobe:
        return None
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"ffprobe failed for rendered video: {result.stderr[-1000:]}")
    try:
        data: dict[str, object] = json.loads(result.stdout)
        streams = data.get("streams")
        if not isinstance(streams, list):
            raise ValueError("stream list is missing")
        video = next(
            item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"
        )
        format_data = data.get("format")
        if not isinstance(format_data, dict):
            raise ValueError("format metadata is missing")
        fps = _parse_frame_rate(str(video.get("avg_frame_rate") or video.get("r_frame_rate")))
        duration = float(format_data["duration"])
        metadata = MediaMetadata(
            width=int(video["width"]),
            height=int(video["height"]),
            fps=fps,
            duration=duration,
            codec=str(video["codec_name"]),
        )
    except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("ffprobe returned incomplete rendered-video metadata") from exc
    if (
        metadata.width <= 0
        or metadata.height <= 0
        or not all(math.isfinite(item) and item > 0 for item in (metadata.fps, metadata.duration))
    ):
        raise RuntimeError("ffprobe returned invalid rendered-video metadata")
    return metadata


def _build_render_manifest(
    store: ProjectStore,
    output: Path,
    payload: dict[str, object],
    *,
    preview: bool,
    expected_duration: float,
    narration: Path | None,
    staged_outputs: dict[str, Path],
) -> RenderManifest:
    project = store.project()
    script = load_model(store.path("script/script.json"), ScriptManifest)
    storyboard = load_model(store.path("storyboard/storyboard.json"), StoryboardManifest)
    sources = load_model(store.path("sources/source-index.json"), SourceIndex)
    assets_path = store.path("assets/asset-manifest.json")
    assets = (
        load_model(assets_path, AssetManifest)
        if assets_path.exists()
        else AssetManifest(version_id="assets-empty")
    )
    metadata = probe_render_metadata(output)
    fallback_width = PREVIEW_WIDTH if preview else project.width
    fallback_height = PREVIEW_HEIGHT if preview else project.height
    output_hashes = {relative: sha256_file(path) for relative, path in staged_outputs.items()}
    identity = {
        "script": stable_hash(script),
        "storyboard": stable_hash(storyboard),
        "watermarked": payload["watermarked"],
        "audio": sha256_file(narration) if narration else None,
        "dimensions": [fallback_width, fallback_height],
        "fps": metadata.fps if metadata else project.fps,
        "renderer": _renderer_version(),
        "outputs": output_hashes,
    }
    watermarked = payload.get("watermarked")
    if not isinstance(watermarked, bool):
        raise ValueError("renderer payload is missing its watermark state")
    manifest = RenderManifest(
        render_id=f"render-{stable_hash(identity)[:16]}",
        width=metadata.width if metadata else fallback_width,
        height=metadata.height if metadata else fallback_height,
        fps=metadata.fps if metadata else project.fps,
        duration=metadata.duration if metadata else expected_duration,
        codec=metadata.codec if metadata else "h264",
        script_hash=stable_hash(script),
        storyboard_hash=stable_hash(storyboard),
        scene_versions={scene.scene_id: scene.dependency_hash for scene in storyboard.scenes},
        asset_hashes={asset.asset_id: asset.sha256 for asset in assets.assets},
        audio_hash=sha256_file(narration) if narration else None,
        renderer_version=_renderer_version(),
        prompt_versions=_generation_prompt_versions(store),
        source_hashes={source.source_id: source.content_hash for source in sources.sources},
        output_paths=list(staged_outputs),
        output_hashes=output_hashes,
        watermarked=watermarked,
    )
    return manifest


def _render_manifest_path(store: ProjectStore, preview: bool) -> Path:
    return store.path(
        "renders/previews/render-manifest.json" if preview else "renders/final/render-manifest.json"
    )


def _archive_active_render(store: ProjectStore, *, preview: bool) -> None:
    """Copy the exact active render bundle into immutable version history."""

    manifest_path = _render_manifest_path(store, preview)
    render_directory = manifest_path.parent.resolve()
    primary_name = "preview.mp4" if preview else "final.mp4"
    known_outputs = {primary_name, "cover.png", "contact-sheet.png"}
    if not manifest_path.is_file():
        if any((render_directory / name).exists() for name in known_outputs):
            raise ValueError("existing render has no valid manifest and cannot be replaced safely")
        return

    manifest = load_model(manifest_path, RenderManifest)
    if not SAFE_RENDER_ID.fullmatch(manifest.render_id):
        raise ValueError("existing render manifest has an unsafe render_id")
    project = store.project()
    active_key = "preview_render" if preview else "final_render"
    active_id = project.active_versions.get(active_key)
    if active_id is not None and active_id != manifest.render_id:
        raise ValueError("active render version does not match its manifest")
    if set(manifest.output_paths) != set(manifest.output_hashes):
        raise ValueError("existing render manifest has incomplete output hashes")
    declared_names = {Path(relative).name for relative in manifest.output_paths}
    if any(
        (render_directory / name).exists() and name not in declared_names for name in known_outputs
    ):
        raise ValueError("existing render has an untracked output and cannot be replaced safely")

    archive = render_directory / "versions" / manifest.render_id
    for relative, expected_hash in manifest.output_hashes.items():
        source = store.path(relative)
        if source.parent.resolve() != render_directory:
            raise ValueError(
                "existing render manifest references an output outside its render directory"
            )
        if source.resolve() == manifest_path.resolve():
            raise ValueError("render manifest cannot declare itself as a media output")
        if not source.is_file() or sha256_file(source) != expected_hash:
            raise ValueError("existing render output does not match its manifest")
        _archive_render_file(source, archive / source.name)
    _archive_render_file(manifest_path, archive / manifest_path.name)


def _archive_render_file(source: Path, destination: Path) -> None:
    if destination.is_file():
        if sha256_file(destination) != sha256_file(source):
            raise ValueError("render history contains a conflicting archived file")
        return
    atomic_copy_file(source, destination)


def _activate_render(store: ProjectStore, *, preview: bool, manifest: RenderManifest) -> None:
    """Record the exact active output and all inputs that determine it."""

    kind = "preview" if preview else "final"
    project = store.project()
    project.active_versions[f"{kind}_render"] = manifest.render_id
    project.dependency_hashes[f"{kind}_render_output"] = stable_hash(manifest.output_hashes)
    project.dependency_hashes[f"{kind}_render_dependencies"] = stable_hash(
        {
            "script": manifest.script_hash,
            "storyboard": manifest.storyboard_hash,
            "scenes": manifest.scene_versions,
            "assets": manifest.asset_hashes,
            "audio": manifest.audio_hash,
            "renderer": manifest.renderer_version,
            "prompts": manifest.prompt_versions,
            "sources": manifest.source_hashes,
            "dimensions": [manifest.width, manifest.height, manifest.fps],
            "watermarked": manifest.watermarked,
        }
    )
    store.save_project(project)


def _generation_prompt_versions(store: ProjectStore) -> dict[str, str]:
    """Record the exact prompt template and prompt hash used for each stage."""

    versions: dict[str, str] = {}
    for stage, relative in (
        ("claims", "claims/generation-receipt.json"),
        ("claims-critique", "claims/critique-receipt.json"),
        ("angles", "script/angles-generation-receipt.json"),
        ("script", "script/generation-receipt.json"),
        ("storyboard", "storyboard/generation-receipt.json"),
    ):
        path = store.path(relative)
        if not path.is_file():
            continue
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid {stage} generation receipt") from exc
        if not isinstance(receipt, dict):
            raise ValueError(f"invalid {stage} generation receipt")
        version = receipt.get("prompt_version")
        prompt_hash = receipt.get("prompt_hash")
        if not isinstance(version, str) or not isinstance(prompt_hash, str):
            raise ValueError(f"incomplete {stage} generation receipt")
        versions[stage] = f"{version}@{prompt_hash}"
    return versions


def _require_final_render_approval(store: ProjectStore, project: ProjectManifest) -> None:
    """Keep the unwatermarked-render gate inside the library boundary."""

    # Imported lazily because review hashes include render inputs from this module.
    from techshort.review import final_review_hash, has_current_approval

    for gate in ("claims", "script", "storyboard", "rights", "final"):
        if getattr(project.approvals, gate) != ReviewStatus.APPROVED:
            raise ValueError(f"final render is blocked until the {gate} gate is approved")
    if not has_current_approval(store, "final", project.project_id):
        raise ValueError("final render is blocked because final approval is missing or stale")
    if project.dependency_hashes.get("final_approval") != final_review_hash(store):
        raise ValueError("final render is blocked because reviewed preview inputs changed")


def _generate_derivatives(video: Path, directory: Path, duration: float) -> list[str]:
    ffmpeg = media_tool("ffmpeg")
    if not ffmpeg:
        return []
    cover = directory / "cover.png"
    cover_time = min(2.0, max(0.0, duration / 2))
    still = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-ss",
            f"{cover_time:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            str(cover),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    if still.returncode or not cover.is_file() or cover.stat().st_size == 0:
        raise RuntimeError(f"cover generation failed: {still.stderr[-1000:]}")

    contact_sheet = directory / "contact-sheet.png"
    _generate_contact_sheet(ffmpeg, video, contact_sheet, duration, directory)
    return [cover.name, contact_sheet.name]


def _generate_contact_sheet(
    ffmpeg: str, video: Path, destination: Path, duration: float, temporary: Path
) -> None:
    """Build a representative 2x3 PNG using only FFmpeg raw frames and stdlib.

    Remotion's bundled FFmpeg intentionally ships a small filter set without
    ``fps``, ``pad``, or ``tile``.  Extracting six bounded RGB frames and encoding
    the final PNG locally keeps contact-sheet generation portable and offline.
    """
    frame_width = 270
    frame_height = 480
    frame_size = frame_width * frame_height * 3
    frames: list[bytes] = []
    for index in range(6):
        timestamp = duration * (index + 0.5) / 6
        raw_path = temporary / f"contact-frame-{index}.rgb"
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(video),
                "-an",
                "-vf",
                f"scale={frame_width}:{frame_height}",
                "-frames:v",
                "1",
                "-f",
                "image2",
                "-vcodec",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                str(raw_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        if result.returncode or not raw_path.is_file():
            raise RuntimeError(f"contact-sheet frame {index + 1} failed: {result.stderr[-1000:]}")
        pixels = raw_path.read_bytes()
        if len(pixels) != frame_size:
            raise RuntimeError(f"contact-sheet frame {index + 1} has an invalid byte count")
        frames.append(pixels)

    margin = 8
    padding = 8
    width = margin * 2 + frame_width * 2 + padding
    height = margin * 2 + frame_height * 3 + padding * 2
    background = bytes((7, 17, 36))
    canvas = bytearray(background * (width * height))
    for index, pixels in enumerate(frames):
        column = index % 2
        row = index // 2
        target_x = margin + column * (frame_width + padding)
        target_y = margin + row * (frame_height + padding)
        for source_y in range(frame_height):
            source_start = source_y * frame_width * 3
            target_start = ((target_y + source_y) * width + target_x) * 3
            canvas[target_start : target_start + frame_width * 3] = pixels[
                source_start : source_start + frame_width * 3
            ]
    _write_rgb_png(destination, width, height, bytes(canvas))


def _write_rgb_png(path: Path, width: int, height: int, pixels: bytes) -> None:
    if len(pixels) != width * height * 3:
        raise ValueError("RGB PNG input has an invalid byte count")
    scanlines = b"".join(
        b"\x00" + pixels[row * width * 3 : (row + 1) * width * 3] for row in range(height)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(scanlines, level=6))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def _parse_frame_rate(value: str) -> float:
    numerator, separator, denominator = value.partition("/")
    if not separator:
        return float(value)
    divisor = float(denominator)
    if divisor == 0:
        raise ValueError("frame-rate denominator is zero")
    return float(numerator) / divisor


def _storyboard_duration(storyboard: StoryboardManifest) -> float:
    if not storyboard.scenes:
        raise ValueError("storyboard has no scenes")
    return max(scene.start_time + scene.duration for scene in storyboard.scenes)


def _preview_scale(width: int, height: int) -> float:
    width_scale = PREVIEW_WIDTH / width
    height_scale = PREVIEW_HEIGHT / height
    if not math.isclose(width_scale, height_scale, rel_tol=0, abs_tol=1e-9):
        raise ValueError("preview rendering requires a 9:16 project canvas")
    return width_scale


def _repository_root() -> Path:
    candidates = (Path.cwd(), Path(__file__).resolve().parents[3])
    for candidate in candidates:
        if (candidate / "package.json").is_file() and (candidate / "renderer").is_dir():
            return candidate
    return Path.cwd()


def _renderer_version() -> str:
    package = _repository_root() / "node_modules/remotion/package.json"
    try:
        value = json.loads(package.read_text(encoding="utf-8"))["version"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return "unknown"
    return f"remotion-{value}"


def safe_subprocess_args(executable: str, *values: str) -> list[str]:
    """Return an argument array; callers must pass it directly with shell=False."""
    return [executable, *values]
