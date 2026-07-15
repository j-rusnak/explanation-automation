from __future__ import annotations

import os
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path

from techshort.domain.models import ScriptManifest


@dataclass(frozen=True)
class CaptionCue:
    index: int
    start: float
    end: float
    text: str


MAX_CAPTION_CHARACTERS = 42


def cues_from_script(
    script: ScriptManifest, *, target_duration: float | None = None
) -> list[CaptionCue]:
    """Create deterministic cue-level captions from approved script timing.

    When reliable narration duration is available, ``target_duration`` scales the
    fallback segment timing proportionally.  The same cues are used for SRT, VTT,
    and the renderer payload so burned captions cannot drift from sidecars.
    """
    script_duration = sum(segment.approximate_duration for segment in script.segments)
    if target_duration is not None and target_duration <= 0:
        raise ValueError("target caption duration must be positive")
    timing_scale = target_duration / script_duration if target_duration is not None else 1.0
    cues: list[CaptionCue] = []
    current = 0.0
    index = 1
    for segment in script.segments:
        # textwrap always consumes input, including a single word longer than the
        # line limit.  This avoids the non-advancing loop that long technical
        # identifiers previously triggered.
        chunks = textwrap.wrap(
            segment.text,
            width=MAX_CAPTION_CHARACTERS,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=True,
            drop_whitespace=True,
        ) or [segment.text]
        segment_duration = segment.approximate_duration * timing_scale
        portion = segment_duration / len(chunks)
        for chunk in chunks:
            cues.append(CaptionCue(index=index, start=current, end=current + portion, text=chunk))
            current += portion
            index += 1
    if cues and target_duration is not None:
        # Remove accumulated floating-point error while preserving monotonic cues.
        last = cues[-1]
        cues[-1] = CaptionCue(last.index, last.start, target_duration, last.text)
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
    return [
        f"caption {cue.index} exceeds {MAX_CAPTION_CHARACTERS} characters"
        for cue in cues
        if len(cue.text) > MAX_CAPTION_CHARACTERS
    ]


def write_caption_files(directory: Path, cues: list[CaptionCue]) -> tuple[Path, Path]:
    """Atomically write matching SRT and VTT caption sidecars."""
    directory.mkdir(parents=True, exist_ok=True)
    srt = directory / "captions.srt"
    vtt = directory / "captions.vtt"
    _atomic_write_text(srt, as_srt(cues))
    _atomic_write_text(vtt, as_vtt(cues))
    return srt, vtt


def _atomic_write_text(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
