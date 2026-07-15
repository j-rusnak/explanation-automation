from __future__ import annotations

import shutil
from pathlib import Path


def media_tool(name: str) -> str | None:
    discovered = shutil.which(name)
    if discovered:
        return discovered
    suffix = ".exe" if __import__("os").name == "nt" else ""
    bundled = Path("node_modules") / "@remotion" / "compositor-win32-x64-msvc" / f"{name}{suffix}"
    return str(bundled.resolve()) if bundled.exists() else None
