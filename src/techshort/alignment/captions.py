from __future__ import annotations

from dataclasses import dataclass

from techshort.domain.models import ScriptManifest


@dataclass(frozen=True)
class CaptionCue:
    index: int
    start: float
    end: float
    text: str


def cues_from_script(script: ScriptManifest) -> list[CaptionCue]:
    cues: list[CaptionCue] = []
    current = 0.0
    index = 1
    for segment in script.segments:
        words = segment.text.split()
        chunks: list[str] = []
        while words:
            chunk_words: list[str] = []
            while words and len(" ".join(chunk_words + [words[0]])) <= 42:
                chunk_words.append(words.pop(0))
            chunks.append(" ".join(chunk_words))
        portion = segment.approximate_duration / max(1, len(chunks))
        for chunk in chunks:
            cues.append(CaptionCue(index=index, start=current, end=current + portion, text=chunk))
            current += portion
            index += 1
    return cues


def _time(value: float, vtt: bool = False) -> str:
    milliseconds = round(value * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    separator = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def as_srt(cues: list[CaptionCue]) -> str:
    return (
        "\n\n".join(
            f"{cue.index}\n{_time(cue.start)} --> {_time(cue.end)}\n{cue.text}" for cue in cues
        )
        + "\n"
    )


def as_vtt(cues: list[CaptionCue]) -> str:
    body = "\n\n".join(
        f"{_time(cue.start, True)} --> {_time(cue.end, True)}\n{cue.text}" for cue in cues
    )
    return f"WEBVTT\n\n{body}\n"


def caption_warnings(cues: list[CaptionCue]) -> list[str]:
    return [f"caption {cue.index} exceeds 42 characters" for cue in cues if len(cue.text) > 42]
