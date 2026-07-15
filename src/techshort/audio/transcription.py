from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from techshort.audio.service import (
    MAX_TRANSCRIPT_BYTES,
    _validate_transcript_text,
    active_transcript,
)
from techshort.domain.storage import ProjectStore

HELP_TIMEOUT_SECONDS = 10
TRANSCRIPTION_TIMEOUT_SECONDS = 600
MAX_TOOL_LOG_BYTES = 64 * 1024


@dataclass(frozen=True)
class TranscriptionAttempt:
    text: str | None
    source: str | None
    unavailable_reason: str | None


@dataclass(frozen=True)
class _ProcessResult:
    returncode: int
    stdout: str
    stderr: str


def _bounded_run(arguments: list[str], *, timeout: int) -> _ProcessResult:
    """Run an argument array while keeping captured tool diagnostics bounded."""
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        result = subprocess.run(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            timeout=timeout,
            check=False,
        )
        stdout.seek(0)
        stderr.seek(0)
        stdout_bytes = stdout.read(MAX_TOOL_LOG_BYTES + 1)
        stderr_bytes = stderr.read(MAX_TOOL_LOG_BYTES + 1)
    if len(stdout_bytes) > MAX_TOOL_LOG_BYTES or len(stderr_bytes) > MAX_TOOL_LOG_BYTES:
        raise ValueError("local transcription tool produced excessive diagnostic output")
    return _ProcessResult(
        returncode=result.returncode,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
    )


def _configured_executable(environment: Mapping[str, str]) -> str | None:
    configured = environment.get("TECHSHORT_WHISPER_CLI")
    if configured:
        configured_path = Path(configured).expanduser()
        if configured_path.is_file():
            return str(configured_path.resolve())
        return shutil.which(configured)
    return shutil.which("whisper-cli") or shutil.which("whisper")


def _configured_model(environment: Mapping[str, str]) -> Path | None:
    configured = environment.get("TECHSHORT_WHISPER_MODEL")
    if not configured:
        return None
    model = Path(configured).expanduser()
    return model.resolve() if model.is_file() else None


def _read_transcript_output(path: Path) -> str:
    if not path.is_file():
        raise ValueError("local transcription tool did not produce its declared text output")
    if path.stat().st_size > MAX_TRANSCRIPT_BYTES:
        raise ValueError("local transcription output exceeds the 128 KiB safety limit")
    try:
        return _validate_transcript_text(path.read_text(encoding="utf-8")).strip()
    except UnicodeDecodeError as exc:
        raise ValueError("local transcription output is not valid UTF-8") from exc


def transcribe_with_local_whisper(
    narration: Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> TranscriptionAttempt:
    """Transcribe with an explicitly local model and a help-verified Whisper CLI.

    Named models are intentionally rejected because common Whisper CLIs may
    download them. Only an existing model file supplied through
    ``TECHSHORT_WHISPER_MODEL`` is accepted.
    """
    environment = os.environ if environment is None else environment
    executable = _configured_executable(environment)
    if not executable:
        return TranscriptionAttempt(None, None, "no supported local Whisper CLI is installed")
    model = _configured_model(environment)
    if model is None:
        return TranscriptionAttempt(
            None,
            None,
            "TECHSHORT_WHISPER_MODEL does not name an existing local model file",
        )
    try:
        help_result = _bounded_run([executable, "--help"], timeout=HELP_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return TranscriptionAttempt(None, None, f"local Whisper CLI help check failed: {exc}")
    help_text = f"{help_result.stdout}\n{help_result.stderr}"

    try:
        with tempfile.TemporaryDirectory(prefix="techshort-whisper-") as temporary:
            directory = Path(temporary)
            if all(
                option in help_text
                for option in ("--model", "--file", "--output-txt", "--output-file")
            ):
                output_prefix = directory / "narration"
                arguments = [
                    executable,
                    "--model",
                    str(model),
                    "--file",
                    str(narration),
                    "--output-txt",
                    "--output-file",
                    str(output_prefix),
                ]
                output = output_prefix.with_suffix(".txt")
                source = "local-whisper.cpp"
            elif all(
                option in help_text for option in ("--model", "--output_dir", "--output_format")
            ):
                arguments = [
                    executable,
                    str(narration),
                    "--model",
                    str(model),
                    "--output_dir",
                    str(directory),
                    "--output_format",
                    "txt",
                ]
                output = directory / f"{narration.stem}.txt"
                source = "local-openai-whisper"
            else:
                return TranscriptionAttempt(
                    None,
                    None,
                    "installed Whisper CLI help does not advertise a supported safe interface",
                )
            result = _bounded_run(arguments, timeout=TRANSCRIPTION_TIMEOUT_SECONDS)
            if result.returncode != 0:
                return TranscriptionAttempt(
                    None,
                    None,
                    f"local Whisper CLI exited with status {result.returncode}",
                )
            return TranscriptionAttempt(_read_transcript_output(output), source, None)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return TranscriptionAttempt(None, None, f"local Whisper transcription failed: {exc}")


def resolve_narration_transcript(
    store: ProjectStore,
    narration: Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> TranscriptionAttempt:
    """Prefer the audio-hash-bound project sidecar, then optional local ASR."""
    sidecar = active_transcript(store)
    if sidecar is not None:
        text, path = sidecar
        return TranscriptionAttempt(
            text,
            f"project sidecar {path.relative_to(store.root).as_posix()}",
            None,
        )
    return transcribe_with_local_whisper(narration, environment=environment)
