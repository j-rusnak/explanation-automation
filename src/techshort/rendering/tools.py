from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def media_tool(name: str) -> str | None:
    discovered = shutil.which(name)
    if discovered:
        return discovered
    suffix = ".exe" if __import__("os").name == "nt" else ""
    bundled = Path("node_modules") / "@remotion" / "compositor-win32-x64-msvc" / f"{name}{suffix}"
    return str(bundled.resolve()) if bundled.exists() else None


def find_remotion_browser(repository_root: Path | None = None) -> Path | None:
    """Find a complete Remotion-managed browser without scanning all dependencies."""

    root = (repository_root or Path.cwd()).resolve()
    cache = root / "node_modules" / ".remotion" / "chrome-headless-shell"
    if not cache.is_dir():
        return None
    names = ("chrome-headless-shell.exe", "chrome-headless-shell")
    for name in names:
        for candidate in cache.rglob(name):
            try:
                if candidate.is_file() and candidate.stat().st_size > 0:
                    return candidate.resolve()
            except OSError:
                continue
    return None


def remotion_browser_readiness(
    repository_root: Path | None = None,
    *,
    timeout_seconds: int = 10,
) -> tuple[bool, str]:
    """Verify the cached browser is present and can start as a local executable."""

    browser = find_remotion_browser(repository_root)
    if browser is None:
        return (
            False,
            "Remotion browser cache is missing; run `npm.cmd exec remotion -- browser ensure`.",
        )
    try:
        result = subprocess.run(
            [str(browser), "--version"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Remotion browser cache could not start: {type(exc).__name__}"
    output = (result.stdout or result.stderr).strip().splitlines()
    if result.returncode != 0 or not output:
        return (
            False,
            f"Remotion browser cache failed its version probe (exit {result.returncode}).",
        )
    return True, f"{output[0][:160]} at {browser}"
