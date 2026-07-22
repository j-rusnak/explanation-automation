from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "statement",
    [
        "from techshort.providers.fixture import FixtureProvider",
        "from techshort.providers import FixtureProvider",
        "from techshort.providers.manual import ManualProvider",
        "from techshort.providers.codex_cli import CodexCliProvider",
    ],
)
def test_provider_imports_work_in_a_clean_python_process(statement: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", statement],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
