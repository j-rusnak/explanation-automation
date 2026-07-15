$ErrorActionPreference = "Stop"
& .\.venv\Scripts\python.exe -m ruff format --check .
& .\.venv\Scripts\python.exe -m ruff check .
& .\.venv\Scripts\python.exe -m mypy src
& .\.venv\Scripts\python.exe -m pytest
npm.cmd run format:check
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run test:renderer
