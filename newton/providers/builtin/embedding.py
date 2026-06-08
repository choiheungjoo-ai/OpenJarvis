"""embedding provider — capability ``embedding.encode``.

Exposes EmbeddingService through the provider registry so the embedding
backend can be inspected and (later) hot-swapped like any other capability.
Self-registers via ``@register_provider``.

Request shape:  {"texts": list[str]}  (or {"text": str} for one)
Result data:    {"vectors": list[list[float]], "dimension": int}
"""

from __future__ import annotations

from typing import Any

from newton.providers.base import CostModel, Provider, ProviderResult
from newton.providers.registration import register_provider
from newton.vault.embeddings import EmbeddingService


@register_provider
class EmbeddingProvider(Provider):
    """Dense text embeddings via the configured EmbeddingService backend."""

    name = "bge_m3_tei"
    capability = "embedding.encode"
    cost_model = CostModel.FREE  # self-hosted
    free_quota = None

    def __init__(self) -> None:
        super().__init__()
        self._service: EmbeddingService | None = None

    def _get_service(self) -> EmbeddingService:
        if self._service is None:
            self._service = EmbeddingService.from_config()
        return self._service

    async def execute(self, request: dict[str, Any]) -> ProviderResult:
        texts = request.get("texts")
        if texts is None and "text" in request:
            texts = [request["text"]]
        if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
            return ProviderResult(
                ok=False,
                error="request must include 'texts' (list[str]) or 'text' (str)",
                provider_name=self.name,
            )

        service = self._get_service()
        try:
            vectors = await service.encode(texts)
            dimension = await service.dimension()
        except Exception as e:  # noqa: BLE001 — surface as a provider error
            return ProviderResult(
                ok=False, error=f"{type(e).__name__}: {e}", provider_name=self.name
            )

        self.used_this_session += len(texts)
        return ProviderResult(
            ok=True,
            data={"vectors": vectors, "dimension": dimension},
            provider_name=self.name,
            usage={"texts": len(texts)},
        )

    async def health_check(self) -> bool:
        try:
            return await self._get_service().health()
        except Exception:  # noqa: BLE001
            return False


__all__ = ["EmbeddingProvider"]
