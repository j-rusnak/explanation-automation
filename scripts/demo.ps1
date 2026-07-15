$ErrorActionPreference = "Stop"
$cli = ".\.venv\Scripts\techshort.exe"
function Invoke-Techshort {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $cli @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "techshort $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }
}
Invoke-Techshort init rolling-shutter --title "Rolling-Shutter Distortion"
Invoke-Techshort ingest rolling-shutter examples\rolling-shutter\rolling-shutter.md
Invoke-Techshort claims generate rolling-shutter --provider fixture
Invoke-Techshort review rolling-shutter --gate claims
Invoke-Techshort script generate rolling-shutter --provider fixture --angle everyday-mechanism
Invoke-Techshort review rolling-shutter --gate script
Invoke-Techshort storyboard generate rolling-shutter --provider fixture
Invoke-Techshort review rolling-shutter --gate storyboard
Invoke-Techshort review rolling-shutter --gate rights
Invoke-Techshort captions generate rolling-shutter
Invoke-Techshort preview rolling-shutter
Invoke-Techshort qa rolling-shutter
Invoke-Techshort evidence-page rolling-shutter
Invoke-Techshort review rolling-shutter --gate final
Invoke-Techshort render rolling-shutter
Invoke-Techshort export rolling-shutter
