$ErrorActionPreference = "Stop"
function Assert-NativeSuccess([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE." }
}
& .\.venv\Scripts\python.exe -m ruff format --check .
Assert-NativeSuccess "Python formatting"
& .\.venv\Scripts\python.exe -m ruff check .
Assert-NativeSuccess "Python lint"
& .\.venv\Scripts\python.exe -m mypy src
Assert-NativeSuccess "Python type checking"
& .\.venv\Scripts\python.exe -m pytest
Assert-NativeSuccess "Python tests"
npm.cmd run format:check
Assert-NativeSuccess "TypeScript formatting"
npm.cmd run lint
Assert-NativeSuccess "TypeScript lint"
npm.cmd run typecheck
Assert-NativeSuccess "TypeScript type checking"
npm.cmd run test:renderer
Assert-NativeSuccess "Renderer tests"
