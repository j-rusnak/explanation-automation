from techshort.audio.local_tts import (
    LocalNarrationUnavailable,
    WindowsSapiNarrationProvider,
    active_synthesis_receipt,
    discover_windows_voices,
    local_narration_readiness,
    synthesize_local_narration,
)
from techshort.audio.providers import (
    NarrationProvider,
    NarrationSynthesisReceipt,
    NarrationVoice,
    SynthesizedNarration,
    derive_synthesis_id,
)
from techshort.audio.service import (
    active_audio,
    active_transcript,
    import_audio,
    import_transcript,
    probe_duration,
    set_narration_mode,
)
from techshort.audio.transcription import (
    TranscriptionAttempt,
    resolve_narration_transcript,
    transcribe_with_local_whisper,
)

__all__ = [
    "active_audio",
    "active_transcript",
    "import_audio",
    "import_transcript",
    "probe_duration",
    "set_narration_mode",
    "LocalNarrationUnavailable",
    "NarrationProvider",
    "NarrationSynthesisReceipt",
    "NarrationVoice",
    "SynthesizedNarration",
    "derive_synthesis_id",
    "WindowsSapiNarrationProvider",
    "active_synthesis_receipt",
    "discover_windows_voices",
    "local_narration_readiness",
    "synthesize_local_narration",
    "TranscriptionAttempt",
    "resolve_narration_transcript",
    "transcribe_with_local_whisper",
]
