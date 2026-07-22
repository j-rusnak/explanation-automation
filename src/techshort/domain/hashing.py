from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: BaseModel | dict[str, Any] | list[Any] | str) -> str:
    def normalize(item: Any) -> Any:
        if isinstance(item, BaseModel):
            return item.model_dump(
                mode="json",
                exclude={"approval_hash", "approval_timestamp", "review_status"},
            )
        if isinstance(item, list):
            return [normalize(child) for child in item]
        if isinstance(item, dict):
            return {str(key): normalize(child) for key, child in item.items()}
        return item

    payload = normalize(value)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return sha256_bytes(encoded)
