$ErrorActionPreference = "Stop"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    $python = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
}
if (-not $python) { throw "Python 3.11-3.14 is required. Install maintained CPython and rerun setup." }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js 22 is required." }
$pythonPath = if ($python.Source) { $python.Source } else { $python.FullName }
$pythonVersion = & $pythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$pythonVersion -lt [version]"3.11" -or [version]$pythonVersion -ge [version]"3.15") {
    throw "Unsupported Python $pythonVersion. Install Python 3.11 through 3.14."
}
$nodeMajor = [int]((& node --version).TrimStart("v").Split(".")[0])
if ($nodeMajor -ne 22) { throw "Node.js 22 is required; found major version $nodeMajor." }
if (-not (Test-Path .venv)) { & $pythonPath -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install pip==26.1.2
& .\.venv\Scripts\python.exe -m pip install -r requirements.lock
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]" --no-deps --no-build-isolation
npm.cmd ci
& .\.venv\Scripts\python.exe scripts\export_schemas.py
& .\.venv\Scripts\techshort.exe doctor
