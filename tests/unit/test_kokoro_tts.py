from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any

import pytest

import techshort.audio.kokoro_tts as kokoro
from techshort.audio import active_synthesis_receipt
from techshort.audio.providers import (
    KOKORO_DEVICE,
    KOKORO_DTYPE,
    KOKORO_MODEL_ID,
    KOKORO_MODEL_REVISION,
    KOKORO_RUNTIME_VERSION,
    KokoroModelCacheManifest,
    NarrationSynthesisReceipt,
    derive_kokoro_cache_hash,
)
from techshort.domain.hashing import sha256_file
from techshort.domain.models import AssetManifest
from techshort.domain.storage import ProjectStore, atomic_write_model, load_model
from techshort.generation import fixture_claims, fixture_script, generate_angles, select_angle
from techshort.ingestion import ingest_source
from techshort.rendering.tools import media_tool
from techshort.review import approve_claims, approve_script


def _approved_store(tmp_path: Path) -> ProjectStore:
    store = ProjectStore(tmp_path / "projects", "kokoro-test")
    store.initialize("Kokoro test")
    ingest_source(store, Path("examples/rolling-shutter/rolling-shutter.md"))
    fixture_claims(store)
    approve_claims(store, "kokoro-test")
    generate_angles(store, "fixture").require_artifact()
    select_angle(store, "everyday-mechanism")
    fixture_script(store)
    approve_script(store, "kokoro-test")
    return store


def _write_wav(path: Path, *, frame_count: int = 12_000) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(b"\x01\x00" * frame_count)


def _fake_repository(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repository"
    scripts = root / "renderer" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "kokoro-local.mjs").write_text("// helper\n", encoding="utf-8")
    (scripts / "kokoro-runtime.mjs").write_text("// runtime\n", encoding="utf-8")
    (root / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    cache = root / ".techshort" / "models" / "kokoro"
    model = cache / "onnx-community" / "Kokoro-82M-v1.0-ONNX"
    (model / "onnx").mkdir(parents=True)
    (model / "config.json").write_text("{}\n", encoding="utf-8")
    (model / "onnx" / "model_quantized.onnx").write_bytes(b"pinned-model")
    monkeypatch.setattr(kokoro, "_repository_root", lambda: root)
    return root, cache


def _write_cache_manifest(cache: Path) -> KokoroModelCacheManifest:
    files = kokoro._walk_cache_files(cache)
    helper_hash, runtime_hash, package_lock_hash = kokoro._runtime_hashes()
    manifest = KokoroModelCacheManifest(
        node_helper_hash=helper_hash,
        runtime_module_hash=runtime_hash,
        package_lock_hash=package_lock_hash,
        aggregate_sha256=derive_kokoro_cache_hash(files),
        file_count=len(files),
        total_bytes=sum(item.size for item in files),
        files=files,
    )
    atomic_write_model(cache / kokoro.KOKORO_CACHE_MANIFEST_NAME, manifest)
    return manifest


def _node_cache_payload(manifest: KokoroModelCacheManifest) -> str:
    return json.dumps(
        {
            "modelId": KOKORO_MODEL_ID,
            "revision": KOKORO_MODEL_REVISION,
            "dtype": KOKORO_DTYPE,
            "device": KOKORO_DEVICE,
            "runtimeVersion": KOKORO_RUNTIME_VERSION,
            "aggregateSha256": manifest.aggregate_sha256,
            "fileCount": manifest.file_count,
            "totalBytes": manifest.total_bytes,
            "files": [item.model_dump() for item in manifest.files],
        }
    )


def test_kokoro_subprocess_is_argument_only_and_forces_offline_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _fake_repository(monkeypatch, tmp_path)
    seen: dict[str, Any] = {}

    def fake_run(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        seen["command"] = command
        seen["options"] = options
        return subprocess.CompletedProcess(command, 0, stdout="{}\n", stderr="")

    monkeypatch.setattr(kokoro.shutil, "which", lambda _name: "node.exe")
    monkeypatch.setattr(kokoro.subprocess, "run", fake_run)

    assert (
        kokoro._run_kokoro(["synthesize", "--cache-dir", "safe"], timeout_seconds=20, offline=True)
        == "{}"
    )
    assert seen["command"][:3] == [
        "node.exe",
        str(kokoro._kokoro_helper_path()),
        "synthesize",
    ]
    options = seen["options"]
    assert options["shell"] is False
    assert options["timeout"] == 20
    assert options["env"]["HF_HUB_OFFLINE"] == "1"
    assert options["env"]["TRANSFORMERS_OFFLINE"] == "1"
    assert "OPENAI_API_KEY" not in options["env"]
    assert "HTTP_PROXY" not in options["env"]


def test_explicit_setup_writes_strict_hash_bound_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _root, cache = _fake_repository(monkeypatch, tmp_path)
    files = kokoro._walk_cache_files(cache)
    provisional = KokoroModelCacheManifest(
        node_helper_hash=kokoro._runtime_hashes()[0],
        runtime_module_hash=kokoro._runtime_hashes()[1],
        package_lock_hash=kokoro._runtime_hashes()[2],
        aggregate_sha256=derive_kokoro_cache_hash(files),
        file_count=len(files),
        total_bytes=sum(item.size for item in files),
        files=files,
    )
    seen: dict[str, object] = {}

    def fake_run(arguments: list[str], *, timeout_seconds: int, offline: bool) -> str:
        seen.update(arguments=arguments, timeout=timeout_seconds, offline=offline)
        return _node_cache_payload(provisional)

    monkeypatch.setattr(kokoro, "_run_kokoro", fake_run)
    provider = kokoro.KokoroLocalNarrationProvider(cache)

    manifest = provider.setup(timeout_seconds=321)

    assert seen["arguments"] == ["setup", "--cache-dir", str(cache)]
    assert seen["timeout"] == 321
    assert seen["offline"] is False
    manifest_path = cache / kokoro.KOKORO_CACHE_MANIFEST_NAME
    assert load_model(manifest_path, KokoroModelCacheManifest) == manifest
    assert provider.readiness()[0]

    (cache / "onnx-community" / "Kokoro-82M-v1.0-ONNX" / "config.json").write_text(
        '{"changed":true}\n', encoding="utf-8"
    )
    ready, message = provider.readiness()
    assert not ready
    assert "stale" in message


def test_cache_directory_is_confined_to_repository_models(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, _cache = _fake_repository(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="under .techshort/models"):
        kokoro.KokoroLocalNarrationProvider(tmp_path / "outside")

    custom = root / ".techshort" / "models" / "custom-kokoro"
    assert kokoro.KokoroLocalNarrationProvider(custom).cache_directory == custom

    monkeypatch.setenv("TECHSHORT_KOKORO_CACHE", ".techshort/models/from-environment")
    assert kokoro.KokoroLocalNarrationProvider().cache_directory == (
        root / ".techshort" / "models" / "from-environment"
    )
    monkeypatch.setenv("TECHSHORT_KOKORO_CACHE", ".techshort/models/../../outside")
    with pytest.raises(ValueError, match="under .techshort/models"):
        kokoro.KokoroLocalNarrationProvider()


def test_kokoro_synthesizes_only_approved_segments_offline_and_registers_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if not media_tool("ffprobe"):
        pytest.skip("FFprobe is required for Kokoro narration registration tests")
    root, cache = _fake_repository(monkeypatch, tmp_path)
    manifest = _write_cache_manifest(cache)
    store = _approved_store(tmp_path)
    calls: list[tuple[list[str], bool]] = []

    def fake_run(arguments: list[str], *, timeout_seconds: int, offline: bool) -> str:
        del timeout_seconds
        calls.append((arguments, offline))
        input_path = Path(arguments[arguments.index("--input") + 1])
        output_directory = Path(arguments[arguments.index("--output-dir") + 1])
        request = json.loads(input_path.read_text(encoding="utf-8"))
        outputs = []
        for index, segment in enumerate(request["segments"]):
            filename = f"segment-{index + 1:03d}.wav"
            _write_wav(output_directory / filename)
            outputs.append(
                {
                    "segmentId": segment["segmentId"],
                    "fileName": filename,
                    "sampleRate": 24_000,
                    "sampleCount": 6_000,
                    "durationSeconds": 0.25,
                }
            )
        return json.dumps(
            {
                "schemaVersion": "1.0.0",
                "provider": "kokoro-local",
                "modelId": KOKORO_MODEL_ID,
                "revision": KOKORO_MODEL_REVISION,
                "dtype": KOKORO_DTYPE,
                "device": KOKORO_DEVICE,
                "runtimeVersion": KOKORO_RUNTIME_VERSION,
                "voice": request["voice"],
                "speed": request["speed"],
                "segments": outputs,
                "modelCacheSha256": manifest.aggregate_sha256,
            }
        )

    def fake_normalize(source: Path, destination: Path) -> float:
        shutil.copyfile(source, destination)
        return 0.0

    monkeypatch.setattr(kokoro, "_run_kokoro", fake_run)
    monkeypatch.setattr(kokoro, "_normalize_audio", fake_normalize)
    provider = kokoro.KokoroLocalNarrationProvider(cache)

    result = provider.synthesize(store, voice_name="af_heart", speed=1.1)

    assert len(calls) == 1
    assert calls[0][0][0] == "synthesize"
    assert calls[0][1] is True
    assert result.provider == "kokoro-local"
    assert result.voice.name == "af_heart"
    assert result.speed == 1.1
    receipt = load_model(result.receipt_path, NarrationSynthesisReceipt)
    assert receipt.provider == "kokoro-local"
    assert receipt.kokoro is not None
    assert receipt.kokoro.model_id == KOKORO_MODEL_ID
    assert receipt.kokoro.revision == KOKORO_MODEL_REVISION
    assert receipt.kokoro.dtype == "q8"
    assert receipt.kokoro.device == "cpu"
    assert receipt.kokoro.offline_mode is True
    assert receipt.kokoro.cache_path == cache.relative_to(root).as_posix()
    assert receipt.kokoro.model_cache_sha256 == manifest.aggregate_sha256
    assert receipt.kokoro.cache_manifest_hash == sha256_file(
        cache / kokoro.KOKORO_CACHE_MANIFEST_NAME
    )
    assert receipt.segments
    assert all(not segment.engine_events for segment in receipt.segments)
    assert active_synthesis_receipt(store) == (receipt, result.receipt_path)
    asset = load_model(store.path("assets/asset-manifest.json"), AssetManifest).assets[0]
    assert asset.rights_status == "unknown"
    assert not asset.embedding_allowed


@pytest.mark.parametrize(
    "voice,speed", [("../../voice", 1.0), ("af_heart", True), ("af_heart", 2.0)]
)
def test_kokoro_rejects_unreviewed_voice_and_unbounded_speed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    voice: str,
    speed: Any,
) -> None:
    _root, cache = _fake_repository(monkeypatch, tmp_path)
    provider = kokoro.KokoroLocalNarrationProvider(cache)
    store = _approved_store(tmp_path)

    with pytest.raises(ValueError, match="voice|speed"):
        provider.synthesize(store, voice_name=voice, speed=speed)


def test_kokoro_synthesis_refuses_stale_cache_before_starting_node(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _root, cache = _fake_repository(monkeypatch, tmp_path)
    _write_cache_manifest(cache)
    (cache / "onnx-community" / "Kokoro-82M-v1.0-ONNX" / "config.json").write_text(
        "tampered\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        kokoro,
        "_run_kokoro",
        lambda *_args, **_kwargs: pytest.fail("Node must not run with a stale cache"),
    )

    with pytest.raises(ValueError, match="stale"):
        kokoro.KokoroLocalNarrationProvider(cache).synthesize(_approved_store(tmp_path))
