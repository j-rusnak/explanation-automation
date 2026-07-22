from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from techshort.rendering.tools import find_remotion_browser, remotion_browser_readiness


def test_remotion_browser_readiness_rejects_missing_cache(tmp_path: Path) -> None:
    assert find_remotion_browser(tmp_path) is None
    ready, message = remotion_browser_readiness(tmp_path)
    assert not ready
    assert "browser ensure" in message


def test_remotion_browser_readiness_probes_cached_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser = (
        tmp_path
        / "node_modules/.remotion/chrome-headless-shell/win64/shell/chrome-headless-shell.exe"
    )
    browser.parent.mkdir(parents=True)
    browser.write_bytes(b"not-empty")
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="HeadlessChrome 137.0\n", stderr="")

    monkeypatch.setattr("techshort.rendering.tools.subprocess.run", fake_run)
    ready, message = remotion_browser_readiness(tmp_path)
    assert ready
    assert "HeadlessChrome 137.0" in message
    assert calls == [[str(browser.resolve()), "--version"]]


def test_remotion_browser_readiness_rejects_broken_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser = (
        tmp_path
        / "node_modules/.remotion/chrome-headless-shell/win64/shell/chrome-headless-shell.exe"
    )
    browser.parent.mkdir(parents=True)
    browser.write_bytes(b"not-empty")

    def fake_run(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 7, stdout="", stderr="broken")

    monkeypatch.setattr("techshort.rendering.tools.subprocess.run", fake_run)
    ready, message = remotion_browser_readiness(tmp_path)
    assert not ready
    assert "exit 7" in message
