"""Model pricing from models.dev (M3b).

Cost is derived from token usage: ``(prompt*in + completion*out) / 1_000_000`` where the
per-1M-token prices come from ``https://models.dev/api.json`` (USD / 1M tokens).

The table is fetched once per process and **degrades gracefully**: a fetch failure
leaves it empty (cost stays 0) and logs a warning; budget enforcement on steps/wall is
unaffected, and ``max_cost`` simply never trips. Lookup is by model id (scanning every
provider), because our gateway model names rarely line up with models.dev's provider
partition.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

MODELS_DEV_URL = "https://models.dev/api.json"
TIMEOUT_SECONDS = 30.0

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1M tokens."""

    input_per_1m: float
    output_per_1m: float


class PricingTable:
    """A model-id -> :class:`ModelPrice` table (injectable; tests bypass the network)."""

    def __init__(self, prices: Mapping[str, ModelPrice] | None = None) -> None:
        self._by_model: dict[str, ModelPrice] = {}
        self._loaded = prices is not None
        if prices:
            for model, price in prices.items():
                self._by_model[model] = price
                self._by_model.setdefault(model.lower(), price)

    @property
    def loaded(self) -> bool:
        return self._loaded

    def lookup(self, model: str | None) -> ModelPrice | None:
        """Return the price for ``model`` (exact or case-insensitive), else ``None``."""
        if not model:
            return None
        return self._by_model.get(model) or self._by_model.get(model.lower())

    def load_models(self, payload: object) -> int:
        """Populate from a models.dev ``api.json`` payload; return the entry count."""
        if not isinstance(payload, dict):
            return 0
        by_model: dict[str, ModelPrice] = {}
        for provider in payload.values():
            if not isinstance(provider, dict):
                continue
            models = provider.get("models")
            if not isinstance(models, dict):
                continue
            for model_id, entry in models.items():
                if not isinstance(model_id, str) or not isinstance(entry, dict):
                    continue
                cost = entry.get("cost")
                if not isinstance(cost, dict):
                    continue
                inp = cost.get("input")
                out = cost.get("output")
                if not (isinstance(inp, (int, float)) and isinstance(out, (int, float))):
                    continue
                price = ModelPrice(float(inp), float(out))
                by_model.setdefault(model_id, price)
                by_model.setdefault(model_id.lower(), price)
        self._by_model = by_model
        self._loaded = True
        return len(by_model)

    async def refresh(self, *, client: httpx.AsyncClient | None = None) -> int:
        """Fetch models.dev once; on failure keep the table and log (never raise)."""
        try:
            if client is None:
                async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as owned:
                    response = await owned.get(MODELS_DEV_URL)
            else:
                response = await client.get(MODELS_DEV_URL)
            response.raise_for_status()
            return self.load_models(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            _log.warning("could not load model pricing from models.dev: %s", exc)
            self._loaded = True
            return 0


__all__ = ["MODELS_DEV_URL", "ModelPrice", "PricingTable"]
