param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("list", "synthesize")]
    [string]$Action,
    [string]$InputText,
    [string]$OutputWav,
    [string]$Voice,
    [ValidateRange(-10, 10)]
    [int]$Rate = 1,
    [ValidateRange(1, 100)]
    [int]$Volume = 100
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
Add-Type -AssemblyName System.Speech

$synthesizer = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voices = @(
        $synthesizer.GetInstalledVoices() |
            Where-Object { $_.Enabled } |
            ForEach-Object {
                [ordered]@{
                    name = $_.VoiceInfo.Name
                    culture = $_.VoiceInfo.Culture.Name
                    gender = $_.VoiceInfo.Gender.ToString()
                    age = $_.VoiceInfo.Age.ToString()
                }
            }
    )

    if ($Action -eq "list") {
        ConvertTo-Json -InputObject @($voices) -Compress
        exit 0
    }

    if (-not $InputText -or -not $OutputWav -or -not $Voice) {
        throw "synthesize requires InputText, OutputWav, and Voice"
    }
    if (-not [IO.File]::Exists($InputText)) {
        throw "approved narration text file does not exist"
    }
    if ([IO.Path]::GetExtension($OutputWav) -ne ".wav") {
        throw "local narration output must be a WAV file"
    }
    if (([IO.FileInfo]$InputText).Length -gt 131072) {
        throw "approved narration text exceeds the 128 KiB limit"
    }
    $text = [IO.File]::ReadAllText($InputText, [Text.Encoding]::UTF8).Trim()
    if ([String]::IsNullOrWhiteSpace($text)) {
        throw "approved narration text is empty"
    }
    if ($Voice -notin @($voices | ForEach-Object { $_.name })) {
        throw "requested System.Speech voice is not enabled"
    }

    $outputDirectory = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($OutputWav))
    if (-not [IO.Directory]::Exists($outputDirectory)) {
        throw "local narration output directory does not exist"
    }
    $synthesizer.SelectVoice($Voice)
    $synthesizer.Rate = $Rate
    $synthesizer.Volume = $Volume
    $prompt = New-Object System.Speech.Synthesis.PromptBuilder
    $lines = @($text -split "`r?`n" | Where-Object { -not [String]::IsNullOrWhiteSpace($_) })
    for ($index = 0; $index -lt $lines.Count; $index++) {
        # AppendText escapes the supplied text as speech content. It does not
        # interpret source/model text as SSML. Only this fixed helper controls
        # the allowlisted 140 ms pause between approved script segments.
        $prompt.AppendText($lines[$index].Trim())
        if ($index -lt ($lines.Count - 1)) {
            $prompt.AppendBreak([TimeSpan]::FromMilliseconds(140))
        }
    }
    $synthesizer.SetOutputToWaveFile([IO.Path]::GetFullPath($OutputWav))
    $synthesizer.Speak($prompt)
    $synthesizer.SetOutputToNull()
    [ordered]@{
        voice = $Voice
        rate = $Rate
        volume = $Volume
        output = [IO.Path]::GetFileName($OutputWav)
    } | ConvertTo-Json -Compress
}
finally {
    $synthesizer.Dispose()
}
