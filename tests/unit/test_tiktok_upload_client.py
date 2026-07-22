from __future__ import annotations

import io
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

import pytest

from techshort.publication.official.tiktok import (
    API_ORIGIN,
    INITIALIZE_PATH,
    MAX_API_RESPONSE_BYTES,
    MAX_VIDEO_BYTES,
    STATUS_PATH,
    HttpsTikTokTransport,
    TikTokApiError,
    TikTokConfigurationError,
    TikTokCredentials,
    TikTokDraftUploadClient,
    TikTokHttpResponse,
    TikTokTransportError,
)


@dataclass
class RecordedRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes
    body_length: int
    timeout_seconds: float
    max_response_bytes: int


class FakeTransport:
    def __init__(self, responses: list[TikTokHttpResponse]) -> None:
        self.responses = responses
        self.requests: list[RecordedRequest] = []

    def request(
        self,
        *,
        method: Literal["POST", "PUT"],
        url: str,
        headers: Mapping[str, str],
        body: bytes | BinaryIO,
        body_length: int,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> TikTokHttpResponse:
        captured = body if isinstance(body, bytes) else body.read()
        self.requests.append(
            RecordedRequest(
                method=method,
                url=url,
                headers=dict(headers),
                body=captured,
                body_length=body_length,
                timeout_seconds=timeout_seconds,
                max_response_bytes=max_response_bytes,
            )
        )
        return self.responses.pop(0)


def _credentials() -> TikTokCredentials:
    return TikTokCredentials.from_env(
        {
            "TECHSHORT_TIKTOK_ACCESS_TOKEN": "token_" + "private-value",  # noqa: S105
            "TECHSHORT_TIKTOK_OPEN_ID": "creator_123",
        }
    )


def _mp4(path: Path, *, payload_size: int = 256) -> Path:
    path.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"x" * payload_size)
    return path


def _json_response(data: object, *, code: str = "ok", status: int = 200) -> TikTokHttpResponse:
    return TikTokHttpResponse(
        status_code=status,
        body=json.dumps(
            {"data": data, "error": {"code": code, "message": "", "log_id": "log-1"}}
        ).encode(),
    )


def test_complete_draft_upload_uses_exact_official_requests(tmp_path: Path) -> None:
    video = _mp4(tmp_path / "video.mp4")
    upload_url = (
        "https://open-upload.tiktokapis.com/video/?upload_id=opaque&upload_token=secret-query"
    )
    transport = FakeTransport(
        [
            _json_response({"publish_id": "v_pub_file~v2.123", "upload_url": upload_url}),
            TikTokHttpResponse(status_code=201, body=b""),
            _json_response(
                {
                    "status": "SEND_TO_USER_INBOX",
                    "uploaded_bytes": video.stat().st_size,
                    "publicaly_available_post_id": [],
                }
            ),
        ]
    )
    client = TikTokDraftUploadClient(_credentials(), transport)

    initialization = client.initialize_draft(video)
    receipt = client.upload_video(initialization, video)
    status = client.fetch_status(initialization.publish_id)

    assert initialization.publish_id == "v_pub_file~v2.123"
    assert "secret-query" not in repr(initialization)
    assert not hasattr(initialization, "_upload_url")
    assert receipt.bytes_uploaded == video.stat().st_size
    assert receipt.http_status == 201
    assert status.status == "SEND_TO_USER_INBOX"
    assert status.terminal
    assert not status.publicly_available

    initialize, upload, fetch = transport.requests
    assert initialize.method == "POST"
    assert initialize.url == f"{API_ORIGIN}{INITIALIZE_PATH}"
    initialize_payload = json.loads(initialize.body)
    assert initialize_payload == {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video.stat().st_size,
            "chunk_size": video.stat().st_size,
            "total_chunk_count": 1,
        }
    }
    assert initialize.headers["Authorization"].startswith("Bearer ")
    assert initialize.headers["Content-Length"] == str(len(initialize.body))

    assert upload.method == "PUT"
    assert upload.url == upload_url
    assert "Authorization" not in upload.headers
    assert upload.headers["Content-Type"] == "video/mp4"
    assert upload.headers["Content-Length"] == str(video.stat().st_size)
    assert upload.headers["Content-Range"] == (
        f"bytes 0-{video.stat().st_size - 1}/{video.stat().st_size}"
    )
    assert upload.body == video.read_bytes()

    assert fetch.method == "POST"
    assert fetch.url == f"{API_ORIGIN}{STATUS_PATH}"
    assert json.loads(fetch.body) == {"publish_id": initialization.publish_id}


def test_credentials_are_loaded_from_explicit_mapping_and_redacted() -> None:
    token = "sensitive_" + "token"
    open_id = "sensitive_creator"
    environment = {
        "TECHSHORT_TIKTOK_ACCESS_TOKEN": token,
        "TECHSHORT_TIKTOK_OPEN_ID": open_id,
    }

    credentials = TikTokCredentials.from_env(environment)
    diagnostics = credentials.diagnostics()

    assert diagnostics.configured
    assert diagnostics.required_scope == "video.upload"
    assert diagnostics.account_subject_hash == credentials.account_subject_hash
    assert len(credentials.account_subject_hash) == 64
    assert token not in repr(credentials)
    assert open_id not in repr(credentials)
    assert token not in str(credentials)
    assert open_id not in str(credentials)


def test_raw_response_representation_never_displays_secret_body_or_headers() -> None:
    upload_url = "https://open-upload.tiktokapis.com/video/?upload_token=secret"
    response = TikTokHttpResponse(
        status_code=200,
        body=upload_url.encode(),
        headers=(("Location", upload_url),),
    )

    rendered = repr(response)
    assert upload_url not in rendered
    assert "upload_token" not in rendered
    assert "body=<" in rendered and " bytes>" in rendered


def test_credential_diagnostics_report_missing_and_invalid_without_secrets() -> None:
    missing = TikTokCredentials.diagnose_env({})
    invalid = TikTokCredentials.diagnose_env(
        {
            "TECHSHORT_TIKTOK_ACCESS_TOKEN": "bad\r\nheader",
            "TECHSHORT_TIKTOK_OPEN_ID": "creator",
        }
    )

    assert not missing.configured
    assert set(missing.missing_environment_variables) == {
        "TECHSHORT_TIKTOK_ACCESS_TOKEN",
        "TECHSHORT_TIKTOK_OPEN_ID",
    }
    assert not invalid.configured
    assert invalid.invalid_environment_variables == ("TECHSHORT_TIKTOK_ACCESS_TOKEN",)
    assert "bad" not in repr(invalid)
    with pytest.raises(TikTokConfigurationError, match="TECHSHORT_TIKTOK_ACCESS_TOKEN"):
        TikTokCredentials.from_env(
            {
                "TECHSHORT_TIKTOK_ACCESS_TOKEN": "bad\r\nheader",
                "TECHSHORT_TIKTOK_OPEN_ID": "creator",
            }
        )


def test_definite_api_rejection_preserves_safe_code_and_log_id(tmp_path: Path) -> None:
    transport = FakeTransport(
        [
            TikTokHttpResponse(
                status_code=401,
                body=json.dumps(
                    {
                        "data": {},
                        "error": {
                            "code": "access_token_invalid",
                            "message": "Access token is invalid",
                            "log_id": "log-safe-1",
                        },
                    }
                ).encode(),
            )
        ]
    )
    client = TikTokDraftUploadClient(_credentials(), transport)

    with pytest.raises(TikTokApiError) as captured:
        client.initialize_draft(_mp4(tmp_path / "video.mp4"))

    assert captured.value.code == "access_token_invalid"
    assert captured.value.http_status == 401
    assert captured.value.log_id == "log-safe-1"
    assert not captured.value.args[0].startswith("https://")


@pytest.mark.parametrize(
    "response",
    [
        TikTokHttpResponse(status_code=200, body=b"not-json"),
        TikTokHttpResponse(
            status_code=200,
            body=b'{"data":{},"data":{},"error":{"code":"ok","message":""}}',
        ),
        TikTokHttpResponse(status_code=200, body=b"x" * (MAX_API_RESPONSE_BYTES + 1)),
    ],
)
def test_malformed_or_oversized_response_is_ambiguous_transport_failure(
    tmp_path: Path, response: TikTokHttpResponse
) -> None:
    client = TikTokDraftUploadClient(_credentials(), FakeTransport([response]))

    with pytest.raises(TikTokTransportError) as captured:
        client.initialize_draft(_mp4(tmp_path / "video.mp4"))

    assert captured.value.ambiguous


def test_custom_transport_exception_cannot_leak_upload_url_or_token(tmp_path: Path) -> None:
    class LeakyTransport:
        def request(self, **_: object) -> TikTokHttpResponse:
            raise RuntimeError(
                "token_private-value at "
                "https://open-upload.tiktokapis.com/video/?upload_token=secret"
            )

    client = TikTokDraftUploadClient(_credentials(), LeakyTransport())

    with pytest.raises(TikTokTransportError) as captured:
        client.initialize_draft(_mp4(tmp_path / "video.mp4"))

    rendered = repr(captured.value) + str(captured.value)
    assert "private-value" not in rendered
    assert "upload_token" not in rendered
    assert captured.value.ambiguous


@pytest.mark.parametrize(
    "upload_url",
    [
        "http://open-upload.tiktokapis.com/video/?token=x",
        "https://evil.example/video/?token=x",
        "https://open-upload.tiktokapis.com.evil.example/video/?token=x",
        "https://open-upload.tiktokapis.com/video/",
        "https://user:pass@open-upload.tiktokapis.com/video/?token=x",
    ],
)
def test_initialization_rejects_nonofficial_or_unscoped_upload_url(
    tmp_path: Path, upload_url: str
) -> None:
    transport = FakeTransport(
        [_json_response({"publish_id": "v_pub_file~v2.123", "upload_url": upload_url})]
    )
    client = TikTokDraftUploadClient(_credentials(), transport)

    with pytest.raises(TikTokTransportError) as captured:
        client.initialize_draft(_mp4(tmp_path / "video.mp4"))

    assert upload_url not in str(captured.value)


def test_fixed_transport_rejects_host_and_header_injection_before_network() -> None:
    transport = HttpsTikTokTransport()

    with pytest.raises(TikTokConfigurationError, match="allowlisted"):
        transport.request(
            method="POST",
            url="https://evil.example/path",
            headers={"Content-Length": "2"},
            body=b"{}",
            body_length=2,
            timeout_seconds=1,
            max_response_bytes=100,
        )
    with pytest.raises(TikTokConfigurationError, match="header value"):
        transport.request(
            method="POST",
            url=f"{API_ORIGIN}{INITIALIZE_PATH}",
            headers={"Content-Length": "2", "X-Test": "safe\r\nInjected: true"},
            body=b"{}",
            body_length=2,
            timeout_seconds=1,
            max_response_bytes=100,
        )
    with pytest.raises(TikTokConfigurationError, match="endpoint"):
        transport.request(
            method="POST",
            url=f"{API_ORIGIN}/v2/unrelated/endpoint/",
            headers={"Content-Length": "2"},
            body=b"{}",
            body_length=2,
            timeout_seconds=1,
            max_response_bytes=100,
        )


def test_redirect_is_a_definite_non_success_and_is_not_followed(tmp_path: Path) -> None:
    client = TikTokDraftUploadClient(
        _credentials(), FakeTransport([TikTokHttpResponse(status_code=302, body=b"")])
    )

    with pytest.raises(TikTokApiError) as captured:
        client.initialize_draft(_mp4(tmp_path / "video.mp4"))

    assert captured.value.http_status == 302
    assert captured.value.code == "http_302"


def test_single_chunk_upload_requires_created_not_partial_content(tmp_path: Path) -> None:
    video = _mp4(tmp_path / "video.mp4")
    upload_url = "https://open-upload.tiktokapis.com/video/?upload_token=secret"
    client = TikTokDraftUploadClient(
        _credentials(),
        FakeTransport(
            [
                _json_response({"publish_id": "v_pub_file~v2.123", "upload_url": upload_url}),
                TikTokHttpResponse(status_code=206, body=b""),
            ]
        ),
    )
    initialization = client.initialize_draft(video)

    with pytest.raises(TikTokApiError) as captured:
        client.upload_video(initialization, video)

    assert captured.value.http_status == 206
    assert captured.value.code == "upload_http_206"


@pytest.mark.parametrize("operation", ["initialize", "upload"])
def test_server_failures_are_ambiguous_and_never_reported_as_rejections(
    tmp_path: Path, operation: str
) -> None:
    video = _mp4(tmp_path / "video.mp4")
    upload_url = "https://open-upload.tiktokapis.com/video/?upload_token=secret"
    server_failure = TikTokHttpResponse(
        status_code=500,
        body=json.dumps(
            {
                "data": {},
                "error": {
                    "code": "internal_error",
                    "message": "Try again later",
                    "log_id": "log-500",
                },
            }
        ).encode(),
    )
    responses = (
        [server_failure]
        if operation == "initialize"
        else [
            _json_response({"publish_id": "v_pub_file~v2.123", "upload_url": upload_url}),
            server_failure,
        ]
    )
    client = TikTokDraftUploadClient(_credentials(), FakeTransport(responses))

    with pytest.raises(TikTokTransportError) as captured:
        initialization = client.initialize_draft(video)
        client.upload_video(initialization, video)

    assert captured.value.ambiguous
    assert "internal_error" not in str(captured.value)


def test_status_accepts_documented_int64_public_post_ids_without_exposing_them() -> None:
    client = TikTokDraftUploadClient(
        _credentials(),
        FakeTransport(
            [
                _json_response(
                    {
                        "status": "PUBLISH_COMPLETE",
                        "uploaded_bytes": 128,
                        "publicaly_available_post_id": [7_456_123_456_789_123_456],
                    }
                )
            ]
        ),
    )

    status = client.fetch_status("v_pub_file~v2.123")

    assert status.publicly_available
    assert status.publicly_available_post_count == 1
    assert "7456123456789123456" not in repr(status)


def test_video_constraints_are_checked_before_transport(tmp_path: Path) -> None:
    transport = FakeTransport([])
    client = TikTokDraftUploadClient(_credentials(), transport)
    bad = tmp_path / "video.mp4"
    bad.write_bytes(b"not-an-mp4")

    with pytest.raises(TikTokConfigurationError, match="recognized MP4"):
        client.initialize_draft(bad)
    oversized = tmp_path / "oversized.mp4"
    with oversized.open("wb") as stream:
        stream.write(b"\x00\x00\x00\x18ftypisom")
        stream.seek(MAX_VIDEO_BYTES)
        stream.write(b"x")
    with pytest.raises(TikTokConfigurationError, match="between 1"):
        client.initialize_draft(oversized)
    assert not transport.requests


def test_upload_rejects_video_that_changed_after_initialization(tmp_path: Path) -> None:
    video = _mp4(tmp_path / "video.mp4")
    upload_url = "https://open-upload.tiktokapis.com/video/?upload_token=secret"
    transport = FakeTransport(
        [_json_response({"publish_id": "v_pub_file~v2.123", "upload_url": upload_url})]
    )
    client = TikTokDraftUploadClient(_credentials(), transport)
    initialization = client.initialize_draft(video)
    video.write_bytes(video.read_bytes() + b"changed")

    with pytest.raises(TikTokConfigurationError, match="size changed"):
        client.upload_video(initialization, video)
    assert len(transport.requests) == 1


@pytest.mark.parametrize("status", ["UNKNOWN_NEW_STATE", "done", ""])
def test_status_rejects_unknown_states(status: str) -> None:
    client = TikTokDraftUploadClient(
        _credentials(),
        FakeTransport([_json_response({"status": status, "publicaly_available_post_id": []})]),
    )

    with pytest.raises(TikTokTransportError):
        client.fetch_status("v_pub_file~v2.123")


def test_stream_body_type_and_length_are_enforced_without_network() -> None:
    class ShortStream(io.BytesIO):
        pass

    # Exercise the exact-stream helper directly: a short stream is ambiguous once
    # transmission begins. A fake connection avoids any external request.
    class Connection:
        def __init__(self) -> None:
            self.sent = bytearray()

        def send(self, data: bytes) -> None:
            self.sent.extend(data)

    connection = Connection()
    with pytest.raises(TikTokTransportError):
        HttpsTikTokTransport._send_exact(connection, ShortStream(b"short"), 10)
