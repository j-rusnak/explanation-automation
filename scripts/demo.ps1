$ErrorActionPreference = "Stop"
$cli = ".\.venv\Scripts\techshort.exe"
& $cli init rolling-shutter --title "Rolling-Shutter Distortion"
& $cli ingest rolling-shutter examples\rolling-shutter\rolling-shutter.md
& $cli claims generate rolling-shutter --provider fixture
& $cli review rolling-shutter --gate claims
& $cli script generate rolling-shutter --provider fixture --angle everyday-mechanism
& $cli review rolling-shutter --gate script
& $cli storyboard generate rolling-shutter --provider fixture
& $cli review rolling-shutter --gate storyboard
& $cli review rolling-shutter --gate rights
& $cli captions generate rolling-shutter
& $cli preview rolling-shutter
& $cli qa rolling-shutter
& $cli evidence-page rolling-shutter
& $cli review rolling-shutter --gate final
& $cli render rolling-shutter
& $cli export rolling-shutter
