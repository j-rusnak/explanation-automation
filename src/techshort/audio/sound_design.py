from __future__ import annotations

import math
import sys
import tempfile
import wave
from array import array
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from techshort.audio.service import active_audio, probe_duration
from techshort.domain.creative import RetentionPlan, SoundDesignCue
from techshort.domain.hashing import sha256_file, stable_hash
from techshort.domain.models import (
    Asset,
    AssetManifest,
    ReviewStatus,
    StrictModel,
    now_utc,
)
from techshort.domain.storage import (
    ProjectStore,
    atomic_copy_file,
    atomic_write_model,
    load_model,
)

SOUND_DESIGN_SCHEMA_VERSION = "1.0.0"
SOUND_DESIGN_GENERATOR_VERSION = "procedural-accents-v1"
SAMPLE_RATE = 48_000
PRESET_LEVELS: dict[str, float] = {"subtle": 0.075, "present": 0.12}


class SoundDesignEvent(StrictModel):
    event_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    cue: SoundDesignCue
    time_seconds: float = Field(ge=0, le=120)
    peak_amplitude: float = Field(gt=0, le=0.15)


class SoundDesignReceipt(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    sound_design_id: str = Field(pattern=r"^sound-design-[0-9a-f]{16}$")
    generator_version: Literal["procedural-accents-v1"] = "procedural-accents-v1"
    preset: Literal["subtle", "present"]
    retention_plan_version_id: str
    retention_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    narration_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    duration_seconds: float = Field(gt=0, le=120)
    sample_rate: Literal[48000] = 48_000
    events: list[SoundDesignEvent] = Field(min_length=1, max_length=15)
    output_path: str
    output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=now_utc)

    @model_validator(mode="after")
    def identifier_matches_content(self) -> SoundDesignReceipt:
        expected = _receipt_id(self.model_dump(mode="json"))
        if self.sound_design_id != expected:
            raise ValueError("sound-design ID does not match its exact inputs and output")
        return self


def _receipt_id(payload: dict[str, object]) -> str:
    stable = {
        key: value for key, value in payload.items() if key not in {"sound_design_id", "created_at"}
    }
    return f"sound-design-{stable_hash(stable)[:16]}"


def _retention_plan(store: ProjectStore) -> RetentionPlan:
    path = store.path("script/retention-plan.json")
    if not path.is_file():
        raise ValueError("generate an approved script retention plan before sound design")
    plan = load_model(path, RetentionPlan)
    project = store.project()
    if project.active_versions.get("retention_plan") != plan.version_id:
        raise ValueError("the sound-design retention plan is not the active plan")
    if project.approvals.script != ReviewStatus.APPROVED:
        raise ValueError("approve the current script before generating sound design")
    return plan


def _target_duration(store: ProjectStore, plan: RetentionPlan) -> tuple[float, str | None]:
    narration = active_audio(store)
    if narration is None:
        return plan.cadence.total_duration_seconds, None
    duration = probe_duration(narration)
    if duration is None or not math.isfinite(duration) or duration <= 0:
        raise ValueError("active narration duration is unavailable for sound design")
    return duration, sha256_file(narration)


def _cue_sample(cue: SoundDesignCue, elapsed: float, duration: float) -> float:
    progress = min(1.0, max(0.0, elapsed / duration))
    attack = min(1.0, elapsed / 0.012)
    release = (1.0 - progress) ** 2
    envelope = attack * release
    if cue == "soft-hit":
        frequency = 92.0 - 24.0 * progress
        tone = math.sin(2.0 * math.pi * frequency * elapsed)
        transient = 0.35 * math.sin(2.0 * math.pi * 420.0 * elapsed)
        return envelope * (tone + transient) / 1.35
    if cue == "scan-pulse":
        frequency = 620.0 + 560.0 * progress
        return envelope * math.sin(2.0 * math.pi * frequency * elapsed)
    if cue == "source-click":
        tone = math.sin(2.0 * math.pi * 1_600.0 * elapsed)
        overtone = 0.45 * math.sin(2.0 * math.pi * 2_350.0 * elapsed)
        return envelope * (tone + overtone) / 1.45
    if cue == "contrast-shift":
        frequency = 300.0 if progress < 0.45 else 510.0
        return envelope * math.sin(2.0 * math.pi * frequency * elapsed)
    frequency = 430.0 + 230.0 * progress
    fundamental = math.sin(2.0 * math.pi * frequency * elapsed)
    harmonic = 0.25 * math.sin(2.0 * math.pi * frequency * 1.5 * elapsed)
    return envelope * (fundamental + harmonic) / 1.25


def _cue_duration(cue: SoundDesignCue) -> float:
    return {
        "soft-hit": 0.24,
        "scan-pulse": 0.16,
        "source-click": 0.09,
        "contrast-shift": 0.22,
        "resolve-tone": 0.38,
    }[cue]


def _write_wave(path: Path, duration: float, events: list[SoundDesignEvent]) -> None:
    frame_count = max(1, math.ceil(duration * SAMPLE_RATE))
    samples = array("h", [0]) * frame_count
    for event in events:
        cue_duration = _cue_duration(event.cue)
        start = min(frame_count - 1, max(0, round(event.time_seconds * SAMPLE_RATE)))
        cue_frames = min(frame_count - start, math.ceil(cue_duration * SAMPLE_RATE))
        for offset in range(cue_frames):
            elapsed = offset / SAMPLE_RATE
            value = _cue_sample(event.cue, elapsed, cue_duration)
            mixed = samples[start + offset] + round(32_767 * event.peak_amplitude * value)
            samples[start + offset] = min(32_767, max(-32_768, mixed))
    if sys.byteorder != "little":  # pragma: no cover - supported hosts are little-endian
        samples.byteswap()
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(samples.tobytes())


def _archive_receipt(store: ProjectStore, receipt: SoundDesignReceipt) -> None:
    current = store.path("audio/sound-design.json")
    versions = store.path("audio/versions")
    versions.mkdir(parents=True, exist_ok=True)
    destination = versions / f"{receipt.sound_design_id}.json"
    if destination.is_file() and sha256_file(destination) != sha256_file(current):
        destination = versions / f"{receipt.sound_design_id}-state-{sha256_file(current)[:12]}.json"
    if not destination.exists():
        atomic_copy_file(current, destination)


def generate_sound_design(
    store: ProjectStore,
    preset: Literal["subtle", "present"] = "subtle",
) -> SoundDesignReceipt:
    """Generate quiet, deterministic accents from the allowlisted retention cues."""

    if preset not in PRESET_LEVELS:
        raise ValueError("sound-design preset must be subtle or present")
    plan = _retention_plan(store)
    duration, narration_hash = _target_duration(store, plan)
    timing_scale = duration / plan.cadence.total_duration_seconds
    events = [
        SoundDesignEvent(
            event_id=event.event_id,
            cue=event.sound_design,
            time_seconds=min(duration - 0.001, event.scheduled_at_seconds * timing_scale),
            peak_amplitude=PRESET_LEVELS[preset],
        )
        for event in plan.attention_events
        if event.sound_design is not None
    ]
    if not events:
        raise ValueError("the active retention plan has no allowlisted sound-design cues")

    audio_directory = store.path("audio")
    audio_directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sound-design-", dir=audio_directory) as stage:
        temporary = Path(stage) / "sound-design.wav"
        _write_wave(temporary, duration, events)
        output_hash = sha256_file(temporary)
        destination = store.path(f"audio/{output_hash[:12]}-sound-design.wav")
        if destination.exists() and sha256_file(destination) != output_hash:
            raise ValueError("existing sound-design destination has unexpected bytes")
        if not destination.exists():
            atomic_copy_file(temporary, destination)

    payload: dict[str, object] = {
        "schema_version": SOUND_DESIGN_SCHEMA_VERSION,
        "sound_design_id": "sound-design-0000000000000000",
        "generator_version": SOUND_DESIGN_GENERATOR_VERSION,
        "preset": preset,
        "retention_plan_version_id": plan.version_id,
        "retention_plan_hash": stable_hash(plan),
        "narration_hash": narration_hash,
        "duration_seconds": duration,
        "sample_rate": SAMPLE_RATE,
        "events": [event.model_dump(mode="json") for event in events],
        "output_path": destination.relative_to(store.root).as_posix(),
        "output_hash": output_hash,
        "created_at": now_utc(),
    }
    payload["sound_design_id"] = _receipt_id(payload)
    receipt = SoundDesignReceipt.model_validate(payload)

    receipt_path = store.path("audio/sound-design.json")
    previous_receipt = (
        load_model(receipt_path, SoundDesignReceipt) if receipt_path.is_file() else None
    )
    if previous_receipt is not None and previous_receipt.sound_design_id == receipt.sound_design_id:
        receipt = previous_receipt
    if previous_receipt is not None and previous_receipt != receipt:
        _archive_receipt(store, previous_receipt)

    asset_path = store.path("assets/asset-manifest.json")
    assets = (
        load_model(asset_path, AssetManifest)
        if asset_path.is_file()
        else AssetManifest(version_id="assets-empty")
    )
    asset_id = f"asset-sound-design-{output_hash[:12]}"
    previous_asset = next((asset for asset in assets.assets if asset.asset_id == asset_id), None)
    sound_asset = Asset(
        asset_id=asset_id,
        asset_type="sound-design",
        local_path=receipt.output_path,
        sha256=output_hash,
        origin=f"techshort {SOUND_DESIGN_GENERATOR_VERSION}",
        creator="techshort deterministic procedural audio",
        license="original procedural audio (review required)",
        rights_status="original",
        embedding_allowed=True,
        review_status=(
            previous_asset.review_status if previous_asset is not None else ReviewStatus.PENDING
        ),
        scene_usage=[],
    )
    updated_assets = [asset for asset in assets.assets if asset.asset_type != "sound-design"]
    updated_assets.append(sound_asset)
    updated_assets.sort(key=lambda asset: asset.asset_id)
    version_payload = [asset.model_dump(exclude={"review_status"}) for asset in updated_assets]
    updated = AssetManifest(
        version_id=f"assets-{stable_hash(version_payload)[:12]}", assets=updated_assets
    )

    unchanged = (
        previous_receipt == receipt
        and assets == updated
        and store.project().active_versions.get("sound_design") == receipt.sound_design_id
    )
    atomic_write_model(receipt_path, receipt)
    atomic_write_model(asset_path, updated)
    project = store.project()
    if not unchanged:
        project = store.invalidate_from("rights", "procedural sound design generated or changed")
    project.active_versions["sound_design"] = receipt.sound_design_id
    project.active_versions["sound_design_asset"] = asset_id
    project.active_versions["assets"] = updated.version_id
    project.dependency_hashes["sound_design"] = output_hash
    project.dependency_hashes["sound_design_inputs"] = stable_hash(
        {
            "retention": receipt.retention_plan_hash,
            "narration": narration_hash,
            "preset": preset,
        }
    )
    store.save_project(project)
    return receipt


def active_sound_design(store: ProjectStore) -> Path | None:
    """Resolve and verify the active procedural sound-design track."""

    project = store.project()
    receipt_id = project.active_versions.get("sound_design")
    asset_id = project.active_versions.get("sound_design_asset")
    expected_hash = project.dependency_hashes.get("sound_design")
    if receipt_id is None and asset_id is None and expected_hash is None:
        return None
    if not receipt_id or not asset_id or not expected_hash:
        raise ValueError("active sound-design metadata is incomplete; generate it again")
    receipt = load_model(store.path("audio/sound-design.json"), SoundDesignReceipt)
    if receipt.sound_design_id != receipt_id or receipt.output_hash != expected_hash:
        raise ValueError("active sound-design receipt is stale")
    plan = _retention_plan(store)
    duration, narration_hash = _target_duration(store, plan)
    if (
        receipt.retention_plan_version_id != plan.version_id
        or receipt.retention_plan_hash != stable_hash(plan)
        or receipt.narration_hash != narration_hash
        or abs(receipt.duration_seconds - duration) > 0.02
    ):
        raise ValueError("sound design is stale for the active script or narration")
    assets = load_model(store.path("assets/asset-manifest.json"), AssetManifest)
    asset = next((item for item in assets.assets if item.asset_id == asset_id), None)
    if asset is None or asset.asset_type != "sound-design":
        raise ValueError("active sound-design asset is missing")
    path = store.path(receipt.output_path)
    if (
        asset.local_path != receipt.output_path
        or asset.sha256 != expected_hash
        or not path.is_file()
        or sha256_file(path) != expected_hash
    ):
        raise ValueError("active sound-design bytes changed; generate it again")
    return path
