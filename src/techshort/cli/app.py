from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from techshort import __version__
from techshort.alignment import as_srt, as_vtt, cues_from_script
from techshort.audio import import_audio
from techshort.domain.models import ScriptManifest
from techshort.domain.storage import ProjectStore, load_model
from techshort.export import export_project, generate_evidence_page
from techshort.generation import fixture_claims, fixture_script, fixture_storyboard
from techshort.ingestion import ingest_source
from techshort.qa import run_qa
from techshort.rendering import render_video
from techshort.review import (
    approve_claims,
    approve_final,
    approve_rights,
    approve_script,
    approve_storyboard,
)

app = typer.Typer(
    help="Compile evidence-linked vertical technical explainers.", no_args_is_help=True
)
claims_app = typer.Typer(help="Generate evidence-linked candidate claims.")
script_app = typer.Typer(help="Generate and manage scripts.")
storyboard_app = typer.Typer(help="Generate structured storyboards.")
audio_app = typer.Typer(help="Import user-recorded narration.")
captions_app = typer.Typer(help="Generate deterministic captions.")
app.add_typer(claims_app, name="claims")
app.add_typer(script_app, name="script")
app.add_typer(storyboard_app, name="storyboard")
app.add_typer(audio_app, name="audio")
app.add_typer(captions_app, name="captions")
console = Console()


def projects_root() -> Path:
    return Path(os.getenv("TECHSHORT_PROJECTS_ROOT", "projects"))


def store(slug: str) -> ProjectStore:
    return ProjectStore(projects_root(), slug)


def fail(message: str) -> None:
    console.print(f"[red]Error:[/red] {message}")
    raise typer.Exit(1)


@app.command()
def doctor(
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Check the local toolchain and optional providers."""
    tools = {
        "python": sys.executable,
        "node": shutil.which("node"),
        "npm": shutil.which("npm.cmd") or shutil.which("npm"),
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "codex": shutil.which("codex") or shutil.which("codex.exe"),
        "git": shutil.which("git"),
    }
    tools["renderer"] = str(Path("renderer/package.json").exists())
    tools["local_transcription"] = shutil.which("whisper") or shutil.which("whisper.cpp")
    if json_output:
        typer.echo(json.dumps(tools, indent=2))
        return
    table = Table(title=f"techshort {__version__} doctor")
    table.add_column("Dependency")
    table.add_column("Status")
    table.add_column("Location / next step")
    for name, value in tools.items():
        present = bool(value) and value != "False"
        required = name in {"python", "node", "npm", "git", "renderer"}
        status = "OK" if present else "MISSING" if required else "OPTIONAL"
        table.add_row(name, status, str(value or "not found"))
    console.print(table)


@app.command("init")
def init_project(slug: str, title: Annotated[str | None, typer.Option()] = None) -> None:
    """Create an idempotent project directory."""
    try:
        manifest = store(slug).initialize(title or slug.replace("-", " ").title())
        console.print(f"Initialized [bold]{manifest.slug}[/bold] at {store(slug).root}")
    except ValueError as exc:
        fail(str(exc))


@app.command()
def ingest(slug: str, source: Path) -> None:
    """Safely ingest a local PDF, Markdown, or text source."""
    try:
        document = ingest_source(store(slug), source)
        console.print(
            f"Ingested {document.original_filename} as {document.source_id} ({document.page_or_section_count} locations)"
        )
        for warning in document.extraction_warnings:
            console.print(f"[yellow]Warning:[/yellow] {warning}")
    except (OSError, ValueError) as exc:
        fail(str(exc))


@claims_app.command("generate")
def generate_claims(slug: str, provider: Annotated[str, typer.Option()] = "fixture") -> None:
    if provider != "fixture":
        fail(
            "V1 checkpoint currently supports --provider fixture; manual/codex packets follow the deterministic slice"
        )
    try:
        claims = fixture_claims(store(slug))
        console.print(
            f"Generated {len(claims.claims)} claims; run `techshort review {slug} --gate claims`"
        )
    except (OSError, ValueError) as exc:
        fail(str(exc))


@script_app.command("generate")
def generate_script(
    slug: str,
    provider: Annotated[str, typer.Option()] = "fixture",
    angle: Annotated[str, typer.Option()] = "everyday-mechanism",
) -> None:
    if provider != "fixture":
        fail("Use --provider fixture for this offline vertical slice")
    try:
        script = fixture_script(store(slug), angle)
        words = sum(len(segment.text.split()) for segment in script.segments)
        console.print(f"Generated {len(script.segments)} segments ({words} words)")
    except (OSError, ValueError) as exc:
        fail(str(exc))


@storyboard_app.command("generate")
def generate_storyboard(slug: str, provider: Annotated[str, typer.Option()] = "fixture") -> None:
    if provider != "fixture":
        fail("Use --provider fixture for this offline vertical slice")
    try:
        storyboard = fixture_storyboard(store(slug))
        console.print(f"Generated {len(storyboard.scenes)} typed scenes")
    except (OSError, ValueError) as exc:
        fail(str(exc))


@app.command()
def review(
    slug: str,
    gate: Annotated[str, typer.Option(help="claims, script, storyboard, rights, or final")],
    reviewer: Annotated[str, typer.Option()] = "local-reviewer",
) -> None:
    actions = {
        "claims": approve_claims,
        "script": approve_script,
        "storyboard": approve_storyboard,
        "rights": approve_rights,
        "final": approve_final,
    }
    if gate not in actions:
        fail("gate must be claims, script, storyboard, rights, or final")
    try:
        actions[gate](store(slug), reviewer)
        console.print(f"Approved {gate} gate as {reviewer}")
    except (OSError, ValueError) as exc:
        fail(str(exc))


@audio_app.command("import")
def audio_import(slug: str, audio_file: Path) -> None:
    try:
        path = import_audio(store(slug), audio_file)
        console.print(f"Imported narration to {path}")
    except (OSError, ValueError) as exc:
        fail(str(exc))


@captions_app.command("generate")
def captions_generate(slug: str) -> None:
    try:
        target = store(slug)
        script = load_model(target.path("script/script.json"), ScriptManifest)
        cues = cues_from_script(script)
        target.path("captions").mkdir(exist_ok=True)
        target.path("captions/captions.srt").write_text(as_srt(cues), encoding="utf-8")
        target.path("captions/captions.vtt").write_text(as_vtt(cues), encoding="utf-8")
        console.print(f"Generated {len(cues)} cues in SRT and VTT")
    except (OSError, ValueError) as exc:
        fail(str(exc))


@app.command()
def preview(slug: str) -> None:
    """Render a visibly watermarked review preview."""
    try:
        path = render_video(store(slug), preview=True)
        console.print(f"Rendered watermarked preview: {path}")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        fail(str(exc))


@app.command()
def render(slug: str) -> None:
    """Render an unwatermarked final only after final approval."""
    target = store(slug)
    if target.project().approvals.final != "approved":
        fail("final render is blocked until the final review gate is approved")
    try:
        path = render_video(target, preview=False)
        console.print(f"Rendered final: {path}")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        fail(str(exc))


@app.command()
def qa(slug: str) -> None:
    try:
        target = store(slug)
        preview_path = target.path("renders/previews/preview.mp4")
        report = run_qa(target, preview_path if preview_path.exists() else None)
        console.print(
            f"QA {'passed' if report.passed else 'blocked'}: {len(report.export_blockers)} blocker(s)"
        )
        if report.export_blockers:
            for blocker in report.export_blockers:
                console.print(f"[red]- {blocker}[/red]")
            raise typer.Exit(1)
    except (OSError, ValueError) as exc:
        fail(str(exc))


@app.command()
def evidence_page(slug: str) -> None:
    target = store(slug)
    path = target.path("renders/previews/evidence.html")
    generate_evidence_page(target, path)
    console.print(f"Generated {path}")


@app.command("export")
def export_command(slug: str) -> None:
    try:
        path = export_project(store(slug))
        console.print(f"Export complete: {path}")
    except (OSError, ValueError) as exc:
        fail(str(exc))


@app.command()
def status(slug: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    try:
        project = store(slug).project()
        blockers = [
            f"{gate} gate: {getattr(project.approvals, gate)}"
            for gate in ("claims", "script", "storyboard", "rights", "final")
            if getattr(project.approvals, gate) != "approved"
        ]
        data = {"project": project.model_dump(mode="json"), "export_blockers": blockers}
        if json_output:
            typer.echo(json.dumps(data, indent=2))
        else:
            console.print(f"[bold]{project.title}[/bold] — {project.status}")
            console.print(
                "Export ready" if not blockers else "\n".join(f"- {item}" for item in blockers)
            )
    except (OSError, ValueError) as exc:
        fail(str(exc))


if __name__ == "__main__":
    app()
