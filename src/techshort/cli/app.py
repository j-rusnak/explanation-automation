from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from techshort import __version__
from techshort.alignment import cues_from_script, write_caption_files
from techshort.audio import (
    active_audio,
    import_audio,
    import_transcript,
    probe_duration,
    set_narration_mode,
)
from techshort.configuration import PACING_PROFILES, set_pacing_profile, set_safe_zone
from techshort.domain.hashing import sha256_file, stable_hash
from techshort.domain.models import (
    ClaimCritiqueReport,
    QAReport,
    ReviewStatus,
    SafeZoneInsets,
    ScriptManifest,
)
from techshort.domain.storage import ProjectStore, load_model
from techshort.export import export_project, generate_evidence_page
from techshort.generation import (
    generate_angles,
    generate_claims,
    generate_fixture_covers,
    generate_script,
    generate_storyboard,
    select_angle,
    select_cover,
)
from techshort.ingestion import ingest_source
from techshort.providers import CodexCliProvider
from techshort.qa import run_qa
from techshort.rendering import render_video
from techshort.rendering.tools import media_tool, remotion_browser_readiness
from techshort.review import (
    approve_claims,
    approve_final,
    approve_rights,
    approve_script,
    approve_storyboard,
    final_review_hash,
    has_current_approval,
)

app = typer.Typer(
    help="Compile evidence-linked vertical technical explainers.", no_args_is_help=True
)
claims_app = typer.Typer(help="Generate evidence-linked candidate claims.")
script_app = typer.Typer(help="Generate and manage evidence-linked scripts.")
storyboard_app = typer.Typer(help="Generate allowlisted structured storyboards.")
cover_app = typer.Typer(help="Generate and select evidence-linked cover designs.")
audio_app = typer.Typer(help="Import user-recorded narration.")
captions_app = typer.Typer(help="Generate deterministic SRT, VTT, and burned-caption cues.")
style_app = typer.Typer(help="Configure reviewed visual delivery and pacing.")
app.add_typer(claims_app, name="claims")
app.add_typer(script_app, name="script")
app.add_typer(storyboard_app, name="storyboard")
app.add_typer(cover_app, name="cover")
app.add_typer(audio_app, name="audio")
app.add_typer(captions_app, name="captions")
app.add_typer(style_app, name="style")
console = Console()
PROVIDERS = {"fixture", "manual", "codex"}
ANGLES = {"surprising-result", "everyday-mechanism", "engineering-tradeoff"}
RIGHTS_STATUSES = {
    "original",
    "user-owned",
    "permissively-licensed",
    "citation-only",
    "unknown",
    "restricted",
}


@style_app.command("pacing")
def style_pacing(slug: str, profile: str) -> None:
    """Select measured, brisk, or high-retention visual pacing."""

    try:
        if profile not in PACING_PROFILES:
            raise ValueError("pacing must be measured, brisk, or high-retention")
        target = store(slug)
        previous = target.project().pacing
        set_pacing_profile(target, profile)
        if previous == profile:
            console.print(f"Pacing already set to {profile}")
        else:
            console.print(
                f"Pacing set to {profile}; storyboard and downstream review are now stale"
            )
    except (OSError, ValueError) as exc:
        fail(str(exc))


@style_app.command("safe-zone")
def style_safe_zone(
    slug: str,
    top: Annotated[float, typer.Option(min=0, max=0.25)] = 0.06,
    right: Annotated[float, typer.Option(min=0, max=0.25)] = 0.14,
    bottom: Annotated[float, typer.Option(min=0, max=0.25)] = 0.17,
    left: Annotated[float, typer.Option(min=0, max=0.25)] = 0.067,
) -> None:
    """Set resolution-independent content insets shared by TikTok and Reels."""

    try:
        target = store(slug)
        safe_zone = SafeZoneInsets(top=top, right=right, bottom=bottom, left=left)
        previous = target.project().safe_zone
        set_safe_zone(target, safe_zone)
        if previous == safe_zone:
            console.print("Safe zone already matches those insets")
        else:
            console.print("Safe zone updated; storyboard and downstream review are now stale")
    except (OSError, ValueError) as exc:
        fail(str(exc))


def projects_root() -> Path:
    return Path(os.getenv("TECHSHORT_PROJECTS_ROOT", "projects"))


def store(slug: str) -> ProjectStore:
    return ProjectStore(projects_root(), slug)


def fail(message: str) -> NoReturn:
    console.print(f"[red]Error:[/red] {message}")
    raise typer.Exit(1)


def _provider(value: str) -> str:
    normalized = value.lower()
    if normalized not in PROVIDERS:
        raise ValueError("provider must be fixture, manual, or codex")
    return normalized


def _package_version(name: str) -> str | None:
    package_path = Path("node_modules") / name / "package.json"
    if not package_path.is_file():
        return None
    data = json.loads(package_path.read_text(encoding="utf-8"))
    value = data.get("version")
    return str(value) if value else None


def _tool_version(executable: str | None, flag: str = "--version") -> str | None:
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, flag],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = (result.stdout or result.stderr).strip().splitlines()
    return value[0] if result.returncode == 0 and value else None


@app.command()
def doctor(
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Check the local toolchain, renderer, media tools, and optional providers."""

    node = shutil.which("node")
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    node_version = _tool_version(node)
    try:
        node_major = int(node_version.removeprefix("v").split(".", 1)[0]) if node_version else None
    except ValueError:
        node_major = None
    renderer_version = _package_version("@remotion/cli")
    codex = CodexCliProvider()
    browser_ready, browser_message = remotion_browser_readiness()
    codex_ready, codex_message = codex.readiness()
    configured_whisper = os.getenv("TECHSHORT_WHISPER_CLI")
    whisper = (
        shutil.which(configured_whisper)
        if configured_whisper
        else shutil.which("whisper-cli") or shutil.which("whisper")
    )
    configured_model = os.getenv("TECHSHORT_WHISPER_MODEL")
    whisper_model = Path(configured_model).expanduser() if configured_model else None
    transcription_ready = bool(whisper and whisper_model and whisper_model.is_file())
    if not whisper:
        transcription_message = "optional local whisper-cli/whisper not installed"
    elif whisper_model is None or not whisper_model.is_file():
        transcription_message = (
            f"{whisper}; set TECHSHORT_WHISPER_MODEL to an existing local model file"
        )
    else:
        transcription_message = f"{whisper}; local model {whisper_model.resolve()}"
    details: dict[str, dict[str, Any]] = {
        "python": {
            "required": True,
            "ok": (3, 11) <= sys.version_info[:2] < (3, 15),
            "value": f"{sys.version.split()[0]} at {sys.executable}",
        },
        "node": {
            "required": True,
            "ok": bool(node and node_major == 22),
            "value": f"{node_version} at {node}" if node_version else "not found or unreadable",
        },
        "npm": {"required": True, "ok": bool(npm), "value": npm or "not found"},
        "git": {
            "required": True,
            "ok": bool(shutil.which("git")),
            "value": shutil.which("git") or "not found",
        },
        "ffmpeg": {
            "required": True,
            "ok": bool(media_tool("ffmpeg")),
            "value": media_tool("ffmpeg") or "not found",
        },
        "ffprobe": {
            "required": True,
            "ok": bool(media_tool("ffprobe")),
            "value": media_tool("ffprobe") or "not found",
        },
        "renderer": {
            "required": True,
            "ok": bool(renderer_version and Path("renderer/src/index.ts").is_file()),
            "value": f"Remotion {renderer_version}" if renderer_version else "not installed",
        },
        "browser": {
            "required": True,
            "ok": browser_ready,
            "value": browser_message,
        },
        "codex": {
            "required": False,
            "ok": codex_ready,
            "value": codex_message,
        },
        "local_transcription": {
            "required": False,
            "ok": transcription_ready,
            "value": transcription_message,
        },
    }
    overall = all(row["ok"] for row in details.values() if row["required"])
    payload = {"techshort": __version__, "ok": overall, "dependencies": details}
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
    else:
        table = Table(title=f"techshort {__version__} doctor")
        table.add_column("Dependency")
        table.add_column("Status")
        table.add_column("Location / next step")
        for name, row in details.items():
            status = "OK" if row["ok"] else "MISSING" if row["required"] else "OPTIONAL"
            table.add_row(name, status, str(row["value"]))
        console.print(table)
    if not overall:
        raise typer.Exit(1)


@app.command("init")
def init_project(slug: str, title: Annotated[str | None, typer.Option()] = None) -> None:
    """Create or safely resume a project directory."""

    try:
        manifest = store(slug).initialize(title or slug.replace("-", " ").title())
        console.print(f"Initialized [bold]{manifest.slug}[/bold] at {store(slug).root}")
    except (OSError, ValueError) as exc:
        fail(str(exc))


@app.command()
def ingest(slug: str, source: Path) -> None:
    """Safely ingest a local text PDF, Markdown file, or plain-text source."""

    try:
        document = ingest_source(store(slug), source)
        console.print(
            f"Ingested {document.original_filename} as {document.source_id} "
            f"({document.page_or_section_count} locations)"
        )
        for warning in document.extraction_warnings:
            console.print(f"[yellow]Warning:[/yellow] {warning}")
    except (OSError, ValueError) as exc:
        fail(str(exc))


@claims_app.command("generate")
def claims_generate(
    slug: str,
    provider: Annotated[str, typer.Option()] = "fixture",
    source_id: Annotated[str | None, typer.Option("--source-id")] = None,
    manual_result: Annotated[
        Path | None,
        typer.Option(
            "--manual-result",
            help="Project-relative returned JSON for a previously exported manual packet.",
        ),
    ] = None,
) -> None:
    """Generate candidates, or export/import a strict manual prompt packet."""

    try:
        selected = _provider(provider)
        outcome = generate_claims(
            store(slug),
            selected,  # type: ignore[arg-type]
            source_id=source_id,
            manual_result=manual_result,
        )
        if outcome.requires_manual_import:
            console.print(f"Manual claims packet ready: {outcome.prompt_packet}")
            console.print(
                "Return schema-valid JSON, then rerun with --manual-result <project path>."
            )
            return
        claims = outcome.require_artifact()
        critique = load_model(store(slug).path("claims/critique.json"), ClaimCritiqueReport)
        console.print(
            f"Generated {len(claims.claims)} {selected} claims; "
            f"independent critique found {len(critique.issues)} candidate issue(s); "
            f"run `techshort review {slug} --gate claims`"
        )
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        fail(str(exc))


@script_app.command("generate")
def script_generate(
    slug: str,
    provider: Annotated[str, typer.Option()] = "fixture",
    angle: Annotated[
        str | None,
        typer.Option(help="Optional assertion matching the already-selected explainer angle"),
    ] = None,
    manual_result: Annotated[Path | None, typer.Option("--manual-result")] = None,
) -> None:
    """Generate a clause-level script after explicitly selecting one of three angles."""

    try:
        selected = _provider(provider)
        if angle is not None and angle not in ANGLES:
            raise ValueError(
                "angle must be surprising-result, everyday-mechanism, or engineering-tradeoff"
            )
        outcome = generate_script(
            store(slug),
            selected,  # type: ignore[arg-type]
            angle=angle,  # type: ignore[arg-type]
            manual_result=manual_result,
        )
        if outcome.requires_manual_import:
            console.print(f"Manual script packet ready: {outcome.prompt_packet}")
            console.print(
                "Return schema-valid JSON, then rerun with --manual-result <project path>."
            )
            return
        script = outcome.require_artifact()
        words = sum(len(segment.text.split()) for segment in script.segments)
        console.print(f"Generated {len(script.segments)} segments ({words} spoken words)")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        fail(str(exc))


@script_app.command("angles")
def script_angles(
    slug: str,
    provider: Annotated[str, typer.Option()] = "fixture",
    manual_result: Annotated[Path | None, typer.Option("--manual-result")] = None,
) -> None:
    """Generate the three claim-linked angle candidates without selecting one."""

    try:
        selected = _provider(provider)
        outcome = generate_angles(
            store(slug),
            selected,  # type: ignore[arg-type]
            manual_result=manual_result,
        )
        if outcome.requires_manual_import:
            console.print(f"Manual angles packet ready: {outcome.prompt_packet}")
            console.print(
                "Return schema-valid JSON, then rerun with --manual-result <project path>."
            )
            return
        angles = outcome.require_artifact()
        console.print(f"Generated {len(angles.candidates)} current angle candidates")
        for candidate in angles.candidates:
            console.print(f"- {candidate.angle}: {candidate.title}")
        console.print(f"Select one with `techshort script select-angle {slug} <angle>`")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        fail(str(exc))


@script_app.command("select-angle")
def script_select_angle(slug: str, angle: str) -> None:
    """Persist an explicit selection from the current angle candidates."""

    try:
        if angle not in ANGLES:
            raise ValueError(
                "angle must be surprising-result, everyday-mechanism, or engineering-tradeoff"
            )
        selection = select_angle(store(slug), angle)  # type: ignore[arg-type]
        console.print(
            f"Selected {selection.selected_angle} from {selection.angles_version_id} "
            f"as {selection.selection_id}"
        )
    except (OSError, ValueError) as exc:
        fail(str(exc))


@storyboard_app.command("generate")
def storyboard_generate(
    slug: str,
    provider: Annotated[str, typer.Option()] = "fixture",
    manual_result: Annotated[Path | None, typer.Option("--manual-result")] = None,
) -> None:
    """Generate an allowlisted, non-executable structured storyboard."""

    try:
        selected = _provider(provider)
        outcome = generate_storyboard(
            store(slug),
            selected,  # type: ignore[arg-type]
            manual_result=manual_result,
        )
        if outcome.requires_manual_import:
            console.print(f"Manual storyboard packet ready: {outcome.prompt_packet}")
            console.print(
                "Return schema-valid JSON, then rerun with --manual-result <project path>."
            )
            return
        storyboard = outcome.require_artifact()
        console.print(f"Generated {len(storyboard.scenes)} typed scenes and registered font rights")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        fail(str(exc))


@cover_app.command("generate")
def cover_generate(slug: str) -> None:
    """Generate three deterministic cover candidates from the selected angle."""

    try:
        covers = generate_fixture_covers(store(slug))
        console.print(f"Generated {len(covers.candidates)} evidence-linked cover candidates")
        for candidate in covers.candidates:
            console.print(
                f"- {candidate.candidate_id}: {candidate.headline} "
                f"({candidate.layout}, {candidate.palette})"
            )
        console.print(f"Select one with `techshort cover select {slug} <candidate-id>`")
    except (OSError, ValueError) as exc:
        fail(str(exc))


@cover_app.command("select")
def cover_select(slug: str, candidate_id: str) -> None:
    """Persist the cover candidate reviewed by the user."""

    try:
        selection = select_cover(store(slug), candidate_id)
        console.print(f"Selected {selection.selected_candidate_id} as {selection.selection_id}")
    except (OSError, ValueError) as exc:
        fail(str(exc))


@app.command()
def review(
    slug: str,
    gate: Annotated[str, typer.Option(help="claims, script, storyboard, rights, or final")],
    reviewer: Annotated[str, typer.Option()] = "local-reviewer",
) -> None:
    """Explicitly approve one human review gate from the local CLI."""

    try:
        target = store(slug)
        if gate == "claims":
            approve_claims(target, reviewer)
        elif gate == "script":
            approve_script(target, reviewer)
        elif gate == "storyboard":
            approve_storyboard(target, reviewer)
        elif gate == "rights":
            approve_rights(target, reviewer)
        elif gate == "final":
            approve_final(target, reviewer)
        else:
            raise ValueError("gate must be claims, script, storyboard, rights, or final")
        console.print(f"Approved {gate} gate as {reviewer}")
    except (OSError, ValueError) as exc:
        fail(str(exc))


@audio_app.command("import")
def audio_import(
    slug: str,
    audio_file: Path,
    rights_status: Annotated[
        str,
        typer.Option(
            "--rights-status",
            help="Use user-owned only when you own the recording; unknown blocks export.",
        ),
    ] = "unknown",
    creator: Annotated[str | None, typer.Option("--creator")] = None,
    license_name: Annotated[str | None, typer.Option("--license")] = None,
    source_url: Annotated[str | None, typer.Option("--source-url")] = None,
    required_attribution: Annotated[str | None, typer.Option("--required-attribution")] = None,
) -> None:
    """Import narration with an explicit rights classification."""

    try:
        if rights_status not in RIGHTS_STATUSES:
            raise ValueError("invalid rights status")
        path = import_audio(
            store(slug),
            audio_file,
            rights_status,
            creator=creator,
            license_name=license_name,
            source_url=source_url,
            required_attribution=required_attribution,
        )
        console.print(f"Imported narration to {path}")
        if rights_status in {"unknown", "restricted", "citation-only"}:
            console.print(
                "[yellow]Rights review will block embedding until metadata is corrected.[/yellow]"
            )
    except (OSError, ValueError) as exc:
        fail(str(exc))


@audio_app.command("mode")
def audio_mode(slug: str, mode: str) -> None:
    """Explicitly require narration or approve a silent production workflow."""

    try:
        if mode not in {"narrated", "silent-reviewed"}:
            raise ValueError("mode must be narrated or silent-reviewed")
        set_narration_mode(store(slug), mode)  # type: ignore[arg-type]
        console.print(f"Narration mode set to {mode}")
    except (OSError, ValueError) as exc:
        fail(str(exc))


@audio_app.command("import-transcript")
def audio_import_transcript(slug: str, transcript_file: Path) -> None:
    """Import a UTF-8 transcript bound to the exact active narration bytes."""

    try:
        path = import_transcript(store(slug), transcript_file)
        console.print(f"Imported narration transcript to {path}")
    except (OSError, ValueError) as exc:
        fail(str(exc))


def _generate_captions(target: ProjectStore) -> tuple[Path, Path]:
    script = load_model(target.path("script/script.json"), ScriptManifest)
    narration = active_audio(target)
    narration_duration = probe_duration(narration) if narration else None
    cues = cues_from_script(script, target_duration=narration_duration)
    old_hashes = {
        path.name: sha256_file(path)
        for path in (target.path("captions/captions.srt"), target.path("captions/captions.vtt"))
        if path.is_file()
    }
    srt, vtt = write_caption_files(target.path("captions"), cues)
    new_hashes = {srt.name: sha256_file(srt), vtt.name: sha256_file(vtt)}
    project = target.project()
    project.active_versions["captions"] = stable_hash(new_hashes)
    target.save_project(project)
    if old_hashes != new_hashes:
        target.invalidate_from("final", "captions regenerated")
    return srt, vtt


@captions_app.command("generate")
def captions_generate(slug: str) -> None:
    try:
        srt, vtt = _generate_captions(store(slug))
        console.print(f"Generated matching caption sidecars: {srt} and {vtt}")
    except (OSError, ValueError) as exc:
        fail(str(exc))


@app.command()
def preview(slug: str) -> None:
    """Render a 360x640 review copy with a visible UNREVIEWED watermark."""

    try:
        path = render_video(store(slug), preview=True)
        console.print(f"Rendered watermarked preview: {path}")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        fail(str(exc))


@app.command()
def render(slug: str) -> None:
    """Render and hard-QA an unwatermarked 1080x1920 final after final approval."""

    target = store(slug)
    try:
        project = target.project()
        if project.approvals.final != ReviewStatus.APPROVED:
            raise ValueError("final render is blocked until the final review gate is approved")
        if not has_current_approval(target, "final", project.project_id):
            raise ValueError("final approval no longer matches the reviewed preview")
        if project.dependency_hashes.get("final_approval") != final_review_hash(target):
            raise ValueError("final approval hash is stale")
        path = render_video(target, preview=False)
        report = run_qa(target, path, destination="renders/final/qa-report.json")
        if not report.passed:
            raise ValueError(f"final render failed QA: {'; '.join(report.export_blockers)}")
        console.print(f"Rendered and verified final: {path}")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        fail(str(exc))


@app.command()
def qa(
    slug: str,
    final: Annotated[
        bool, typer.Option("--final", help="Check the full-resolution final.")
    ] = False,
) -> None:
    try:
        target = store(slug)
        path = target.path("renders/final/final.mp4" if final else "renders/previews/preview.mp4")
        report = run_qa(
            target,
            path,
            destination="renders/final/qa-report.json"
            if final
            else "renders/previews/qa-report.json",
        )
        console.print(
            f"QA {'passed' if report.passed else 'blocked'}: {len(report.export_blockers)} blocker(s)"
        )
        for blocker in report.export_blockers:
            console.print(f"[red]- {blocker}[/red]")
        if not report.passed:
            raise typer.Exit(1)
    except (OSError, ValueError) as exc:
        fail(str(exc))


@app.command("evidence-page")
def evidence_page(slug: str) -> None:
    try:
        target = store(slug)
        path = target.path("renders/previews/evidence.html")
        generate_evidence_page(target, path)
        console.print(f"Generated cited companion page and ledger: {path}")
    except (OSError, ValueError) as exc:
        fail(str(exc))


@app.command("export")
def export_command(slug: str) -> None:
    try:
        path = export_project(store(slug))
        console.print(f"Export complete: {path}")
    except (OSError, ValueError) as exc:
        fail(str(exc))


def _status_blockers(target: ProjectStore) -> list[str]:
    project = target.project()
    blockers = [
        f"{gate} gate: {getattr(project.approvals, gate)}"
        for gate in ("claims", "script", "storyboard", "rights", "final")
        if getattr(project.approvals, gate) != ReviewStatus.APPROVED
    ]
    blockers.extend(f"stale artifact: {item}" for item in project.stale_artifacts)
    preview_qa = target.path("renders/previews/qa-report.json")
    if not preview_qa.is_file():
        blockers.append("preview QA report is missing")
    else:
        try:
            report = load_model(preview_qa, QAReport)
            if not report.passed:
                blockers.extend(f"QA: {item}" for item in report.export_blockers)
        except ValueError:
            blockers.append("preview QA report is invalid")
    if project.approvals.final == ReviewStatus.APPROVED:
        try:
            final_is_current = has_current_approval(target, "final", project.project_id)
        except (OSError, ValueError):
            final_is_current = False
        if not final_is_current:
            blockers.append("final approval record is stale")
        final_video = target.path("renders/final/final.mp4")
        final_qa = target.path("renders/final/qa-report.json")
        if not final_video.is_file():
            blockers.append("final render is missing")
        elif not final_qa.is_file():
            blockers.append("final QA report is missing")
        else:
            try:
                final_report = load_model(final_qa, QAReport)
                if not final_report.passed:
                    blockers.extend(f"final QA: {item}" for item in final_report.export_blockers)
                if final_report.media_hash != sha256_file(final_video):
                    blockers.append("final QA media hash is stale")
            except (OSError, ValueError):
                blockers.append("final QA report is invalid")
    return list(dict.fromkeys(blockers))


@app.command()
def status(slug: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    try:
        target = store(slug)
        project = target.project()
        blockers = _status_blockers(target)
        data = {
            "project": project.model_dump(mode="json"),
            "export_ready": not blockers,
            "export_blockers": blockers,
        }
        if json_output:
            typer.echo(json.dumps(data, indent=2))
        else:
            console.print(f"[bold]{project.title}[/bold] — {project.status}")
            console.print("Export ready" if not blockers else "\n".join(f"- {x}" for x in blockers))
    except (OSError, ValueError) as exc:
        fail(str(exc))


@app.command()
def demo(
    slug: Annotated[str, typer.Argument()] = "rolling-shutter",
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Confirm regeneration and all five fixture review gates."),
    ] = False,
) -> None:
    """Run the complete deterministic offline rolling-shutter workflow."""

    if not yes:
        fail("demo requires --yes because it records human-gate fixture approvals")
    target = store(slug)
    reviewer = "demo-reviewer"
    try:
        target.initialize("Rolling-Shutter Distortion")
        set_narration_mode(target, "silent-reviewed")
        ingest_source(target, Path("examples/rolling-shutter/rolling-shutter.md"))
        generate_claims(target, "fixture").require_artifact()
        approve_claims(target, reviewer)
        generate_angles(target, "fixture").require_artifact()
        select_angle(target, "everyday-mechanism")
        generate_script(target, "fixture", angle="everyday-mechanism").require_artifact()
        approve_script(target, reviewer)
        generate_storyboard(target, "fixture").require_artifact()
        generate_fixture_covers(target)
        select_cover(target, "cover-scanline")
        approve_storyboard(target, reviewer)
        approve_rights(target, reviewer)
        _generate_captions(target)
        preview_path = render_video(target, preview=True)
        preview_report = run_qa(target, preview_path)
        if not preview_report.passed:
            raise ValueError(f"preview QA failed: {'; '.join(preview_report.export_blockers)}")
        generate_evidence_page(target, target.path("renders/previews/evidence.html"))
        approve_final(target, reviewer)
        final_path = render_video(target, preview=False)
        final_report = run_qa(target, final_path, destination="renders/final/qa-report.json")
        if not final_report.passed:
            raise ValueError(f"final QA failed: {'; '.join(final_report.export_blockers)}")
        exported = export_project(target)
        console.print(f"Complete deterministic demo exported to [bold]{exported}[/bold]")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        fail(str(exc))


if __name__ == "__main__":
    app()
