from __future__ import annotations

import ast
from pathlib import Path


def _python_trees() -> list[tuple[Path, ast.AST]]:
    rows: list[tuple[Path, ast.AST]] = []
    for path in Path("src/techshort").rglob("*.py"):
        rows.append((path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))))
    return rows


def test_runtime_contains_no_eval_or_exec_calls() -> None:
    violations: list[str] = []
    for path, tree in _python_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"eval", "exec"}:
                    violations.append(f"{path}:{node.lineno}:{node.func.id}")
    assert violations == []


def test_runtime_never_enables_subprocess_shell() -> None:
    violations: list[str] = []
    for path, tree in _python_trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "shell"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ):
                    violations.append(f"{path}:{node.lineno}")
    assert violations == []
