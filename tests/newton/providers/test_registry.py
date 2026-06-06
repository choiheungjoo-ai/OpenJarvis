"""Step 2.7 — tests for ProviderRegistry and demo providers."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import newton.models  # noqa: F401  (populate metadata)
from newton.models.base import Base
from newton.providers import (
    CostModel,
    ProviderRegistry,
    register_demo_providers,
)
from newton.providers.base import Provider, ProviderResult
from newton.providers.builtin.echo_loud import EchoLoudProvider
from newton.providers.builtin.echo_quiet import EchoQuietProvider
from newton.providers.registry import ProviderError


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Maker = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def factory():
        s = Maker()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    return factory


def _reg(session_factory=None) -> ProviderRegistry:
    r = ProviderRegistry(session_factory=session_factory)
    register_demo_providers(r)
    return r


# -- registration -------------------------------------------------------------


def test_register_and_list():
    r = _reg()
    names = [p.name for p in r.list_providers("demo.echo")]
    # default priority: free (echo_loud) before free_tier (echo_quiet)
    assert names == ["echo_loud", "echo_quiet"]


def test_duplicate_registration_raises():
    r = _reg()
    with pytest.raises(ProviderError, match="already registered"):
        r.register(EchoLoudProvider())


def test_unknown_capability_raises():
    r = _reg()
    with pytest.raises(ProviderError, match="unknown capability"):
        r.list_providers("nope.capability")


def test_capabilities_listing():
    r = _reg()
    assert r.capabilities() == ["demo.echo"]


# -- default selection --------------------------------------------------------


def test_default_active_is_cheapest():
    r = _reg()
    assert r.resolve_active_name("demo.echo", consume_once=False) == "echo_loud"


@pytest.mark.asyncio
async def test_execute_uses_default():
    r = _reg()
    result = await r.execute("demo.echo", {"text": "Hello"})
    assert result.ok
    assert result.data == {"text": "HELLO"}  # echo_loud uppercases
    assert result.provider_name == "echo_loud"


# -- session swap -------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_swap_changes_active():
    r = _reg()
    r.swap("demo.echo", "echo_quiet", scope="session")
    result = await r.execute("demo.echo", {"text": "Hello"})
    assert result.data == {"text": "hello"}  # echo_quiet lowercases
    assert result.provider_name == "echo_quiet"


def test_clear_session_swap_reverts_to_default():
    r = _reg()
    r.swap("demo.echo", "echo_quiet", scope="session")
    assert r.resolve_active_name("demo.echo", consume_once=False) == "echo_quiet"
    r.clear_session_swap("demo.echo")
    assert r.resolve_active_name("demo.echo", consume_once=False) == "echo_loud"


# -- once swap ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_once_swap_applies_then_reverts():
    r = _reg()
    r.swap("demo.echo", "echo_quiet", scope="once")
    first = await r.execute("demo.echo", {"text": "Hi"})
    assert first.provider_name == "echo_quiet"  # one-shot honoured
    second = await r.execute("demo.echo", {"text": "Hi"})
    assert second.provider_name == "echo_loud"  # reverted to default


def test_once_does_not_override_when_peeking():
    r = _reg()
    r.swap("demo.echo", "echo_quiet", scope="once")
    # peeking must not consume it
    assert r.resolve_active_name("demo.echo", consume_once=False) == "echo_quiet"
    assert r.resolve_active_name("demo.echo", consume_once=False) == "echo_quiet"


# -- permanent swap (DB-backed) -----------------------------------------------


def test_permanent_swap_persists_in_db(session_factory):
    r = _reg(session_factory)
    r.swap("demo.echo", "echo_quiet", scope="permanent")
    assert r.resolve_active_name("demo.echo", consume_once=False) == "echo_quiet"


def test_permanent_swap_survives_new_registry(session_factory):
    # Swap on one registry, then build a fresh one over the same DB.
    r1 = _reg(session_factory)
    r1.swap("demo.echo", "echo_quiet", scope="permanent")

    r2 = _reg(session_factory)
    assert r2.resolve_active_name("demo.echo", consume_once=False) == "echo_quiet"


def test_permanent_swap_overwrites_in_place(session_factory):
    from newton.models.provider_state import ProviderState

    r = _reg(session_factory)
    r.swap("demo.echo", "echo_quiet", scope="permanent")
    r.swap("demo.echo", "echo_loud", scope="permanent")

    with session_factory() as s:
        rows = s.query(ProviderState).all()
    assert len(rows) == 1  # one row per capability, overwritten
    assert rows[0].active_provider == "echo_loud"


def test_permanent_swap_without_session_factory_raises():
    r = _reg()  # no session_factory
    with pytest.raises(ProviderError, match="requires a session_factory"):
        r.swap("demo.echo", "echo_quiet", scope="permanent")


# -- scope precedence ---------------------------------------------------------


def test_session_beats_permanent(session_factory):
    r = _reg(session_factory)
    r.swap("demo.echo", "echo_loud", scope="permanent")
    r.swap("demo.echo", "echo_quiet", scope="session")
    # session override wins over the persisted permanent choice
    assert r.resolve_active_name("demo.echo", consume_once=False) == "echo_quiet"


@pytest.mark.asyncio
async def test_once_beats_session(session_factory):
    r = _reg(session_factory)
    r.swap("demo.echo", "echo_loud", scope="session")
    r.swap("demo.echo", "echo_quiet", scope="once")
    first = await r.execute("demo.echo", {"text": "x"})
    assert first.provider_name == "echo_quiet"  # once wins
    second = await r.execute("demo.echo", {"text": "x"})
    assert second.provider_name == "echo_loud"  # falls back to session


# -- bad swaps ----------------------------------------------------------------


def test_swap_unknown_provider_raises():
    r = _reg()
    with pytest.raises(ProviderError, match="unknown provider"):
        r.swap("demo.echo", "ghost", scope="session")


def test_swap_bad_scope_raises():
    r = _reg()
    with pytest.raises(ProviderError, match="bad scope"):
        r.swap("demo.echo", "echo_quiet", scope="forever")


# -- telemetry ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_telemetry_reports_usage_and_active():
    r = _reg()
    await r.execute("demo.echo", {"text": "a"})
    await r.execute("demo.echo", {"text": "b"})
    tel = r.telemetry()
    assert tel["demo.echo"]["active"] == "echo_loud"
    providers = tel["demo.echo"]["providers"]
    assert providers["echo_loud"]["used_this_session"] == 2
    assert providers["echo_quiet"]["used_this_session"] == 0
    assert providers["echo_quiet"]["cost_model"] == "free_tier"
    assert providers["echo_quiet"]["free_quota"] == 1000


# -- health check -------------------------------------------------------------


@pytest.mark.asyncio
async def test_demo_providers_healthy():
    assert await EchoLoudProvider().health_check() is True
    assert await EchoQuietProvider().health_check() is True


# -- base abstractions --------------------------------------------------------


def test_cannot_instantiate_abstract_provider():
    with pytest.raises(TypeError):
        Provider()  # type: ignore[abstract]


def test_cost_model_values():
    assert CostModel.FREE.value == "free"
    assert CostModel.FREE_TIER.value == "free_tier"
    assert CostModel.PAID.value == "paid"


def test_provider_result_defaults():
    r = ProviderResult(ok=True)
    assert r.cost == 0.0
    assert r.usage == {}
    assert r.provider_name is None
