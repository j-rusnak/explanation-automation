"""Bounded, redacting client for TikTok's official draft-upload API.

The client intentionally supports the ``FILE_UPLOAD`` inbox flow only.  A video is
uploaded to TikTok's draft inbox; this module never makes a public-post request.
The conservative 64,000,000-byte limit keeps each upload to one API chunk and
avoids retry or partial-chunk semantics whose outcome could be ambiguous.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import re
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal, Protocol, cast
from urllib.parse import SplitResult, urlsplit

API_HOST = "open.tiktokapis.com"
UPLOAD_HOST = "open-upload.tiktokapis.com"
API_ORIGIN = f"https://{API_HOST}"
INITIALIZE_PATH = "/v2/post/publish/inbox/video/init/"
STATUS_PATH = "/v2/post/publish/status/fetch/"
REQUIRED_SCOPE = "video.upload"

# One conservative single chunk. TikTok's FILE_UPLOAD API documents 64 MB as the
# maximum chunk size; using decimal MB avoids accidentally exceeding that bound.
MAX_VIDEO_BYTES = 64_000_000
MAX_API_RESPONSE_BYTES = 1_000_000
MAX_UPLOAD_RESPONSE_BYTES = 64_000
HARD_MAX_RESPONSE_BYTES = 1_000_000
API_TIMEOUT_SECONDS = 30.0
UPLOAD_TIMEOUT_SECONDS = 180.0

_TOKEN_ENV = "TECHSHORT_TIKTOK_ACCESS_TOKEN"  # noqa: S105 - environment variable name
_OPEN_ID_ENV = "TECHSHORT_TIKTOK_OPEN_ID"
_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_PUBLISH_ID = re.compile(r"^[A-Za-z0-9._~:-]{1,200}$")
_STATUS = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_UPLOAD_URL_IN_TEXT = re.compile(r"https://open-upload\.tiktokapis\.com/[^\s\"'<>]+", re.IGNORECASE)

TikTokPublishState = Literal[
    "PROCESSING_UPLOAD",
    "PROCESSING_DOWNLOAD",
    "SEND_TO_USER_INBOX",
    "PUBLISH_COMPLETE",
    "FAILED",
]
_KNOWN_STATES: frozenset[str] = frozenset(
    {
        "PROCESSING_UPLOAD",
        "PROCESSING_DOWNLOAD",
        "SEND_TO_USER_INBOX",
        "PUBLISH_COMPLETE",
        "FAILED",
    }
)


class TikTokConfigurationError(ValueError):
    """A local credential, path, or request constraint is invalid."""


class TikTokTransportError(RuntimeError):
    """A network/protocol failure for which the remote outcome may be ambiguous."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        self.ambiguous = True
        super().__init__(
            f"TikTok transport failed during {operation}; the remote outcome is ambiguous"
        )


class TikTokApiError(RuntimeError):
    """A definite rejection returned by TikTok's API."""

    def __init__(
        self,
        *,
        operation: str,
        code: str,
        message: str,
        http_status: int,
        log_id: str | None = None,
    ) -> None:
        self.operation = operation
        self.code = code
        self.api_message = message
        self.http_status = http_status
        self.log_id = log_id
        suffix = f" (log_id={log_id})" if log_id else ""
        super().__init__(
            f"TikTok rejected {operation}: {code}: {message} [HTTP {http_status}]{suffix}"
        )


@dataclass(frozen=True, slots=True)
class TikTokCredentialDiagnostics:
    """Secret-free credential readiness information."""

    configured: bool
    required_scope: str
    account_subject_hash: str | None
    missing_environment_variables: tuple[str, ...] = ()
    invalid_environment_variables: tuple[str, ...] = ()


class TikTokCredentials:
    """TikTok credentials whose string representations are always redacted."""

    __slots__ = ("_access_token", "_open_id")

    def __init__(self, *, access_token: str, open_id: str) -> None:
        invalid = self._invalid_values(access_token=access_token, open_id=open_id)
        if invalid:
            names = ", ".join(invalid)
            raise TikTokConfigurationError(f"invalid TikTok credential value(s): {names}")
        self._access_token = access_token
        self._open_id = open_id

    @classmethod
    def from_env(cls, environment: Mapping[str, str]) -> TikTokCredentials:
        """Load only from the explicit mapping; the process environment is never read."""

        diagnostics = cls.diagnose_env(environment)
        if diagnostics.missing_environment_variables:
            names = ", ".join(diagnostics.missing_environment_variables)
            raise TikTokConfigurationError(f"missing TikTok environment variable(s): {names}")
        if diagnostics.invalid_environment_variables:
            names = ", ".join(diagnostics.invalid_environment_variables)
            raise TikTokConfigurationError(f"invalid TikTok environment variable(s): {names}")
        return cls(
            access_token=environment[_TOKEN_ENV],
            open_id=environment[_OPEN_ID_ENV],
        )

    @classmethod
    def diagnose_env(cls, environment: Mapping[str, str]) -> TikTokCredentialDiagnostics:
        missing = tuple(
            name
            for name in (_TOKEN_ENV, _OPEN_ID_ENV)
            if not isinstance(environment.get(name), str) or not environment.get(name)
        )
        invalid: tuple[str, ...] = ()
        account_hash: str | None = None
        if not missing:
            token = environment[_TOKEN_ENV]
            open_id = environment[_OPEN_ID_ENV]
            invalid = cls._invalid_values(access_token=token, open_id=open_id)
            if _OPEN_ID_ENV not in invalid:
                account_hash = cls._subject_hash(open_id)
        return TikTokCredentialDiagnostics(
            configured=not missing and not invalid,
            required_scope=REQUIRED_SCOPE,
            account_subject_hash=account_hash,
            missing_environment_variables=missing,
            invalid_environment_variables=invalid,
        )

    @staticmethod
    def _invalid_values(*, access_token: str, open_id: str) -> tuple[str, ...]:
        invalid: list[str] = []
        if not _is_bounded_header_value(access_token, maximum=8192):
            invalid.append(_TOKEN_ENV)
        if not _is_bounded_identifier(open_id, maximum=512):
            invalid.append(_OPEN_ID_ENV)
        return tuple(invalid)

    @staticmethod
    def _subject_hash(open_id: str) -> str:
        material = f"techshort:tiktok-account:{open_id}".encode()
        return hashlib.sha256(material).hexdigest()

    @property
    def account_subject_hash(self) -> str:
        return self._subject_hash(self._open_id)

    def diagnostics(self) -> TikTokCredentialDiagnostics:
        return TikTokCredentialDiagnostics(
            configured=True,
            required_scope=REQUIRED_SCOPE,
            account_subject_hash=self.account_subject_hash,
        )

    def _authorization_header(self) -> str:
        return f"Bearer {self._access_token}"

    def _redact(self, value: str) -> str:
        redacted = value.replace(self._access_token, "<redacted-access-token>")
        redacted = redacted.replace(self._open_id, "<redacted-open-id>")
        return _UPLOAD_URL_IN_TEXT.sub("<redacted-upload-url>", redacted)

    def __repr__(self) -> str:
        return (
            "TikTokCredentials(access_token=<redacted>, open_id=<redacted>, "
            f"account_subject_hash={self.account_subject_hash!r})"
        )

    __str__ = __repr__


@dataclass(frozen=True, slots=True, repr=False)
class TikTokHttpResponse:
    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()

    def __repr__(self) -> str:
        return (
            "TikTokHttpResponse("
            f"status_code={self.status_code}, body=<{len(self.body)} bytes>, "
            f"headers=<{len(self.headers)} entries>)"
        )


class TikTokTransport(Protocol):
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
    ) -> TikTokHttpResponse: ...


class _SendConnection(Protocol):
    def send(self, data: bytes) -> None: ...


class HttpsTikTokTransport:
    """Direct TLS transport with fixed hosts, no proxy use, and no redirects."""

    _allowed_hosts = frozenset({API_HOST, UPLOAD_HOST})

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
        if method not in {"POST", "PUT"}:
            raise TikTokConfigurationError("TikTok transport method is not allowlisted")
        parsed = self._validate_url(url, method=method)
        validated_headers = self._validate_headers(headers, body_length=body_length)
        if not 0 < timeout_seconds <= UPLOAD_TIMEOUT_SECONDS:
            raise TikTokConfigurationError("TikTok transport timeout is out of bounds")
        if not 0 < max_response_bytes <= HARD_MAX_RESPONSE_BYTES:
            raise TikTokConfigurationError("TikTok response bound is out of bounds")
        if not 0 <= body_length <= MAX_VIDEO_BYTES:
            raise TikTokConfigurationError("TikTok request body length is out of bounds")
        if isinstance(body, bytes) and len(body) != body_length:
            raise TikTokConfigurationError("TikTok request body length does not match bytes")

        context = ssl.create_default_context()
        hostname = parsed.hostname
        if hostname is None:  # Kept explicit for static typing after validated parsing.
            raise TikTokConfigurationError("TikTok HTTPS URL has no hostname")
        connection = http.client.HTTPSConnection(
            hostname,
            port=parsed.port or 443,
            timeout=timeout_seconds,
            context=context,
        )
        response: http.client.HTTPResponse | None = None
        try:
            target = parsed.path or "/"
            if parsed.query:
                target = f"{target}?{parsed.query}"
            connection.putrequest(method, target, skip_accept_encoding=True)
            for name, value in validated_headers.items():
                connection.putheader(name, value)
            connection.putheader("Connection", "close")
            connection.endheaders()
            self._send_exact(connection, body, body_length)
            response = connection.getresponse()
            response_body = response.read(max_response_bytes + 1)
            if len(response_body) > max_response_bytes:
                raise TikTokTransportError("bounded HTTPS response read")
            return TikTokHttpResponse(
                status_code=response.status,
                body=response_body,
                headers=tuple(response.getheaders()),
            )
        except TikTokConfigurationError:
            raise
        except TikTokTransportError:
            raise
        except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException):
            raise TikTokTransportError("HTTPS request") from None
        finally:
            if response is not None:
                response.close()
            connection.close()

    @classmethod
    def _validate_url(cls, url: str, *, method: Literal["POST", "PUT"]) -> SplitResult:
        if not isinstance(url, str) or not url or len(url) > 4096:
            raise TikTokConfigurationError("TikTok HTTPS URL is invalid")
        if any(character in url for character in ("\r", "\n", "\x00")):
            raise TikTokConfigurationError("TikTok HTTPS URL contains control characters")
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            raise TikTokConfigurationError("TikTok HTTPS URL is malformed") from None
        if (
            parsed.scheme != "https"
            or parsed.hostname not in cls._allowed_hosts
            or port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise TikTokConfigurationError("TikTok HTTPS URL is not an allowlisted destination")
        if parsed.hostname == API_HOST and (
            method != "POST"
            or parsed.path not in {INITIALIZE_PATH, STATUS_PATH}
            or bool(parsed.query)
        ):
            raise TikTokConfigurationError("TikTok API endpoint is not allowlisted")
        if parsed.hostname == UPLOAD_HOST and (method != "PUT" or not parsed.query):
            raise TikTokConfigurationError("TikTok upload endpoint is not allowlisted")
        return parsed

    @staticmethod
    def _validate_headers(headers: Mapping[str, str], *, body_length: int) -> dict[str, str]:
        validated: dict[str, str] = {}
        lowered: set[str] = set()
        for name, value in headers.items():
            if not isinstance(name, str) or _HEADER_NAME.fullmatch(name) is None:
                raise TikTokConfigurationError("TikTok request header name is invalid")
            if not isinstance(value, str) or any(item in value for item in ("\r", "\n", "\x00")):
                raise TikTokConfigurationError("TikTok request header value is invalid")
            normalized = name.casefold()
            if normalized in lowered:
                raise TikTokConfigurationError("TikTok request headers contain a duplicate")
            if normalized in {"host", "transfer-encoding", "connection"}:
                raise TikTokConfigurationError("TikTok request header is managed by the transport")
            lowered.add(normalized)
            validated[name] = value
        content_length = next(
            (value for name, value in validated.items() if name.casefold() == "content-length"),
            None,
        )
        if content_length != str(body_length):
            raise TikTokConfigurationError("TikTok Content-Length is missing or incorrect")
        return validated

    @staticmethod
    def _send_exact(
        connection: _SendConnection,
        body: bytes | BinaryIO,
        body_length: int,
    ) -> None:
        if isinstance(body, bytes):
            if body:
                connection.send(body)
            return
        remaining = body_length
        while remaining:
            chunk = body.read(min(64 * 1024, remaining))
            if not isinstance(chunk, bytes) or not chunk:
                raise TikTokTransportError("streaming request body")
            connection.send(chunk)
            remaining -= len(chunk)
        if body.read(1):
            raise TikTokTransportError("streaming request body")


@dataclass(frozen=True, slots=True)
class TikTokDraftInitialization:
    publish_id: str
    video_size: int
    upload_host: str


@dataclass(frozen=True, slots=True)
class TikTokUploadReceipt:
    publish_id: str
    bytes_uploaded: int
    http_status: int


@dataclass(frozen=True, slots=True)
class TikTokPublishStatus:
    publish_id: str
    status: TikTokPublishState
    uploaded_bytes: int | None
    publicly_available: bool
    publicly_available_post_count: int
    fail_reason: str | None

    @property
    def terminal(self) -> bool:
        return self.status in {"SEND_TO_USER_INBOX", "PUBLISH_COMPLETE", "FAILED"}


class TikTokDraftUploadApi(Protocol):
    @property
    def account_subject_hash(self) -> str: ...

    def initialize_draft(self, video_path: str | Path) -> TikTokDraftInitialization: ...

    def upload_video(
        self, initialization: TikTokDraftInitialization, video_path: str | Path
    ) -> TikTokUploadReceipt: ...

    def fetch_status(self, publish_id: str) -> TikTokPublishStatus: ...


class TikTokDraftUploadClient:
    """Official API client for a human-reviewed video-to-draft transfer."""

    def __init__(
        self,
        credentials: TikTokCredentials,
        transport: TikTokTransport | None = None,
    ) -> None:
        self._credentials = credentials
        self._transport = transport if transport is not None else HttpsTikTokTransport()
        # Upload URLs are bearer-like, short-lived capabilities. They never leave this
        # client in a result object and are consumed before the one permitted upload.
        self._pending_upload_urls: dict[str, str] = {}

    @property
    def account_subject_hash(self) -> str:
        return self._credentials.account_subject_hash

    def diagnostics(self) -> TikTokCredentialDiagnostics:
        return self._credentials.diagnostics()

    def initialize_draft(self, video_path: str | Path) -> TikTokDraftInitialization:
        path, video_size = _validate_video(video_path)
        del path
        request_body = _json_bytes(
            {
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": video_size,
                    "total_chunk_count": 1,
                }
            }
        )
        response = self._request(
            operation="draft initialization",
            method="POST",
            url=f"{API_ORIGIN}{INITIALIZE_PATH}",
            headers=self._api_headers(len(request_body)),
            body=request_body,
            body_length=len(request_body),
            timeout_seconds=API_TIMEOUT_SECONDS,
            max_response_bytes=MAX_API_RESPONSE_BYTES,
        )
        data = self._successful_api_data(response, operation="draft initialization")
        publish_id = _required_publish_id(data.get("publish_id"), operation="draft initialization")
        upload_url = _required_upload_url(data.get("upload_url"))
        if publish_id in self._pending_upload_urls:
            raise TikTokTransportError("draft initialization response validation")
        self._pending_upload_urls[publish_id] = upload_url
        return TikTokDraftInitialization(
            publish_id=publish_id,
            video_size=video_size,
            upload_host=UPLOAD_HOST,
        )

    def upload_video(
        self, initialization: TikTokDraftInitialization, video_path: str | Path
    ) -> TikTokUploadReceipt:
        path, video_size = _validate_video(video_path)
        if video_size != initialization.video_size:
            raise TikTokConfigurationError("video size changed after TikTok draft initialization")
        _required_publish_id(initialization.publish_id, operation="video upload")
        if initialization.upload_host != UPLOAD_HOST:
            raise TikTokConfigurationError("TikTok upload initialization host is invalid")
        upload_url = self._pending_upload_urls.pop(initialization.publish_id, None)
        if upload_url is None:
            raise TikTokConfigurationError("TikTok upload initialization is not active")
        upload_url = _required_upload_url(upload_url)
        headers = {
            "Content-Type": "video/mp4",
            "Content-Length": str(video_size),
            "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
            "User-Agent": "techshort/0.1 official-tiktok-draft-upload",
        }
        with path.open("rb") as stream:
            response = self._request(
                operation="video upload",
                method="PUT",
                url=upload_url,
                headers=headers,
                body=stream,
                body_length=video_size,
                timeout_seconds=UPLOAD_TIMEOUT_SECONDS,
                max_response_bytes=MAX_UPLOAD_RESPONSE_BYTES,
            )
        # This client deliberately sends exactly one chunk. TikTok documents 201 as
        # the completed-upload response and 206 as a successful *partial* chunk, so
        # accepting an arbitrary 2xx response could misreport an incomplete upload.
        if response.status_code != 201:
            raise TikTokApiError(
                operation="video upload",
                code=f"upload_http_{response.status_code}",
                message="upload endpoint did not confirm a complete single-chunk upload",
                http_status=response.status_code,
            )
        return TikTokUploadReceipt(
            publish_id=initialization.publish_id,
            bytes_uploaded=video_size,
            http_status=response.status_code,
        )

    def fetch_status(self, publish_id: str) -> TikTokPublishStatus:
        publish_id = _required_publish_id(publish_id, operation="status fetch")
        request_body = _json_bytes({"publish_id": publish_id})
        response = self._request(
            operation="status fetch",
            method="POST",
            url=f"{API_ORIGIN}{STATUS_PATH}",
            headers=self._api_headers(len(request_body)),
            body=request_body,
            body_length=len(request_body),
            timeout_seconds=API_TIMEOUT_SECONDS,
            max_response_bytes=MAX_API_RESPONSE_BYTES,
        )
        data = self._successful_api_data(response, operation="status fetch")
        status_value = data.get("status")
        if not isinstance(status_value, str) or _STATUS.fullmatch(status_value) is None:
            raise TikTokTransportError("status response validation")
        if status_value not in _KNOWN_STATES:
            raise TikTokTransportError("status response validation")
        status = cast(TikTokPublishState, status_value)
        uploaded_bytes_value = data.get("uploaded_bytes")
        if uploaded_bytes_value is not None and (
            not isinstance(uploaded_bytes_value, int)
            or isinstance(uploaded_bytes_value, bool)
            or not 0 <= uploaded_bytes_value <= MAX_VIDEO_BYTES
        ):
            raise TikTokTransportError("status response validation")
        public_ids = data.get("publicaly_available_post_id", [])
        if not isinstance(public_ids, list) or len(public_ids) > 100:
            raise TikTokTransportError("status response validation")
        if any(not _valid_remote_post_id(item) for item in public_ids):
            raise TikTokTransportError("status response validation")
        fail_reason_value = data.get("fail_reason")
        fail_reason: str | None = None
        if fail_reason_value is not None:
            fail_reason = self._safe_remote_text(fail_reason_value, maximum=500)
        if status == "FAILED" and not fail_reason:
            fail_reason = "TikTok reported an unspecified processing failure"
        return TikTokPublishStatus(
            publish_id=publish_id,
            status=status,
            uploaded_bytes=uploaded_bytes_value,
            publicly_available=bool(public_ids),
            publicly_available_post_count=len(public_ids),
            fail_reason=fail_reason,
        )

    def _api_headers(self, body_length: int) -> dict[str, str]:
        return {
            "Authorization": self._credentials._authorization_header(),
            "Content-Type": "application/json; charset=UTF-8",
            "Content-Length": str(body_length),
            "User-Agent": "techshort/0.1 official-tiktok-draft-upload",
        }

    def _request(
        self,
        *,
        operation: str,
        method: Literal["POST", "PUT"],
        url: str,
        headers: Mapping[str, str],
        body: bytes | BinaryIO,
        body_length: int,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> TikTokHttpResponse:
        try:
            response = self._transport.request(
                method=method,
                url=url,
                headers=headers,
                body=body,
                body_length=body_length,
                timeout_seconds=timeout_seconds,
                max_response_bytes=max_response_bytes,
            )
        except TikTokConfigurationError:
            raise
        except Exception:
            # Custom transports are injectable for offline tests. Never propagate their
            # messages because they may contain an upload URL or Authorization header.
            raise TikTokTransportError(operation) from None
        if not isinstance(response, TikTokHttpResponse):
            raise TikTokTransportError(operation)
        if (
            not isinstance(response.status_code, int)
            or isinstance(response.status_code, bool)
            or not 100 <= response.status_code <= 599
            or len(response.body) > max_response_bytes
        ):
            raise TikTokTransportError(operation)
        return response

    def _successful_api_data(
        self, response: TikTokHttpResponse, *, operation: str
    ) -> dict[str, object]:
        payload: dict[str, object] | None = None
        try:
            payload = _strict_json_object(response.body)
        except (UnicodeDecodeError, ValueError, TypeError):
            if 200 <= response.status_code < 300:
                raise TikTokTransportError(f"{operation} response validation") from None
        if payload is not None:
            error = payload.get("error")
            if not isinstance(error, dict):
                raise TikTokTransportError(f"{operation} response validation")
            code = self._safe_remote_code(error.get("code"))
            message = self._safe_remote_text(error.get("message", ""), maximum=500)
            log_id_value = error.get("log_id")
            log_id = (
                self._safe_remote_text(log_id_value, maximum=200)
                if log_id_value is not None
                else None
            )
            if code != "ok":
                raise TikTokApiError(
                    operation=operation,
                    code=code,
                    message=message or "request rejected",
                    http_status=response.status_code,
                    log_id=log_id,
                )
        if not 200 <= response.status_code < 300:
            raise TikTokApiError(
                operation=operation,
                code=f"http_{response.status_code}",
                message="API returned a non-success response",
                http_status=response.status_code,
            )
        if payload is None:
            raise TikTokTransportError(f"{operation} response validation")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise TikTokTransportError(f"{operation} response validation")
        if any(not isinstance(key, str) for key in data):
            raise TikTokTransportError(f"{operation} response validation")
        return cast(dict[str, object], data)

    def _safe_remote_code(self, value: object) -> str:
        if not isinstance(value, str) or not 1 <= len(value) <= 100:
            raise TikTokTransportError("API error response validation")
        if any(ord(character) < 0x20 or ord(character) > 0x7E for character in value):
            raise TikTokTransportError("API error response validation")
        return self._credentials._redact(value)

    def _safe_remote_text(self, value: object, *, maximum: int) -> str:
        if not isinstance(value, str) or len(value) > maximum:
            raise TikTokTransportError("API text response validation")
        if any(character in value for character in ("\r", "\n", "\x00")):
            raise TikTokTransportError("API text response validation")
        return self._credentials._redact(value)


def _is_bounded_header_value(value: object, *, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and value == value.strip()
        and all(0x21 <= ord(character) <= 0x7E for character in value)
    )


def _is_bounded_identifier(value: object, *, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and value == value.strip()
        and all(
            ord(character) >= 0x20 and character not in {"\r", "\n", "\x00"} for character in value
        )
    )


def _validate_video(video_path: str | Path) -> tuple[Path, int]:
    path = Path(video_path)
    try:
        if path.is_symlink() or not path.is_file():
            raise TikTokConfigurationError("TikTok upload requires a regular local MP4 file")
        size = path.stat().st_size
        with path.open("rb") as stream:
            header = stream.read(12)
    except TikTokConfigurationError:
        raise
    except OSError:
        raise TikTokConfigurationError("TikTok upload MP4 cannot be read") from None
    if path.suffix.casefold() != ".mp4" or len(header) < 12 or header[4:8] != b"ftyp":
        raise TikTokConfigurationError("TikTok upload file is not a recognized MP4")
    if not 0 < size <= MAX_VIDEO_BYTES:
        raise TikTokConfigurationError(
            f"TikTok upload MP4 must be between 1 and {MAX_VIDEO_BYTES} bytes"
        )
    return path, size


def _required_publish_id(value: object, *, operation: str) -> str:
    if not isinstance(value, str) or _PUBLISH_ID.fullmatch(value) is None:
        raise TikTokTransportError(f"{operation} response validation")
    return value


def _required_upload_url(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise TikTokTransportError("draft initialization response validation")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise TikTokTransportError("draft initialization response validation") from None
    if (
        parsed.scheme != "https"
        or parsed.hostname != UPLOAD_HOST
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not parsed.query
        or any(character in value for character in ("\r", "\n", "\x00"))
    ):
        raise TikTokTransportError("draft initialization response validation")
    return value


def _valid_remote_post_id(value: object) -> bool:
    """Validate but never persist public post IDs returned by status polling."""

    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 < value <= 9_223_372_036_854_775_807
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,18}", value) is not None


def _json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


def _strict_json_object(raw: bytes) -> dict[str, object]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"invalid JSON constant: {value}")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    decoded = raw.decode("utf-8")
    parsed = cast(
        object,
        json.loads(
            decoded,
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        ),
    )
    if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
        raise TypeError("TikTok response must be a JSON object")
    return cast(dict[str, object], parsed)
