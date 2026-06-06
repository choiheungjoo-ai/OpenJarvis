"""Provider registry: registration, active selection, and hot-swap.

Active-provider resolution for a capability, highest precedence first:

    1. once     — a one-shot override; consumed by the next get_active
    2. session  — set this process; survives until restart
    3. permanent— persisted in provider_state; survives restart
    4. default  — lowest cost_model priority among registered providers

``swap`` writes to whichever layer the scope names. ``get_active`` reads them
in the order above. ``session_factory`` is only needed for the permanent
scope; pass it once at construction (e.g. ``newton.db.get_session``).
"""

from __future__ import annotations

from typing import Any

from newton.providers.base import Provider, ProviderResult

_SCOPES = ("once", "session", "permanent")


class ProviderError(Exception):
    """Registry-level error (unknown capability/provider, bad scope)."""


class ProviderRegistry:
    def __init__(self, session_factory: Any = None) -> None:
        # capability -> {provider_name -> Provider}
        self._providers: dict[str, dict[str, Provider]] = {}
        self._session_factory = session_factory
        self._session_active: dict[str, str] = {}  # capability -> provider
        self._once: dict[str, str] = {}  # capability -> provider (consumed)

    # -- registration ---------------------------------------------------------

    def register(self, provider: Provider) -> None:
        """Register a provider under its capability. Duplicate (capability,
        name) raises ``ProviderError``."""
        cap = provider.capability
        bucket = self._providers.setdefault(cap, {})
        if provider.name in bucket:
            raise ProviderError(f"provider already registered: {cap}/{provider.name}")
        bucket[provider.name] = provider

    def _bucket(self, capability: str) -> dict[str, Provider]:
        try:
            return self._providers[capability]
        except KeyError:
            raise ProviderError(f"unknown capability: {capability!r}") from None

    def list_providers(self, capability: str) -> list[Provider]:
        """Providers for a capability, default-priority order (free first)."""
        bucket = self._bucket(capability)
        return sorted(bucket.values(), key=lambda p: (p._priority(), p.name))

    def capabilities(self) -> list[str]:
        return sorted(self._providers)

    # -- active selection -----------------------------------------------------

    def _permanent_choice(self, capability: str) -> str | None:
        if self._session_factory is None:
            return None
        from newton.models.provider_state import ProviderState

        with self._session_factory() as session:
            row = session.get(ProviderState, capability)
            return row.active_provider if row is not None else None

    def _default_choice(self, capability: str) -> str:
        providers = self.list_providers(capability)
        if not providers:
            raise ProviderError(f"no providers for capability: {capability!r}")
        return providers[0].name

    def resolve_active_name(self, capability: str, *, consume_once: bool = True) -> str:
        """Name of the provider that would serve the next call.

        Set ``consume_once=False`` to peek without consuming a one-shot
        override (used by telemetry/listing).
        """
        bucket = self._bucket(capability)

        if capability in self._once:
            name = self._once[capability]
            if consume_once:
                self._once.pop(capability, None)
            if name in bucket:
                return name
            # Stale one-shot (provider removed): fall through.

        if capability in self._session_active:
            name = self._session_active[capability]
            if name in bucket:
                return name

        perm = self._permanent_choice(capability)
        if perm is not None and perm in bucket:
            return perm

        return self._default_choice(capability)

    def get_active(self, capability: str) -> Provider:
        """Resolve and return the active provider, consuming any one-shot."""
        name = self.resolve_active_name(capability, consume_once=True)
        return self._bucket(capability)[name]

    # -- swap -----------------------------------------------------------------

    def swap(self, capability: str, provider_name: str, scope: str = "session") -> None:
        """Change the active provider for a capability.

        scope: 'once' (next call) | 'session' (this process) |
        'permanent' (persisted in provider_state).
        """
        if scope not in _SCOPES:
            raise ProviderError(f"bad scope {scope!r}; expected one of {_SCOPES}")
        bucket = self._bucket(capability)
        if provider_name not in bucket:
            raise ProviderError(
                f"unknown provider {provider_name!r} for capability {capability!r}"
            )

        if scope == "once":
            self._once[capability] = provider_name
        elif scope == "session":
            self._session_active[capability] = provider_name
        else:  # permanent
            if self._session_factory is None:
                raise ProviderError(
                    "permanent swap requires a session_factory at construction"
                )
            from newton.models.provider_state import ProviderState

            with self._session_factory() as session:
                row = session.get(ProviderState, capability)
                if row is None:
                    session.add(
                        ProviderState(
                            capability=capability, active_provider=provider_name
                        )
                    )
                else:
                    row.active_provider = provider_name

    def clear_session_swap(self, capability: str) -> None:
        """Drop a session-scope override (falls back to permanent/default)."""
        self._session_active.pop(capability, None)
        self._once.pop(capability, None)

    # -- execution + telemetry ------------------------------------------------

    async def execute(self, capability: str, request: dict[str, Any]) -> ProviderResult:
        """Run a request through the active provider, tagging the result."""
        provider = self.get_active(capability)
        result = await provider.execute(request)
        provider.used_this_session += 1
        if result.provider_name is None:
            result = result.model_copy(update={"provider_name": provider.name})
        return result

    def telemetry(self) -> dict[str, Any]:
        """Per-capability snapshot: active provider + per-provider usage."""
        out: dict[str, Any] = {}
        for cap in self.capabilities():
            active = self.resolve_active_name(cap, consume_once=False)
            out[cap] = {
                "active": active,
                "providers": {
                    p.name: {
                        "cost_model": p.cost_model.value,
                        "free_quota": p.free_quota,
                        "used_this_session": p.used_this_session,
                    }
                    for p in self.list_providers(cap)
                },
            }
        return out


__all__ = ["ProviderError", "ProviderRegistry"]
