"""Recorded-response cache for offline replay.

Each capability call is stored as a single JSON file keyed by a hash of the
request, so replay can look it up directly without touching the network:

    <run-dir>/capabilities/<provider>/<request_hash>.json

The file holds the provider, operation, request params, the response, and a
recording timestamp.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import CacheMissError


def request_key(provider: str, op: str, params: Mapping[str, Any]) -> str:
    """Return a stable short hash for a capability request."""
    payload = json.dumps(
        {"provider": provider, "op": op, "params": params},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class ResponseCache:
    """File-per-call store of recorded capability responses."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, provider: str, op: str, params: Mapping[str, Any]) -> Path:
        return self._root / provider / f"{request_key(provider, op, params)}.json"

    def read(self, provider: str, op: str, params: Mapping[str, Any]) -> dict[str, Any] | None:
        path = self.path_for(provider, op, params)
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise CacheMissError(f"malformed cache entry: {path}")
        return data

    def write(
        self,
        provider: str,
        op: str,
        params: Mapping[str, Any],
        response: Any,
        *,
        recorded_at: str | None = None,
    ) -> Path:
        path = self.path_for(provider, op, params)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "provider": provider,
            "op": op,
            "params": dict(params),
            "response": response,
            "recordedAt": recorded_at or datetime.now(UTC).isoformat(),
        }
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        return path
