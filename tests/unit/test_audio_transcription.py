from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from techshort.audio import transcribe_with_local_whisper
from techshort.audio import transcription as transcription_module


def test_local_whisper_requires_existing_local_model_without_invocation(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        transcription_module,
        "_configured_executable",
        lambda _environment: "whisper-cli",
    )
    called = False

    def unexpected_run(_arguments: list[str], *, timeout: int) -> Any:
        nonlocal called
        called = True
        raise AssertionError(timeout)

    monkeypatch.setattr(transcription_module, "_bounded_run", unexpected_run)

    attempt = transcribe_with_local_whisper(
        tmp_path / "narration.wav",
        environment={},
    )

    assert attempt.text is None
    assert "existing local model" in (attempt.unavailable_reason or "")
    assert not called


def test_local_whisper_uses_help_verified_argument_array(monkeypatch: Any, tmp_path: Path) -> None:
    narration = tmp_path / "narration.wav"
    narration.write_bytes(b"fixture")
    model = tmp_path / "model.bin"
    model.write_bytes(b"local model")
    monkeypatch.setattr(
        transcription_module,
        "_configured_executable",
        lambda _environment: "whisper-cli",
    )
    monkeypatch.setattr(
        transcription_module,
        "_configured_model",
        lambda _environment: model,
    )
    invocations: list[list[str]] = []

    def fake_run(arguments: list[str], *, timeout: int) -> Any:
        invocations.append(arguments)
        if arguments[-1] == "--help":
            return transcription_module._ProcessResult(
                0,
                "--model --file --output-txt --output-file",
                "",
            )
        assert timeout == transcription_module.TRANSCRIPTION_TIMEOUT_SECONDS
        output_prefix = Path(arguments[arguments.index("--output-file") + 1])
        output_prefix.with_suffix(".txt").write_text(
            "Narration matches the approved script.", encoding="utf-8"
        )
        return transcription_module._ProcessResult(0, "", "")

    monkeypatch.setattr(transcription_module, "_bounded_run", fake_run)

    attempt = transcribe_with_local_whisper(narration, environment={})

    assert attempt.text == "Narration matches the approved script."
    assert attempt.source == "local-whisper.cpp"
    assert len(invocations) == 2
    command = invocations[1]
    assert isinstance(command, list)
    assert command[:2] == ["whisper-cli", "--model"]
    assert str(model) in command
    assert str(narration) in command


def test_bounded_runner_never_uses_a_shell(monkeypatch: Any) -> None:
    observed: dict[str, Any] = {}

    def fake_run(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        observed["arguments"] = arguments
        observed.update(kwargs)
        kwargs["stdout"].write(b"help")
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(transcription_module.subprocess, "run", fake_run)

    result = transcription_module._bounded_run(["whisper-cli", "--help"], timeout=3)

    assert result.stdout == "help"
    assert observed["arguments"] == ["whisper-cli", "--help"]
    assert "shell" not in observed
    assert observed["timeout"] == 3
