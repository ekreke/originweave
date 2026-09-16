"""Search capability providers.

Live search is not implemented until M3; providers validate credentials and
raise a clear error so the offline (cache) path is the only usable one for now.
Credentials are read from environment variables only.
"""

from __future__ import annotations

import os

from .base import MissingCredentialError, ProviderUnavailableError, SearchResult

ENV_VARS: dict[str, str] = {
    "exa": "EXA_API_KEY",
    "parallel": "PARALLEL_API_KEY",
}


class _LiveSearch:
    name: str
    env_var: str

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get(self.env_var)

    def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        if not self._api_key:
            raise MissingCredentialError(f"{self.env_var} is not set")
        raise ProviderUnavailableError(
            f"live {self.name} search is not implemented until M3; "
            "run offline (LIVE=0) against recorded responses"
        )


class ExaSearch(_LiveSearch):
    name = "exa"
    env_var = ENV_VARS["exa"]


class ParallelSearch(_LiveSearch):
    name = "parallel"
    env_var = ENV_VARS["parallel"]


def credential_env(name: str) -> str | None:
    """Return the environment variable backing ``name``, if any."""
    return ENV_VARS.get(name)
