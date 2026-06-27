"""Newton CLI — entry point for operator commands.

Used by ``sir`` (and not by end users — end users speak to Newton via voice,
web, or mobile). Keep this CLI focused on operations: DB migration, persona
seeding, vault indexing, telemetry inspection, etc.

Command tree
------------
    newton
    ├── status        [--json]   # snapshot of DB + personas + users + config
    ├── config show   [--json]
    ├── db
    │   ├── migrate   [--json]
    │   └── status    [--json]
    ├── personas list [--json]
    ├── users list    [--json]
    ├── seed          [--json]
    └── init          [--json]   # migrate + seed in one shot

CLI logic stays thin.  Real work happens in ``newton.config`` / ``newton.db``
/ ``newton.seed`` so the same operations can be invoked from voice, web, or
MCP later without duplicating logic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from newton import __version__
from newton.config import ConfigError, load_config
from newton.db import DataError, get_session, init_db, migration_status
from newton.models import Persona, User
from newton.seed import SeedReport, seed_all
from newton.tools.assembly import build_provider_registry, build_tool_registry

# ─────────────────────────────────────────────────────────────────────────────
# Root group
# ─────────────────────────────────────────────────────────────────────────────


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)
@click.version_option(__version__, prog_name="newton")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Newton — Proactive Multi-Persona AI OS.

    Operator CLI. End users interact with Newton via voice / web / mobile,
    not this command line.
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ─────────────────────────────────────────────────────────────────────────────
# config group
# ─────────────────────────────────────────────────────────────────────────────


@cli.group()
def config() -> None:
    """Inspect Newton configuration (personas, identity policy)."""


@config.command("show")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit machine-readable JSON instead of a Rich table.",
)
def config_show(as_json: bool) -> None:
    """Show parsed and validated configuration."""
    try:
        cfg = load_config()
    except ConfigError as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)

    if as_json:
        click.echo(
            json.dumps(cfg.model_dump(mode="json"), indent=2, ensure_ascii=False)
        )
        return

    console = Console()

    p_table = Table(title="Personas", header_style="bold", title_style="bold")
    p_table.add_column("id", style="cyan")
    p_table.add_column("display", style="white")
    p_table.add_column("owner")
    p_table.add_column("public", justify="center")
    p_table.add_column("default", justify="center")
    p_table.add_column("color", justify="center")
    for pid, p in cfg.personas.items():
        p_table.add_row(
            pid,
            p.display_name,
            p.owner or "—",
            "✓" if p.is_public else "",
            "✓" if p.is_default else "",
            f"[{p.color}]{p.color}[/{p.color}]",
        )
    console.print(p_table)

    i_table = Table(title="Identity policy", header_style="bold", title_style="bold")
    i_table.add_column("profile", style="cyan")
    i_table.add_column("max_retries", justify="right")
    i_table.add_column("threshold", justify="right")
    i_table.add_column("active", justify="center")
    for name, rp in cfg.identity.retry_profiles.items():
        i_table.add_row(
            name,
            str(rp.max_retries),
            f"{rp.threshold:.2f}",
            "✓" if name == cfg.identity.active_profile else "",
        )
    console.print(i_table)

    fb = cfg.identity.fallback
    fb_str = ", ".join(fb.methods) if fb.enabled and fb.methods else "disabled"
    console.print(
        f"guest_mode={'on' if cfg.identity.guest_mode_enabled else 'off'} "
        f"· fallback={fb_str}",
        style="dim",
    )


# ─────────────────────────────────────────────────────────────────────────────
# db group
# ─────────────────────────────────────────────────────────────────────────────


@cli.group()
def db() -> None:
    """Manage Newton's database (migrations, status)."""


@db.command("migrate")
@click.option("--json", "as_json", is_flag=True)
def db_migrate(as_json: bool) -> None:
    """Apply any pending migrations.  Idempotent — safe to rerun."""
    console = Console()
    try:
        before = migration_status()
        already = list(before.applied)
        applied_now = init_db()
    except DataError as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)

    if as_json:
        click.echo(
            json.dumps({"applied": applied_now, "already_applied": already}, indent=2)
        )
        return

    if applied_now:
        for v in applied_now:
            console.print(f"[green]✓[/green] applied migration {v:03d}")
    else:
        console.print("[dim]already up to date[/dim]")
        if already:
            console.print(f"[dim]applied versions: {already}[/dim]")


@db.command("status")
@click.option("--json", "as_json", is_flag=True)
def db_status(as_json: bool) -> None:
    """Show applied and pending migrations.  Does not mutate."""
    try:
        s = migration_status()
    except DataError as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)

    if as_json:
        click.echo(
            json.dumps(
                {
                    "applied": s.applied,
                    "pending": [m.name for m in s.pending],
                    "up_to_date": s.is_up_to_date,
                },
                indent=2,
            )
        )
        return

    console = Console()
    table = Table(title="Migrations", header_style="bold", title_style="bold")
    table.add_column("version", style="cyan", justify="right")
    table.add_column("status")
    table.add_column("filename")
    for v in s.applied:
        table.add_row(f"{v:03d}", "[green]applied[/green]", "")
    for m in s.pending:
        table.add_row(f"{m.version:03d}", "[yellow]pending[/yellow]", m.name)
    console.print(table)

    if s.is_up_to_date:
        console.print("[dim]up to date[/dim]")
    else:
        console.print(
            f"[yellow]{len(s.pending)} pending migration(s)[/yellow] — "
            f"run [bold]newton db migrate[/bold]"
        )


# ─────────────────────────────────────────────────────────────────────────────
# personas / users — read-only listings
# ─────────────────────────────────────────────────────────────────────────────


def _personas_with_owner_displays() -> list[tuple[Persona, str | None]]:
    """Return personas paired with their owner's display_name (or None)."""
    from sqlalchemy import select

    with get_session() as session:
        personas = list(session.scalars(select(Persona)).all())
        owner_ids = {p.owner_user_id for p in personas if p.owner_user_id}
        if owner_ids:
            users = {
                u.user_id: u.display_name
                for u in session.scalars(
                    select(User).where(User.user_id.in_(owner_ids))
                )
            }
        else:
            users = {}
        return [
            (p, users.get(p.owner_user_id) if p.owner_user_id else None)
            for p in personas
        ]


@cli.group()
def personas() -> None:
    """Inspect personas in the database."""


@personas.command("list")
@click.option("--json", "as_json", is_flag=True)
def personas_list(as_json: bool) -> None:
    """List personas (after they've been seeded)."""
    rows = _personas_with_owner_displays()

    if as_json:
        click.echo(
            json.dumps(
                [
                    {
                        "persona_id": p.persona_id,
                        "display_name": p.display_name,
                        "owner_user_id": p.owner_user_id,
                        "owner_display_name": owner_display,
                        "is_public": bool(p.is_public),
                        "is_default": bool(p.is_default),
                        "color": p.color,
                    }
                    for p, owner_display in rows
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    if not rows:
        click.secho("no personas — run 'newton seed' or 'newton init'", fg="yellow")
        return

    for p, owner_display in rows:
        tags: list[str] = []
        if p.is_public:
            tags.append("public")
        if p.is_default:
            tags.append("default")
        if p.owner_user_id:
            who = owner_display or p.owner_user_id
            tags.append(f"owner: {who}")
        suffix = f" ({', '.join(tags)})" if tags else ""
        click.echo(f"{p.persona_id}\t{suffix}")


@cli.group()
def users() -> None:
    """Inspect registered users."""


@users.command("list")
@click.option("--json", "as_json", is_flag=True)
def users_list(as_json: bool) -> None:
    """List registered users (after they've been seeded)."""
    from sqlalchemy import select

    with get_session() as session:
        user_rows = list(session.scalars(select(User)).all())

    if as_json:
        click.echo(
            json.dumps(
                [
                    {
                        "user_id": u.user_id,
                        "display_name": u.display_name,
                        "default_persona_id": u.default_persona_id,
                        "retry_profile": u.retry_profile,
                    }
                    for u in user_rows
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    if not user_rows:
        click.secho("no users — run 'newton seed' or 'newton init'", fg="yellow")
        return

    for u in user_rows:
        default = u.default_persona_id or "—"
        click.echo(f"{u.user_id}\t{u.display_name}\tdefault persona: {default}")


# ─────────────────────────────────────────────────────────────────────────────
# seed / init
# ─────────────────────────────────────────────────────────────────────────────


def _emit_seed_report(report: SeedReport, as_json: bool) -> None:
    if as_json:
        click.echo(
            json.dumps(
                {
                    "personas_added": report.personas_added,
                    "users_added": report.users_added,
                    "links_added": [list(t) for t in report.links_added],
                },
                indent=2,
            )
        )
        return

    console = Console()
    if report.is_empty:
        console.print("[dim]already seeded — nothing to do[/dim]")
        return

    if report.personas_added:
        console.print(
            f"[green]✓[/green] seeded {len(report.personas_added)} "
            f"persona(s): {', '.join(report.personas_added)}"
        )
    if report.users_added:
        console.print(
            f"[green]✓[/green] seeded {len(report.users_added)} "
            f"user(s): {', '.join(report.users_added)}"
        )
    if report.links_added:
        pairs = ", ".join(f"{u}→{p}" for u, p in report.links_added)
        console.print(
            f"[green]✓[/green] linked {len(report.links_added)} user/persona "
            f"default(s): {pairs}"
        )


@cli.command("seed")
@click.option("--json", "as_json", is_flag=True)
def seed_cmd(as_json: bool) -> None:
    """Insert initial personas and users.  Idempotent."""
    try:
        with get_session() as session:
            report = seed_all(session)
    except (ConfigError, DataError) as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)
    _emit_seed_report(report, as_json)


@cli.command("init")
@click.option("--json", "as_json", is_flag=True)
def init_cmd(as_json: bool) -> None:
    """Apply migrations and seed initial data.  Idempotent — safe to rerun."""
    try:
        applied = init_db()
        with get_session() as session:
            report = seed_all(session)
    except (ConfigError, DataError) as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)

    if as_json:
        click.echo(
            json.dumps(
                {
                    "migrations_applied": applied,
                    "personas_added": report.personas_added,
                    "users_added": report.users_added,
                    "links_added": [list(t) for t in report.links_added],
                },
                indent=2,
            )
        )
        return

    console = Console()
    if applied:
        for v in applied:
            console.print(f"[green]✓[/green] applied migration {v:03d}")
    else:
        console.print("[dim]migrations: already up to date[/dim]")
    _emit_seed_report(report, as_json=False)


# ─────────────────────────────────────────────────────────────────────────────
# status  —  one-shot snapshot of DB + personas + users + config
# ─────────────────────────────────────────────────────────────────────────────


def _status_tools_summary() -> dict:
    """Tool counts grouped by risk level. Read-only; never raises."""
    try:
        from newton.tools.assembly import build_tool_registry

        registry = build_tool_registry(auto_approve=True)
        by_risk: dict[int, int] = {}
        for t in registry.list():
            by_risk[int(t.risk)] = by_risk.get(int(t.risk), 0) + 1
        return {"count": len(registry), "by_risk": by_risk}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def _status_providers_summary() -> dict:
    """Provider counts per capability with the active provider name."""
    try:
        from newton.tools.assembly import build_provider_registry

        registry = build_provider_registry()
        out: dict[str, dict] = {}
        for cap in registry.capabilities():
            out[cap] = {
                "count": len(registry.list_providers(cap)),
                "active": registry.resolve_active_name(cap, consume_once=False),
            }
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


@cli.command("status")
@click.option("--json", "as_json", is_flag=True)
def status_cmd(as_json: bool) -> None:
    """Show a snapshot of Newton's data and configuration state.

    Read-only — never mutates.  Useful as a first debugging step before
    anything else, or after ``newton init`` to confirm everything is in place.
    """
    from sqlalchemy import select

    from newton.db import _db_path  # internal helper — fine inside our CLI

    # ── Database ──
    db_path = _db_path()
    db_size_bytes = db_path.stat().st_size if db_path.exists() else 0
    try:
        mig = migration_status()
    except DataError as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)

    # ── Personas + Users (only if DB has tables) ──
    persona_rows: list[tuple[Persona, str | None]] = []
    user_rows: list[User] = []
    if mig.applied:
        persona_rows = _personas_with_owner_displays()
        with get_session() as session:
            user_rows = list(session.scalars(select(User)).all())

    # ── Config ──
    try:
        cfg = load_config()
        cfg_summary = {
            "active_profile": cfg.identity.active_profile,
            "guest_mode": cfg.identity.guest_mode_enabled,
            "fallback_methods": (
                list(cfg.identity.fallback.methods)
                if cfg.identity.fallback.enabled
                else []
            ),
        }
        cfg_ok = True
    except ConfigError as e:
        cfg_summary = {"error": str(e)}
        cfg_ok = False

    if as_json:
        click.echo(
            json.dumps(
                {
                    "version": __version__,
                    "database": {
                        "path": str(db_path),
                        "size_bytes": db_size_bytes,
                        "migrations_applied": mig.applied,
                        "migrations_pending": [m.name for m in mig.pending],
                        "schema_up_to_date": mig.is_up_to_date,
                    },
                    "personas": [
                        {
                            "persona_id": p.persona_id,
                            "display_name": p.display_name,
                            "owner_user_id": p.owner_user_id,
                            "owner_display_name": owner_display,
                            "is_public": bool(p.is_public),
                            "is_default": bool(p.is_default),
                        }
                        for p, owner_display in persona_rows
                    ],
                    "users": [
                        {
                            "user_id": u.user_id,
                            "display_name": u.display_name,
                            "default_persona_id": u.default_persona_id,
                        }
                        for u in user_rows
                    ],
                    "config": cfg_summary,
                    "tools": _status_tools_summary(),
                    "providers": _status_providers_summary(),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    # ── Human output ──
    console = Console()
    console.print(f"[bold]Newton {__version__}[/bold]\n")

    # Database
    console.print("[bold]Database[/bold]")
    console.print(f"  path:        {db_path}")
    size_str = f"{db_size_bytes / 1024:.1f} KB" if db_size_bytes else "0 KB"
    if db_size_bytes == 0:
        size_str += " [dim](not initialized)[/dim]"
    console.print(f"  size:        {size_str}")
    applied_str = (
        ", ".join(f"{v:03d}" for v in mig.applied) if mig.applied else "[dim]none[/dim]"
    )
    console.print(f"  migrations:  {applied_str}")
    if mig.is_up_to_date:
        console.print("  schema:      [green]up to date[/green]")
    else:
        console.print(
            f"  schema:      [yellow]{len(mig.pending)} pending — "
            f"run 'newton db migrate'[/yellow]"
        )
    console.print()

    # Personas
    console.print(f"[bold]Personas ({len(persona_rows)})[/bold]")
    if persona_rows:
        for p, owner_display in persona_rows:
            tags: list[str] = []
            if p.is_public:
                tags.append("public")
            if p.is_default:
                tags.append("default")
            if p.owner_user_id:
                tags.append(f"owner: {owner_display or p.owner_user_id}")
            console.print(f"  {p.persona_id:8s}{', '.join(tags)}")
    else:
        console.print("  [dim]none — run 'newton seed' or 'newton init'[/dim]")
    console.print()

    # Users
    console.print(f"[bold]Users ({len(user_rows)})[/bold]")
    if user_rows:
        for u in user_rows:
            default = u.default_persona_id or "—"
            console.print(f"  {u.user_id:5s}{u.display_name:9s}default: {default}")
    else:
        console.print("  [dim]none — run 'newton seed' or 'newton init'[/dim]")
    console.print()

    # Config
    console.print("[bold]Config[/bold]")
    if cfg_ok:
        console.print("  source:         config/personas.yaml")
        console.print(f"  active_profile: {cfg_summary['active_profile']}")
        console.print(
            f"  guest_mode:     {'on' if cfg_summary['guest_mode'] else 'off'}"
        )
        fb = cfg_summary["fallback_methods"]
        fb_str = ", ".join(fb) if fb else "disabled"
        console.print(f"  fallback:       {fb_str}")
    else:
        console.print(f"  [red]error:[/red] {cfg_summary['error']}")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# tools group
# ─────────────────────────────────────────────────────────────────────────────


@cli.group()
def tools() -> None:
    """Inspect and run Newton tools."""


@tools.command("list")
@click.option("--json", "as_json", is_flag=True)
def tools_list(as_json: bool) -> None:
    """List registered tools, safest first."""
    registry = build_tool_registry(auto_approve=True)
    rows = [
        {
            "name": t.name,
            "risk": int(t.risk),
            "risk_name": t.risk.name,
            "description": t.description,
        }
        for t in registry.list()
    ]
    if as_json:
        click.echo(json.dumps({"tools": rows}, indent=2))
        return

    console = Console()
    table = Table(title="Newton tools")
    table.add_column("name")
    table.add_column("risk", justify="right")
    table.add_column("level")
    table.add_column("description")
    for r in rows:
        table.add_row(r["name"], str(r["risk"]), r["risk_name"], r["description"])
    console.print(table)


@tools.command("run")
@click.argument("name")
@click.option("--args", "args_json", default="{}", help="Tool args as a JSON object.")
@click.option("--user", "user_id", default="sir", help="Acting user id.")
@click.option("--persona", "persona_id", default="jarvis", help="Acting persona id.")
@click.option("--yes", "auto_approve", is_flag=True, help="Skip the approval prompt.")
@click.option("--json", "as_json", is_flag=True)
def tools_run(
    name: str,
    args_json: str,
    user_id: str,
    persona_id: str,
    auto_approve: bool,
    as_json: bool,
) -> None:
    """Run a tool by name. Gated tools prompt for approval unless --yes."""
    import asyncio

    from newton.tools.base import ToolContext
    from newton.tools.registry import ToolError

    try:
        raw_args = json.loads(args_json)
        if not isinstance(raw_args, dict):
            raise ValueError("--args must be a JSON object")
    except (json.JSONDecodeError, ValueError) as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)

    registry = build_tool_registry(auto_approve=auto_approve)
    context = ToolContext(user_id=user_id, persona_id=persona_id)

    try:
        result = asyncio.run(registry.dispatch(name, raw_args, context))
    except ToolError as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(result.model_dump(), indent=2, default=str))
        return

    console = Console()
    color = {"ok": "green", "denied": "red", "needs_approval": "yellow"}.get(
        result.status, "white"
    )
    console.print(f"[{color}]{result.status}[/{color}]")
    if result.data is not None:
        console.print(result.data)
    if result.error:
        console.print(f"[red]{result.error}[/red]")


# ─────────────────────────────────────────────────────────────────────────────
# providers group
# ─────────────────────────────────────────────────────────────────────────────


@cli.group()
def providers() -> None:
    """Inspect and hot-swap capability providers."""


@providers.command("list")
@click.option("--capability", default=None, help="Filter to one capability.")
@click.option("--json", "as_json", is_flag=True)
def providers_list(capability: str | None, as_json: bool) -> None:
    """List providers per capability, with the active one marked."""
    from newton.providers.registry import ProviderError

    registry = build_provider_registry()
    caps = [capability] if capability else registry.capabilities()

    out: dict = {}
    try:
        for cap in caps:
            active = registry.resolve_active_name(cap, consume_once=False)
            out[cap] = {
                "active": active,
                "providers": [
                    {
                        "name": p.name,
                        "cost_model": p.cost_model.value,
                        "free_quota": p.free_quota,
                        "active": p.name == active,
                    }
                    for p in registry.list_providers(cap)
                ],
            }
    except ProviderError as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(out, indent=2))
        return

    console = Console()
    for cap, info in out.items():
        table = Table(title=f"capability: {cap}  (active: {info['active']})")
        table.add_column("provider")
        table.add_column("cost")
        table.add_column("quota", justify="right")
        table.add_column("active")
        for p in info["providers"]:
            table.add_row(
                p["name"],
                p["cost_model"],
                str(p["free_quota"]) if p["free_quota"] is not None else "-",
                "●" if p["active"] else "",
            )
        console.print(table)


@providers.command("swap")
@click.argument("capability")
@click.argument("provider_name")
@click.option(
    "--scope",
    type=click.Choice(["once", "session", "permanent"]),
    default="permanent",
    help="once=next call, session=this process, permanent=persisted.",
)
@click.option("--json", "as_json", is_flag=True)
def providers_swap(
    capability: str, provider_name: str, scope: str, as_json: bool
) -> None:
    """Change the active provider for a capability.

    Note: 'once' and 'session' scopes only affect the running process, so on
    the CLI (one process per command) they have no lasting effect — use
    'permanent' to persist. once/session exist for long-lived surfaces.
    """
    from newton.providers.registry import ProviderError

    registry = build_provider_registry()
    try:
        registry.swap(capability, provider_name, scope=scope)
    except ProviderError as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)

    payload = {"capability": capability, "active": provider_name, "scope": scope}
    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return
    click.secho(f"✓ {capability} → {provider_name} ({scope})", fg="green")


@providers.command("test")
@click.argument("capability")
@click.option("--text", default="Hello Newton", help="Sample text to send.")
@click.option("--json", "as_json", is_flag=True)
def providers_test(capability: str, text: str, as_json: bool) -> None:
    """Send a sample request through the active provider."""
    import asyncio

    from newton.providers.registry import ProviderError

    registry = build_provider_registry()
    try:
        result = asyncio.run(registry.execute(capability, {"text": text}))
    except ProviderError as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(result.model_dump(), indent=2, default=str))
        return
    console = Console()
    console.print(f"[green]provider:[/green] {result.provider_name}")
    console.print(result.data)


@providers.command("usage")
@click.option("--json", "as_json", is_flag=True)
def providers_usage(as_json: bool) -> None:
    """Show per-provider usage/cost telemetry."""
    registry = build_provider_registry()
    tel = registry.telemetry()
    if as_json:
        click.echo(json.dumps(tel, indent=2))
        return
    console = Console()
    for cap, info in tel.items():
        table = Table(title=f"capability: {cap}  (active: {info['active']})")
        table.add_column("provider")
        table.add_column("cost")
        table.add_column("used", justify="right")
        for name, pinfo in info["providers"].items():
            table.add_row(name, pinfo["cost_model"], str(pinfo["used_this_session"]))
        console.print(table)


@providers.command("health")
@click.option("--json", "as_json", is_flag=True)
def providers_health(as_json: bool) -> None:
    """Run health_check on every registered provider."""
    import asyncio

    registry = build_provider_registry()

    async def _check_all() -> dict[str, dict[str, bool]]:
        out: dict[str, dict[str, bool]] = {}
        for cap in registry.capabilities():
            out[cap] = {}
            for p in registry.list_providers(cap):
                out[cap][p.name] = await p.health_check()
        return out

    results = asyncio.run(_check_all())
    if as_json:
        click.echo(json.dumps(results, indent=2))
        return
    console = Console()
    for cap, providers_map in results.items():
        for name, healthy in providers_map.items():
            mark = "[green]healthy[/green]" if healthy else "[red]down[/red]"
            console.print(f"{cap}/{name}: {mark}")


# ─────────────────────────────────────────────────────────────────────────────
# tools show
# ─────────────────────────────────────────────────────────────────────────────


@tools.command("show")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True)
def tools_show(name: str, as_json: bool) -> None:
    """Show details for one tool: name, risk, description, args schema."""
    from newton.tools.registry import ToolError

    registry = build_tool_registry(auto_approve=True)
    try:
        tool = registry.get(name)
    except ToolError as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)

    payload = {
        "name": tool.name,
        "risk": int(tool.risk),
        "risk_name": tool.risk.name,
        "description": tool.description,
        "args_schema": tool.args_schema.model_json_schema(),
        "returns_schema": tool.returns_schema.model_json_schema(),
    }
    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return

    console = Console()
    console.print(
        f"[bold]{tool.name}[/bold]  risk {payload['risk']} ({tool.risk.name})"
    )
    console.print(tool.description)
    console.print("\n[bold]args schema:[/bold]")
    console.print(json.dumps(payload["args_schema"], indent=2))


# ─────────────────────────────────────────────────────────────────────────────
# tools policy group
# ─────────────────────────────────────────────────────────────────────────────


@tools.group("policy")
def tools_policy() -> None:
    """Inspect and edit the tool approval policy matrix."""


@tools_policy.command("list")
@click.option("--tool", "tool_name", default=None, help="Filter by tool name.")
@click.option("--json", "as_json", is_flag=True)
def tools_policy_list(tool_name: str | None, as_json: bool) -> None:
    """List policy rows. Most-specific rows tend to come last."""
    from sqlalchemy import select

    from newton.db import get_session
    from newton.models.tool_policy import ToolPolicy

    with get_session() as session:
        q = select(ToolPolicy)
        if tool_name:
            q = q.where(ToolPolicy.tool_name == tool_name)
        rows = session.execute(q).scalars().all()
        data = [
            {
                "policy_id": r.policy_id,
                "tool_name": r.tool_name,
                "persona_id": r.persona_id,
                "user_id": r.user_id,
                "decision": r.decision,
                "note": r.note,
            }
            for r in rows
        ]

    if as_json:
        click.echo(json.dumps({"policies": data}, indent=2))
        return
    if not data:
        click.echo("(no policy rows)")
        return
    console = Console()
    table = Table(title="tool policies")
    table.add_column("id", justify="right")
    table.add_column("tool")
    table.add_column("persona")
    table.add_column("user")
    table.add_column("decision")
    table.add_column("note")
    for r in data:
        table.add_row(
            str(r["policy_id"]),
            r["tool_name"],
            r["persona_id"] or "*",
            r["user_id"] or "*",
            r["decision"],
            r["note"] or "",
        )
    console.print(table)


@tools_policy.command("set")
@click.argument("tool_name")
@click.option(
    "--persona", "persona_id", default=None, help="Persona id (or omit for any)."
)
@click.option("--user", "user_id", default=None, help="User id (or omit for any).")
@click.option(
    "--decision",
    type=click.Choice(["auto_allow", "require_approval", "always_deny"]),
    required=True,
)
@click.option("--note", default=None, help="Optional rationale.")
@click.option("--json", "as_json", is_flag=True)
def tools_policy_set(
    tool_name: str,
    persona_id: str | None,
    user_id: str | None,
    decision: str,
    note: str | None,
    as_json: bool,
) -> None:
    """Add or update one policy row for (tool, persona, user)."""
    from sqlalchemy import select

    from newton.db import get_session
    from newton.models.tool_policy import ToolPolicy

    with get_session() as session:
        existing = session.execute(
            select(ToolPolicy).where(
                ToolPolicy.tool_name == tool_name,
                ToolPolicy.persona_id.is_(None)
                if persona_id is None
                else ToolPolicy.persona_id == persona_id,
                ToolPolicy.user_id.is_(None)
                if user_id is None
                else ToolPolicy.user_id == user_id,
            )
        ).scalar_one_or_none()

        if existing is not None:
            existing.decision = decision
            if note is not None:
                existing.note = note
            row = existing
            action = "updated"
        else:
            row = ToolPolicy(
                tool_name=tool_name,
                persona_id=persona_id,
                user_id=user_id,
                decision=decision,
                note=note,
            )
            session.add(row)
            session.flush()
            action = "inserted"

        payload = {
            "action": action,
            "policy_id": row.policy_id,
            "tool_name": row.tool_name,
            "persona_id": row.persona_id,
            "user_id": row.user_id,
            "decision": row.decision,
        }

    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return
    click.secho(
        f"✓ {action} policy #{payload['policy_id']}: "
        f"{tool_name} persona={persona_id or '*'} user={user_id or '*'} "
        f"-> {decision}",
        fg="green",
    )


@tools_policy.command("unset")
@click.argument("tool_name")
@click.option("--persona", "persona_id", default=None)
@click.option("--user", "user_id", default=None)
@click.option("--json", "as_json", is_flag=True)
def tools_policy_unset(
    tool_name: str, persona_id: str | None, user_id: str | None, as_json: bool
) -> None:
    """Delete the policy row matching (tool, persona, user) exactly."""
    from sqlalchemy import select

    from newton.db import get_session
    from newton.models.tool_policy import ToolPolicy

    with get_session() as session:
        row = session.execute(
            select(ToolPolicy).where(
                ToolPolicy.tool_name == tool_name,
                ToolPolicy.persona_id.is_(None)
                if persona_id is None
                else ToolPolicy.persona_id == persona_id,
                ToolPolicy.user_id.is_(None)
                if user_id is None
                else ToolPolicy.user_id == user_id,
            )
        ).scalar_one_or_none()
        if row is None:
            payload = {"deleted": False, "reason": "no matching row"}
            if as_json:
                click.echo(json.dumps(payload, indent=2))
                return
            click.echo("no matching policy row")
            return
        pid = row.policy_id
        session.delete(row)
        payload = {"deleted": True, "policy_id": pid}

    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return
    click.secho(f"✓ deleted policy #{pid}", fg="green")


# ─────────────────────────────────────────────────────────────────────────────
# providers show, providers active
# ─────────────────────────────────────────────────────────────────────────────


@providers.command("show")
@click.argument("capability")
@click.option("--json", "as_json", is_flag=True)
def providers_show(capability: str, as_json: bool) -> None:
    """Show details for one capability: active provider and registered set."""
    from newton.providers.registry import ProviderError

    registry = build_provider_registry()
    try:
        active = registry.resolve_active_name(capability, consume_once=False)
        listed = registry.list_providers(capability)
    except ProviderError as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)

    payload = {
        "capability": capability,
        "active": active,
        "providers": [
            {
                "name": p.name,
                "cost_model": p.cost_model.value,
                "free_quota": p.free_quota,
                "used_this_session": p.used_this_session,
                "active": p.name == active,
            }
            for p in listed
        ],
    }
    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return
    console = Console()
    console.print(f"[bold]{capability}[/bold]  active: {active}")
    for p in payload["providers"]:
        mark = "●" if p["active"] else " "
        console.print(
            f"  {mark} {p['name']:20s} {p['cost_model']:10s} "
            f"used={p['used_this_session']}"
        )


@providers.command("active")
@click.argument("capability")
@click.option("--json", "as_json", is_flag=True)
def providers_active(capability: str, as_json: bool) -> None:
    """Print just the active provider name for a capability."""
    from newton.providers.registry import ProviderError

    registry = build_provider_registry()
    try:
        name = registry.resolve_active_name(capability, consume_once=False)
    except ProviderError as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"capability": capability, "active": name}))
        return
    click.echo(name)


# -----------------------------------------------------------------------------
# vault group
# -----------------------------------------------------------------------------


@cli.group()
def vault() -> None:
    """Vault: scan, index, and (later) search notes."""


@vault.command("index")
@click.option("--force", is_flag=True, help="Re-index every note, ignoring hashes.")
@click.option("--no-scan", is_flag=True, help="Skip the scan; index cache as-is.")
@click.option("--json", "as_json", is_flag=True)
def vault_index(force: bool, no_scan: bool, as_json: bool) -> None:
    """Scan the vault, then chunk/embed/upsert changed notes into Qdrant."""
    import asyncio

    from newton.db import get_session
    from newton.system_config import load_system_config
    from newton.vault.indexer import index_vault
    from newton.vault.scanner import scan

    config = load_system_config()

    async def _run() -> dict:
        with get_session() as session:
            scan_summary = None
            if not no_scan:
                sr = scan(session, config.vault)
                scan_summary = {
                    "scanned": sr.scanned,
                    "added": sr.added,
                    "updated": sr.updated,
                    "removed": sr.removed,
                    "unchanged": sr.unchanged,
                }
            ir = await index_vault(session, config, force=force)
            return {
                "scan": scan_summary,
                "index": {
                    "notes_indexed": ir.notes_indexed,
                    "notes_skipped": ir.notes_skipped,
                    "chunks_upserted": ir.chunks_upserted,
                    "errors": ir.errors,
                },
            }

    try:
        report = asyncio.run(_run())
    except Exception as e:  # noqa: BLE001
        click.secho(f"error: {type(e).__name__}: {e}", fg="red", err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(report, indent=2))
        return

    console = Console()
    if report["scan"] is not None:
        s = report["scan"]
        console.print(
            f"[bold]scan[/bold]: scanned {s['scanned']}, +{s['added']} "
            f"~{s['updated']} -{s['removed']} ({s['unchanged']} unchanged)"
        )
    i = report["index"]
    console.print(
        f"[bold]index[/bold]: {i['notes_indexed']} notes indexed, "
        f"{i['notes_skipped']} skipped, {i['chunks_upserted']} chunks upserted"
    )
    for err in i["errors"]:
        console.print(f"[red]  error: {err}[/red]")


@vault.command("search")
@click.argument("query")
@click.option("--user", "user_id", default="sir", help="Acting user id.")
@click.option("--persona", "persona_id", default="jarvis", help="Active persona.")
@click.option("--limit", default=5, help="Max results.")
@click.option(
    "--status",
    "status_filter",
    default="canonical",
    help="Only notes with this status (canonical|shared|pending_review).",
)
@click.option("--json", "as_json", is_flag=True)
def vault_search(
    query: str,
    user_id: str,
    persona_id: str,
    limit: int,
    status_filter: str,
    as_json: bool,
) -> None:
    """Semantic search over the vault, filtered by ACL for (user, persona)."""
    import asyncio

    from newton.vault.search import search

    try:
        hits = asyncio.run(
            search(
                query,
                user_id,
                persona_id,
                limit=limit,
                status_filter=status_filter,
            )
        )
    except Exception as e:  # noqa: BLE001
        click.secho(f"error: {type(e).__name__}: {e}", fg="red", err=True)
        sys.exit(1)

    if as_json:
        click.echo(
            json.dumps(
                [
                    {
                        "note_id": h.note_id,
                        "chunk_index": h.chunk_index,
                        "path": h.path,
                        "score": h.score,
                        "text": h.text,
                        "owner_user_id": h.owner_user_id,
                        "status": h.status,
                        "tags": h.tags,
                    }
                    for h in hits
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    console = Console()
    if not hits:
        console.print("[dim]no results[/dim]")
        return
    console.print(f"[bold]{len(hits)} result(s)[/bold] for {query!r}:")
    for h in hits:
        console.print(
            f"  [green]{h.score:.3f}[/green]  {h.path} [dim]#{h.chunk_index}[/dim]"
        )
        console.print(f"    {h.text}")


# ── vault quarantine subgroup ────────────────────────────────────────────────


@vault.group("quarantine")
def vault_quarantine() -> None:
    """Review guest activity held in quarantine."""


@vault_quarantine.command("list")
@click.option("--json", "as_json", is_flag=True)
def vault_quarantine_list(as_json: bool) -> None:
    """List pending quarantined items (orphan files are folded in first)."""
    from newton.db import get_session
    from newton.system_config import load_system_config
    from newton.vault.quarantine import list_pending

    config = load_system_config()
    with get_session() as session:
        items = list_pending(session, config)

    if as_json:
        click.echo(
            json.dumps(
                [
                    {
                        "activity_id": it.activity_id,
                        "path": it.path,
                        "activity_type": it.activity_type,
                        "summary": it.summary,
                        "status": it.status,
                    }
                    for it in items
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    console = Console()
    if not items:
        console.print("[dim]quarantine is empty[/dim]")
        return
    console.print(f"[bold]{len(items)} pending item(s)[/bold]:")
    for it in items:
        kind = it.activity_type or "?"
        console.print(f"  [yellow]#{it.activity_id}[/yellow]  {kind}  {it.path}")
        if it.summary:
            console.print(f"      {it.summary}")


@vault_quarantine.command("review")
@click.argument("activity_id", type=int)
@click.option(
    "--decision",
    required=True,
    type=click.Choice(["promote", "shared", "reject", "hold"]),
)
@click.option("--by", "reviewed_by", default="sir", help="Reviewer user id.")
@click.option(
    "--owner",
    "target_owner",
    default=None,
    help="Owner for promoted notes (defaults to reviewer).",
)
@click.option("--json", "as_json", is_flag=True)
def vault_quarantine_review(
    activity_id: int,
    decision: str,
    reviewed_by: str,
    target_owner: str | None,
    as_json: bool,
) -> None:
    """Apply a decision to one quarantined item by its activity id."""
    import asyncio

    from newton.db import get_session
    from newton.system_config import load_system_config
    from newton.vault.quarantine import Decision, review

    config = load_system_config()

    async def _run() -> dict:
        with get_session() as session:
            return await review(
                session,
                activity_id,
                Decision(decision),
                config,
                reviewed_by=reviewed_by,
                target_owner=target_owner,
            )

    try:
        report = asyncio.run(_run())
    except ValueError as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        click.secho(f"error: {type(e).__name__}: {e}", fg="red", err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(report, indent=2))
        return
    click.echo(
        f"#{report['activity_id']}: {report['decision']} "
        f"-> {report['status']} ({report['path']})"
    )


# -----------------------------------------------------------------------------
# persona group
# -----------------------------------------------------------------------------


@cli.group()
def persona() -> None:
    """Persona activation routing and prompt rendering."""


@persona.command("route")
@click.option("--user", "user_id", required=True, help="Acting user id.")
@click.option("--voice-stage2", "voice", default=None, help="Named persona.")
@click.option("--face-stage2", "face", is_flag=True, help="Face binding (use default).")
@click.option("--show-prompt", is_flag=True, help="Also print the system prompt.")
@click.option("--json", "as_json", is_flag=True)
def persona_route(
    user_id: str, voice: str | None, face: bool, show_prompt: bool, as_json: bool
) -> None:
    """Route a Stage-2 signal to a persona and (optionally) render its prompt."""
    from newton.db import get_session
    from newton.persona import (
        FaceBindingSignal,
        PersonaEngine,
        PersonaEngineError,
        VoiceNamingSignal,
    )

    if voice and face:
        click.secho(
            "error: pass only one of --voice-stage2 / --face-stage2", fg="red", err=True
        )
        sys.exit(1)
    if not voice and not face:
        click.secho(
            "error: pass --voice-stage2 NAME or --face-stage2", fg="red", err=True
        )
        sys.exit(1)

    signal = VoiceNamingSignal(voice) if voice else FaceBindingSignal()

    try:
        with get_session() as session:
            engine = PersonaEngine(session)
            act = engine.route(user_id, signal)
            prompt = (
                engine.render_system_prompt(act.persona_id, user_id)
                if show_prompt
                else None
            )
    except PersonaEngineError as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)

    if as_json:
        out = {
            "user_id": act.user_id,
            "persona_id": act.persona_id,
            "reason": act.reason.value,
        }
        if prompt is not None:
            out["system_prompt"] = prompt
        click.echo(json.dumps(out, indent=2, ensure_ascii=False))
        return

    console = Console()
    console.print(f"persona: [bold]{act.persona_id}[/bold]  ({act.reason.value})")
    if prompt is not None:
        console.print("[dim]--- system prompt ---[/dim]")
        console.print(prompt)


# -----------------------------------------------------------------------------
# voice group
# -----------------------------------------------------------------------------


@cli.group()
def voice() -> None:
    """Voice subsystem helpers (biasing dictionary, ...)."""


@voice.group()
def biasing() -> None:
    """Inspect or clear a user's STT contextual-biasing dictionary."""


@biasing.command("show")
@click.option("--user", "user_id", required=True)
@click.option("--json", "as_json", is_flag=True)
def biasing_show(user_id: str, as_json: bool) -> None:
    """Show the user's biasing dictionary."""
    from newton.db import get_session
    from newton.models import User

    with get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            click.secho(f"error: unknown user {user_id!r}", fg="red", err=True)
            sys.exit(1)
        entries = json.loads(user.stt_bias_dict_json or "[]")

    if as_json:
        click.echo(json.dumps(entries, indent=2, ensure_ascii=False))
        return
    console = Console()
    if not entries:
        console.print("[dim]biasing dictionary is empty[/dim]")
        return
    console.print(f"[bold]{len(entries)} entries[/bold] for {user_id}:")
    for e in entries:
        console.print(f"  {e}")


@biasing.command("clear")
@click.option("--user", "user_id", required=True)
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def biasing_clear(user_id: str, yes: bool) -> None:
    """Clear the user's biasing dictionary."""
    from newton.db import get_session
    from newton.models import User

    if not yes:
        click.confirm(f"Clear biasing dictionary for {user_id}?", abort=True)

    with get_session() as session:
        user = session.get(User, user_id)
        if user is None:
            click.secho(f"error: unknown user {user_id!r}", fg="red", err=True)
            sys.exit(1)
        user.stt_bias_dict_json = "[]"

    click.echo(f"cleared biasing dictionary for {user_id}")


# ── voice samples (step 5.4) ────────────────────────────────────────────


def _project_root_path() -> Path:
    return Path(__file__).resolve().parent.parent


def _voice_root_path() -> Path:
    """Where the gitignored persona samples live."""
    from newton.voice.config import load_voice_config

    cfg = load_voice_config()
    root = Path(cfg.tts.voice_root)
    return root if root.is_absolute() else _project_root_path() / root


def _docs_root_path() -> Path:
    return _project_root_path() / "docs"


@voice.group("samples")
def voice_samples() -> None:
    """Inspect persona TTS samples + consent records (step 5.4)."""


@voice_samples.command("list")
@click.argument("persona_id")
@click.option("--json", "as_json", is_flag=True)
def voice_samples_list(persona_id: str, as_json: bool) -> None:
    """List per-language WAV samples on disk for ``persona_id``."""
    from newton.voice.samples import list_samples

    files_by_lang = list_samples(persona_id, _voice_root_path())

    if as_json:
        payload = {
            lang: [
                {
                    "path": str(f.path),
                    "duration_seconds": f.duration_seconds,
                    "sample_rate": f.sample_rate,
                    "n_channels": f.n_channels,
                    "bytes": f.bytes_total,
                }
                for f in files
            ]
            for lang, files in files_by_lang.items()
        }
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    console = Console()
    if not files_by_lang:
        console.print(f"[dim]no samples on disk for {persona_id}[/dim]")
        return
    root = _voice_root_path() / persona_id / "samples"
    for lang, files in files_by_lang.items():
        console.print(f"[bold]{lang}[/bold]  {len(files)} sample(s) in {root / lang}")
        for f in files:
            dur = f"{f.duration_seconds:.1f}s" if f.duration_seconds else "—"
            sr = f"{f.sample_rate}Hz" if f.sample_rate else "—"
            ch = f"{f.n_channels}ch" if f.n_channels else "—"
            console.print(f"  {f.path.name:25s} {dur:>6s}  {sr:>9s}  {ch}")


@voice_samples.command("show")
@click.argument("persona_id")
@click.option("--json", "as_json", is_flag=True)
def voice_samples_show(persona_id: str, as_json: bool) -> None:
    """Show the consent record and inventory for ``persona_id``."""
    from newton.voice.samples import summarize

    summary = summarize(persona_id, _voice_root_path(), _docs_root_path())

    if as_json:
        click.echo(
            json.dumps(
                {
                    "persona_id": summary.persona_id,
                    "voice_root": str(summary.voice_root),
                    "samples_root": str(summary.samples_root),
                    "consent_doc": (
                        str(summary.consent_doc) if summary.consent_doc else None
                    ),
                    "has_consent_doc": summary.has_consent_doc,
                    "total_count": summary.total_count,
                    "files_by_language": {
                        lang: [str(f.path) for f in files]
                        for lang, files in summary.files_by_language.items()
                    },
                },
                indent=2,
            )
        )
        return

    console = Console()
    console.print(f"[bold]{persona_id}[/bold]  ({summary.total_count} samples)")
    console.print(f"  samples_root: {summary.samples_root}")
    if summary.has_consent_doc:
        console.print(f"  consent     : [green]{summary.consent_doc}[/green]")
    else:
        console.print(
            f"  consent     : [red]missing[/red]  "
            f"(expected at docs/newton/voice-samples/{persona_id}.md)"
        )
    for lang, files in summary.files_by_language.items():
        console.print(f"  {lang}: {len(files)} samples")


# ── voice tts (step 5.5 — zero-shot cloning CLI) ───────────────────────


@voice.command("tts")
@click.option("--persona", "persona_id", required=True, help="Persona id.")
@click.option("--lang", "language", required=True, help="Language code (ko/en/...).")
@click.option("--text", required=True, help="Text to synthesize.")
@click.option(
    "--out",
    "out_path",
    default=None,
    help="Output WAV path. Defaults to /tmp/newton-voice-<timestamp>.wav.",
)
@click.option(
    "--play/--no-play",
    "play",
    default=False,
    help="Play the resulting WAV through the system audio output after writing.",
)
@click.option(
    "--stream/--no-stream",
    "stream",
    default=False,
    help=(
        "Sentence-stream synthesis: split text into sentences, synthesize each "
        "and (with --play) start speaking after sentence 1 while the next is "
        "still synthesizing. Drops time-to-first-audio on long replies."
    ),
)
@click.option("--json", "as_json", is_flag=True)
def voice_tts(
    persona_id: str,
    language: str,
    text: str,
    out_path: str | None,
    play: bool,
    stream: bool,
    as_json: bool,
) -> None:
    """Synthesize ``text`` for ``persona_id`` + ``language`` and write a WAV.

    The router resolves (persona, lang) → engine + sample; the engine
    lazy-loads its model on first call. Missing samples fail loudly
    *before* any model load — see
    docs/newton/voice-cloning-verification.md for the install + run flow.
    """
    import time

    from newton.voice.config import load_voice_config
    from newton.voice.samples import find_referenced_sample
    from newton.voice.tts.base import save_wav
    from newton.voice.tts.router import (
        TTSRouter,
        TTSRoutingError,
        make_engine_factory,
    )

    cfg = load_voice_config()
    voice_root = _voice_root_path()
    router = TTSRouter(
        config=cfg.tts,
        engine_factory=make_engine_factory(cfg.tts),
        voice_root_override=voice_root,
    )

    # 1) Find the route — DOES NOT construct the engine.
    try:
        route = router.find_route(persona_id, language)
    except TTSRoutingError as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)

    # 2) Existence-check the sample BEFORE the engine loads, so a
    # missing-sample error never triggers a heavy model load.
    voice_ref: Path | None = None
    if route.voice_reference is not None:
        resolved_path = find_referenced_sample(route.voice_reference, voice_root)
        if resolved_path is None:
            click.secho(
                f"error: voice sample for {persona_id}/{language} not found "
                f"at {voice_root / route.voice_reference}. "
                f"Record it (step 5.4) or update voice.yaml.",
                fg="red",
                err=True,
            )
            sys.exit(1)
        voice_ref = resolved_path

    # 3) Now resolve (engine constructed + cached) and synthesize.
    resolved = router.resolve(persona_id, language)

    if stream:
        _voice_tts_stream(
            text=text,
            language=language,
            persona_id=persona_id,
            voice_ref=voice_ref,
            resolved=resolved,
            out_path=out_path,
            play=play,
            as_json=as_json,
        )
        return

    try:
        result = resolved.engine.synthesize(
            text,
            language=language,
            voice_reference=voice_ref,
            ref_text=resolved.route.ref_text,
        )
    except ModuleNotFoundError as e:
        click.secho(
            f"error: {e.name} not installed. See "
            f"docs/newton/voice-cloning-verification.md for install steps.",
            fg="red",
            err=True,
        )
        sys.exit(1)
    except FileNotFoundError as e:
        click.secho(
            f"error: {e}. Fetch the model weights — see "
            f"docs/newton/voice-cloning-verification.md.",
            fg="red",
            err=True,
        )
        sys.exit(1)

    # 4) Write the WAV.
    if out_path is None:
        out_path = f"/tmp/newton-voice-{int(time.time())}.wav"
    out = Path(out_path)
    save_wav(result, out)

    # 5) Optionally play the WAV. The file is the durable artifact —
    # a playback failure must not delete it, just report and exit cleanly.
    played = False
    playback_error: str | None = None
    if play:
        from newton.voice.playback import PlaybackError, play_wav

        try:
            play_wav(out)
            played = True
        except (PlaybackError, FileNotFoundError) as e:
            playback_error = str(e)

    payload = {
        "persona": persona_id,
        "language": language,
        "engine": resolved.engine.name,
        "voice_reference": str(voice_ref) if voice_ref else None,
        "out": str(out),
        "duration_seconds": result.duration_seconds,
        "sample_rate": result.sample_rate,
        "played": played,
        "streamed": False,
    }
    if playback_error is not None:
        payload["playback_error"] = playback_error
    if as_json:
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    console = Console()
    console.print(f"[bold]engine[/bold] : {resolved.engine.name}")
    console.print(f"[bold]sample[/bold] : {voice_ref}")
    console.print(
        f"[bold]output[/bold] : {out}  ({result.duration_seconds:.2f}s @ "
        f"{result.sample_rate}Hz)"
    )
    if play:
        if played:
            console.print("[bold]played[/bold] : yes")
        else:
            console.print(
                f"[bold]played[/bold] : [red]failed[/red]  ({playback_error})"
            )


def _voice_tts_stream(
    *,
    text: str,
    language: str,
    persona_id: str,
    voice_ref: Path | None,
    resolved,
    out_path: str | None,
    play: bool,
    as_json: bool,
) -> None:
    """Sentence-streamed synth+play branch of ``voice tts``.

    Split → background-worker synth-ahead-by-one → main-thread blocking
    playback. The combined per-sentence audio is concatenated and
    written to ``--out`` so the artifact contract matches the
    non-stream path (single WAV on disk).
    """
    import time

    import numpy as np

    from newton.voice.sentences import split_sentences
    from newton.voice.streaming import stream_synth_and_play
    from newton.voice.tts.base import TTSResult, save_wav

    sentences = split_sentences(text, language)
    if not sentences:
        click.secho(
            "error: --text is empty after sentence splitting.", fg="red", err=True
        )
        sys.exit(1)

    try:
        stream_res = stream_synth_and_play(
            sentences,
            engine=resolved.engine,
            language=language,
            voice_reference=voice_ref,
            ref_text=resolved.route.ref_text,
            play=play,
        )
    except ModuleNotFoundError as e:
        click.secho(
            f"error: {e.name} not installed. See "
            f"docs/newton/voice-cloning-verification.md for install steps.",
            fg="red",
            err=True,
        )
        sys.exit(1)
    except FileNotFoundError as e:
        click.secho(
            f"error: {e}. Fetch the model weights — see "
            f"docs/newton/voice-cloning-verification.md.",
            fg="red",
            err=True,
        )
        sys.exit(1)

    # Concatenate whatever clips made it through (full success → all
    # sentences; partial failure → up to the failing one). Save so the
    # caller always has a durable artifact for the audio already produced.
    out_str = out_path or f"/tmp/newton-voice-{int(time.time())}.wav"
    out = Path(out_str)
    combined: TTSResult | None = None
    if stream_res.audios:
        combined = TTSResult(
            audio=np.concatenate(stream_res.audios),
            sample_rate=stream_res.sample_rate,
        )
        save_wav(combined, out)

    played = (
        play and stream_res.error is None and stream_res.played_count == len(sentences)
    )

    payload: dict[str, object] = {
        "persona": persona_id,
        "language": language,
        "engine": resolved.engine.name,
        "voice_reference": str(voice_ref) if voice_ref else None,
        "out": str(out) if combined is not None else None,
        "duration_seconds": combined.duration_seconds if combined else 0.0,
        "sample_rate": combined.sample_rate if combined else 0,
        "played": played,
        "streamed": True,
        "sentences": len(sentences),
    }
    if stream_res.error is not None:
        payload["failed_sentence"] = stream_res.failed_sentence
        payload["error_phase"] = stream_res.error_phase
        payload["error"] = str(stream_res.error)

    if as_json:
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        console = Console()
        console.print(f"[bold]engine[/bold]   : {resolved.engine.name}")
        console.print(f"[bold]sample[/bold]   : {voice_ref}")
        if combined is not None:
            console.print(
                f"[bold]output[/bold]   : {out}  "
                f"({combined.duration_seconds:.2f}s @ {combined.sample_rate}Hz)"
            )
        console.print(
            f"[bold]streamed[/bold] : {len(sentences)} sentences "
            f"(synthesized {len(stream_res.audios)})"
        )
        if play:
            if played:
                console.print("[bold]played[/bold]   : yes")
            else:
                console.print(
                    f"[bold]played[/bold]   : [red]failed[/red]  "
                    f"(sentence {stream_res.failed_sentence}: {stream_res.error})"
                )
        if stream_res.error_phase == "synth":
            console.print(
                f"[bold]synth[/bold]    : [red]failed at sentence "
                f"{stream_res.failed_sentence}[/red]  ({stream_res.error})"
            )

    # Synth failure means the user's text wasn't fully spoken; signal
    # that with exit 1 (matches the non-stream synth-error behaviour).
    # Playback failure leaves a complete WAV on disk, so exit 0.
    if stream_res.error_phase == "synth":
        sys.exit(1)


# ── voice id (step 5.9 — Resemblyzer enrollment / verification) ────────


@voice.group("id")
def voice_id_group() -> None:
    """Speaker enrollment + recognition (Resemblyzer)."""


@voice_id_group.command("register")
@click.argument("user_id")
@click.argument("wav", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def voice_id_register(user_id: str, wav: Path, as_json: bool) -> None:
    """Compute and store ``user_id``'s voice embedding from ``WAV``."""
    from newton.voice.voice_id import VoiceIdError, VoiceIdService

    try:
        with get_session() as session:
            service = VoiceIdService.from_config(session)
            service.register(user_id, wav)
    except VoiceIdError as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)
    except ModuleNotFoundError as e:
        click.secho(
            f"error: {e.name} not installed. "
            "Install the voice-id extra: `uv sync --extra voice-id`.",
            fg="red",
            err=True,
        )
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"user_id": user_id, "registered": True}))
        return
    click.echo(f"registered voice embedding for {user_id} from {wav}")


@voice_id_group.command("verify")
@click.argument("wav", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def voice_id_verify(wav: Path, as_json: bool) -> None:
    """Identify the speaker of ``WAV`` against registered users."""
    from newton.voice.voice_id import VoiceIdService

    try:
        with get_session() as session:
            service = VoiceIdService.from_config(session)
            matched_user, confidence = service.identify(wav)
    except ModuleNotFoundError as e:
        click.secho(
            f"error: {e.name} not installed. "
            "Install the voice-id extra: `uv sync --extra voice-id`.",
            fg="red",
            err=True,
        )
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"user_id": matched_user, "confidence": confidence}))
        return
    if matched_user is None:
        click.echo(f"no match (best confidence: {confidence:.2f})")
        return
    click.echo(f"user: {matched_user}, confidence: {confidence:.2f}")


# -----------------------------------------------------------------------------
# memory group
# -----------------------------------------------------------------------------


@cli.group()
def memory() -> None:
    """Long-term memory: summarize conversations and recall them."""


@memory.command("summarize-session")
@click.argument("session_id")
@click.option("--json", "as_json", is_flag=True)
def memory_summarize_session(session_id: str, as_json: bool) -> None:
    """Condense a session into a searchable vault note."""
    import asyncio

    from newton.db import get_session
    from newton.memory.summarizer import FakeSummarizer, summarize_session
    from newton.system_config import load_system_config

    config = load_system_config()
    vault_root = Path(config.vault.root)
    auto_dir = config.vault.layout.auto_dir

    async def _run() -> Path | None:
        with get_session() as session:
            return await summarize_session(
                session,
                session_id,
                FakeSummarizer(),
                vault_root,
                auto_dir=auto_dir,
            )

    try:
        path = asyncio.run(_run())
    except Exception as e:  # noqa: BLE001
        click.secho(f"error: {type(e).__name__}: {e}", fg="red", err=True)
        sys.exit(1)

    if path is None:
        click.secho(f"error: unknown session {session_id!r}", fg="red", err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"path": str(path)}, indent=2))
        return
    click.echo(f"Created: {path}")


@memory.command("recall")
@click.argument("query")
@click.option("--user", "user_id", required=True)
@click.option("--persona", "persona_id", required=True)
@click.option("--limit", default=5, show_default=True)
@click.option("--json", "as_json", is_flag=True)
def memory_recall(
    query: str, user_id: str, persona_id: str, limit: int, as_json: bool
) -> None:
    """Recall past conversation summaries relevant to a query."""
    import asyncio

    from newton.vault.search import search

    try:
        hits = asyncio.run(search(query, user_id, persona_id, limit=limit))
    except Exception as e:  # noqa: BLE001
        click.secho(f"error: {type(e).__name__}: {e}", fg="red", err=True)
        sys.exit(1)

    if as_json:
        click.echo(
            json.dumps(
                [
                    {
                        "path": h.path,
                        "score": h.score,
                        "text": h.text,
                        "tags": h.tags,
                    }
                    for h in hits
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
        return
    console = Console()
    if not hits:
        console.print("[dim]no matching memories[/dim]")
        return
    console.print(f"[bold]{len(hits)} memory(ies)[/bold] for {query!r}:")
    for h in hits:
        console.print(
            f"  [green]{h.score:.3f}[/green]  {h.path} [dim]#{h.chunk_index}[/dim]"
        )
        console.print(f"    {h.text}")


# -----------------------------------------------------------------------------
# proactive group (block 4)
# -----------------------------------------------------------------------------


@cli.group()
def proactive() -> None:
    """Proactive engine — background monitoring, patterns, notifications."""


def _proactive_pidfile_path() -> Path:
    from newton.db import _data_dir
    from newton.proactive.pidfile import pidfile_path

    return pidfile_path(_data_dir())


@proactive.command("start")
@click.option(
    "--foreground/--detach",
    default=True,
    help=(
        "Foreground (default) runs the daemon in this terminal until Ctrl-C; "
        "--detach double-forks into the background."
    ),
)
@click.option(
    "--once",
    is_flag=True,
    help="Run exactly one sampling pass and exit. Useful for smoke tests.",
)
@click.option(
    "--active-interval",
    "active_interval_s",
    type=float,
    default=5.0,
    show_default=True,
    help="Seconds between samples when the user is active.",
)
@click.option(
    "--idle-interval",
    "idle_interval_s",
    type=float,
    default=60.0,
    show_default=True,
    help="Seconds between samples when the user is idle.",
)
@click.option(
    "--user",
    "user_id",
    default="sir",
    show_default=True,
    help="User id to pin alert rows against (proactive_notifications.user_id).",
)
@click.option("--json", "as_json", is_flag=True)
def proactive_start(
    foreground: bool,
    once: bool,
    active_interval_s: float,
    idle_interval_s: float,
    user_id: str,
    as_json: bool,
) -> None:
    """Start the proactive monitoring daemon."""
    import logging
    import os

    from newton.proactive import daemon as daemon_module
    from newton.proactive.alerts import AlertChecker
    from newton.proactive.daemon import ProactiveDaemon
    from newton.proactive.pidfile import clear_pidfile, inspect, write_pidfile

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    pidpath = _proactive_pidfile_path()
    status = inspect(pidpath)
    if status.running:
        click.secho(
            f"error: proactive daemon already running (PID {status.pid})",
            fg="red",
            err=True,
        )
        sys.exit(1)
    if status.stale:
        click.secho(
            f"removing stale PID file (PID {status.pid} no longer running)",
            fg="yellow",
        )
        clear_pidfile(pidpath)

    # Pass monitors explicitly (instead of relying on the dataclass's
    # default_factory) so tests can swap default_monitors via monkeypatch.
    daemon = ProactiveDaemon(
        monitors=daemon_module.default_monitors(),
        active_interval_s=active_interval_s,
        idle_interval_s=idle_interval_s,
        alert_checker=AlertChecker(),
        alert_user_id=user_id,
    )

    if once:
        report = daemon.tick_once()
        # Alerts are surfaced through display_text so the [kind] prefix
        # never reaches the user.
        alerts_payload = [
            {"kind": a.kind, "value": a.value, "text": a.display}
            for a in report.alerts_fired
        ]
        if as_json:
            click.echo(
                json.dumps(
                    {
                        "metrics_written": report.metrics_written,
                        "metrics_skipped": report.metrics_skipped,
                        "per_monitor": report.per_monitor,
                        "alerts_fired": alerts_payload,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return
        click.echo(
            f"one tick: {report.metrics_written} written, "
            f"{report.metrics_skipped} skipped, "
            f"{len(report.alerts_fired)} alert(s)"
        )
        for name, value in report.per_monitor.items():
            shown = f"{value:.2f}" if isinstance(value, float) else "—"
            click.echo(f"  {name:10s} {shown}")
        for a in report.alerts_fired:
            click.echo(f"  alert [{a.kind}]: {a.display}")
        return

    if not foreground:
        # Standard Unix double-fork: parent → fork1 (exits) → setsid →
        # fork2 (the daemon body). After this, only the daemon process
        # continues; everyone else has returned to the shell.
        if os.fork() != 0:
            return
        os.setsid()
        if os.fork() != 0:
            os._exit(0)

    write_pidfile(pidpath)
    try:
        daemon.install_signal_handlers()
        if not as_json:
            click.echo(
                f"proactive daemon started (PID {os.getpid()})\n"
                f"sampling: {active_interval_s:.0f}s active, "
                f"{idle_interval_s:.0f}s idle"
            )
        daemon.run_forever()
    finally:
        clear_pidfile(pidpath)


@proactive.command("stop")
@click.option(
    "--timeout",
    type=float,
    default=10.0,
    show_default=True,
    help="Seconds to wait for the daemon to exit before giving up.",
)
@click.option("--json", "as_json", is_flag=True)
def proactive_stop(timeout: float, as_json: bool) -> None:
    """Stop the running proactive daemon (SIGTERM, then wait)."""
    import os
    import time

    from newton.proactive.pidfile import clear_pidfile, inspect

    pidpath = _proactive_pidfile_path()
    status = inspect(pidpath)

    if status.pid is None:
        if as_json:
            click.echo(json.dumps({"stopped": False, "reason": "no pidfile"}))
            return
        click.echo("no proactive daemon running (no PID file)")
        return

    if status.stale:
        clear_pidfile(pidpath)
        if as_json:
            click.echo(
                json.dumps(
                    {
                        "stopped": False,
                        "reason": "stale pidfile cleared",
                        "pid": status.pid,
                    }
                )
            )
            return
        click.echo(f"PID {status.pid} not running; cleared stale PID file")
        return

    try:
        os.kill(status.pid, 15)  # SIGTERM
    except ProcessLookupError:
        clear_pidfile(pidpath)
        if as_json:
            click.echo(json.dumps({"stopped": False, "reason": "process vanished"}))
            return
        click.echo(f"PID {status.pid} already gone")
        return

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not inspect(pidpath).running:
            if as_json:
                click.echo(json.dumps({"stopped": True, "pid": status.pid}))
                return
            click.echo(f"stopped proactive daemon (PID {status.pid})")
            return
        time.sleep(0.1)

    if as_json:
        click.echo(
            json.dumps(
                {
                    "stopped": False,
                    "reason": "timeout",
                    "pid": status.pid,
                    "timeout_s": timeout,
                }
            )
        )
        sys.exit(1)
    click.secho(
        f"timed out waiting for PID {status.pid} to exit after {timeout:.1f}s",
        fg="red",
        err=True,
    )
    sys.exit(1)


@proactive.command("status")
@click.option("--json", "as_json", is_flag=True)
def proactive_status(as_json: bool) -> None:
    """Report whether the daemon is running and what it has sampled."""
    from sqlalchemy import func, select

    from newton.db import get_session
    from newton.models.system_metric import SystemMetric
    from newton.proactive.pidfile import inspect

    pidpath = _proactive_pidfile_path()
    pid_status = inspect(pidpath)

    counts: dict[str, int] = {}
    last_sample_iso: str | None = None
    with get_session() as session:
        rows = session.execute(
            select(SystemMetric.metric_type, func.count()).group_by(
                SystemMetric.metric_type
            )
        ).all()
        counts = {row[0]: int(row[1]) for row in rows}

        last = session.execute(
            select(SystemMetric.captured_at)
            .order_by(SystemMetric.captured_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if last is not None:
            last_sample_iso = last.isoformat()

    payload = {
        "running": pid_status.running,
        "pid": pid_status.pid,
        "stale_pidfile": pid_status.stale,
        "pidfile": str(pidpath),
        "samples_per_type": counts,
        "samples_total": sum(counts.values()),
        "last_sample_at": last_sample_iso,
    }

    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return

    console = Console()
    if pid_status.running:
        console.print(f"[green]running[/green] (PID {pid_status.pid})")
    elif pid_status.stale:
        console.print(f"[yellow]stale PID file[/yellow] (PID {pid_status.pid})")
    else:
        console.print("[dim]not running[/dim]")

    total = payload["samples_total"]
    console.print(f"samples: {total} total")
    for name, count in sorted(counts.items()):
        console.print(f"  {name:12s} {count}")
    if last_sample_iso:
        console.print(f"last sample: {last_sample_iso}")


@proactive.command("test-alert")
@click.argument("kind")
@click.option("--user", "user_id", default="sir", show_default=True)
@click.option(
    "--value",
    "value_override",
    type=float,
    default=None,
    help=(
        "Override the synthetic sample value. By default the CLI picks a "
        "value guaranteed to cross the rule's threshold."
    ),
)
@click.option(
    "--ignore-cooldown",
    is_flag=True,
    help="Insert the synthetic sample even if a recent alert of this kind exists.",
)
@click.option("--json", "as_json", is_flag=True)
def proactive_test_alert(
    kind: str,
    user_id: str,
    value_override: float | None,
    ignore_cooldown: bool,
    as_json: bool,
) -> None:
    """Inject a synthetic sample and run the alert checker for one rule.

    Used by the design-doc verification flow:
    ``newton proactive test-alert battery_low`` writes a sample that
    crosses the ``battery_low`` threshold and inserts the resulting
    notification row.
    """
    from newton.db import get_session
    from newton.models.proactive_notification import ProactiveNotification
    from newton.models.system_metric import SystemMetric
    from newton.proactive.alerts import AlertChecker
    from newton.proactive.config import load_proactive_config

    config = load_proactive_config()
    rule = next((r for r in config.thresholds if r.kind == kind), None)
    if rule is None:
        click.secho(f"error: no rule with kind={kind!r}", fg="red", err=True)
        sys.exit(1)
    if rule.dormant:
        click.secho(
            f"error: rule {kind!r} is dormant — no monitor produces "
            f"metric_type={rule.metric_type!r} yet",
            fg="red",
            err=True,
        )
        sys.exit(1)

    # Default test value: just over the threshold for '>', just under for '<'.
    if value_override is not None:
        test_value = value_override
    elif rule.op == ">":
        test_value = rule.value + 1.0
    else:  # rule.op == "<"
        test_value = max(0.0, rule.value - 1.0)

    checker = AlertChecker(config=config)

    with get_session() as session:
        session.add(SystemMetric(metric_type=rule.metric_type, value=float(test_value)))
        session.flush()

        if ignore_cooldown:
            # Wipe matching cooldown rows so the checker fires fresh.
            session.query(ProactiveNotification).filter(
                ProactiveNotification.user_id == user_id,
                ProactiveNotification.notification_text.like(f"[{kind}] %"),
            ).delete(synchronize_session=False)

        fired = checker.run(session, user_id)

    matching = [a for a in fired if a.kind == kind]
    payload = {
        "kind": kind,
        "value": test_value,
        "fired": bool(matching),
        # Always emit display-only text; the [kind] prefix is storage-only.
        "alerts": [
            {"kind": a.kind, "value": a.value, "text": a.display} for a in fired
        ],
    }
    if not matching:
        payload["reason"] = "in cooldown — pass --ignore-cooldown to force"

    if as_json:
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    console = Console()
    if matching:
        a = matching[0]
        # Show kind: text, no square brackets — Rich would parse them as
        # markup. Operator CLI surface; the actual user-facing prose is
        # already prefix-stripped via a.display.
        console.print(f"[green]fired[/green]  {a.kind}: {a.display}")
    else:
        console.print(
            f"[yellow]not fired[/yellow]  {kind}: in cooldown "
            f"(--ignore-cooldown to force)"
        )


# ── proactive patterns subgroup (step 4.3) ─────────────────────────────────


@proactive.group("patterns")
def proactive_patterns() -> None:
    """Inspect and manage learned user_patterns rows."""


@proactive_patterns.command("learn")
@click.option("--user", "user_id", default="sir", show_default=True)
@click.option(
    "--once",
    is_flag=True,
    help="Run one pass and exit. The cron / timer wiring lands in a later step.",
)
@click.option("--json", "as_json", is_flag=True)
def patterns_learn(user_id: str, once: bool, as_json: bool) -> None:
    """Detect patterns from existing tables and upsert user_patterns rows."""
    from newton.db import get_session
    from newton.proactive.patterns.learner import PatternLearner

    if not once:
        click.secho(
            "error: cron / timer wiring not implemented yet; pass --once",
            fg="red",
            err=True,
        )
        sys.exit(1)

    learner = PatternLearner()
    with get_session() as session:
        report = learner.run(session, user_id)

    payload = {
        "user_id": report.user_id,
        "window_start": report.window_start.isoformat(),
        "window_end": report.window_end.isoformat(),
        "inserted": report.inserted,
        "updated": report.updated,
        "pattern_ids": report.pattern_ids,
    }
    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return

    console = Console()
    console.print(
        f"learn: {report.inserted} inserted, {report.updated} updated "
        f"({len(report.pattern_ids)} total) over "
        f"{report.window_start.date()} → {report.window_end.date()}"
    )


@proactive_patterns.command("list")
@click.option("--user", "user_id", default=None, help="Filter by user_id.")
@click.option(
    "--type",
    "pattern_type",
    type=click.Choice(["time", "sequence", "context"]),
    default=None,
    help="Filter by pattern_type.",
)
@click.option("--json", "as_json", is_flag=True)
def patterns_list(user_id: str | None, pattern_type: str | None, as_json: bool) -> None:
    """List learned patterns, highest confidence first."""
    from sqlalchemy import select

    from newton.db import get_session
    from newton.models.user_pattern import UserPattern

    with get_session() as session:
        q = select(UserPattern)
        if user_id:
            q = q.where(UserPattern.user_id == user_id)
        if pattern_type:
            q = q.where(UserPattern.pattern_type == pattern_type)
        q = q.order_by(UserPattern.confidence.desc().nulls_last())
        rows = list(session.execute(q).scalars().all())

    data = [
        {
            "pattern_id": r.pattern_id,
            "user_id": r.user_id,
            "pattern_type": r.pattern_type,
            "confidence": r.confidence,
            "occurrences": r.occurrences,
            "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            "data": json.loads(r.pattern_data_json) if r.pattern_data_json else None,
        }
        for r in rows
    ]
    if as_json:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False))
        return

    console = Console()
    if not data:
        console.print("[dim]no patterns[/dim]")
        return
    table = Table(title="user_patterns")
    table.add_column("id", justify="right")
    table.add_column("user")
    table.add_column("type")
    table.add_column("confidence", justify="right")
    table.add_column("occurrences", justify="right")
    table.add_column("data")
    for r in data:
        conf = f"{r['confidence']:.3f}" if r["confidence"] is not None else "—"
        table.add_row(
            str(r["pattern_id"]),
            r["user_id"],
            r["pattern_type"],
            conf,
            str(r["occurrences"]),
            json.dumps(r["data"], ensure_ascii=False) if r["data"] else "",
        )
    console.print(table)


@proactive_patterns.command("show")
@click.argument("pattern_id", type=int)
@click.option("--json", "as_json", is_flag=True)
def patterns_show(pattern_id: int, as_json: bool) -> None:
    """Show a pattern with both stored confidence and a live-recomputed one.

    Stored confidence is what the last ``learn`` run wrote. Live
    confidence is recomputed *now* from the row's counts + current
    config — so if you tuned ``half_life_days`` since the last learn,
    the divergence is visible rather than silently confusing.
    """
    from datetime import datetime

    from newton.db import get_session
    from newton.models.user_pattern import UserPattern
    from newton.proactive.config import load_proactive_config
    from newton.proactive.patterns.confidence import score_with_breakdown

    with get_session() as session:
        row = session.get(UserPattern, pattern_id)
        if row is None:
            click.secho(f"error: no pattern with id={pattern_id}", fg="red", err=True)
            sys.exit(1)

        # Approximate the opportunities denominator. The row doesn't
        # store opportunities — only occurrences — so we recompute by
        # re-running the relevant detector. For show, that overhead is
        # fine and ensures the live breakdown is accurate.
        opportunities = _recompute_opportunities(session, row)

        cfg = load_proactive_config().patterns
        now = datetime.now()
        bd = score_with_breakdown(
            occurrences=row.occurrences,
            opportunities=opportunities,
            last_seen=row.last_seen,
            now=now,
            config=cfg,
        )
        payload = {
            "pattern_id": row.pattern_id,
            "user_id": row.user_id,
            "pattern_type": row.pattern_type,
            "data": json.loads(row.pattern_data_json)
            if row.pattern_data_json
            else None,
            "stored_confidence": row.confidence,
            "live_confidence": bd.score,
            "live_breakdown": {
                "occurrences": bd.occurrences,
                "opportunities": bd.opportunities,
                "days_since_last_seen": bd.days_since_last_seen,
                "penalty": bd.penalty,
                "consistency": bd.consistency,
                "volume_factor": bd.volume_factor,
                "recency_factor": bd.recency_factor,
                "raw": bd.raw,
                "floor_passed": bd.floor_passed,
                "opportunities_passed": bd.opportunities_passed,
            },
            "live_explain": bd.explain(),
            "last_seen": row.last_seen.isoformat() if row.last_seen else None,
        }

    if as_json:
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    console = Console()
    console.print(
        f"[bold]#{payload['pattern_id']}[/bold] {payload['pattern_type']} "
        f"({payload['user_id']})"
    )
    console.print(f"  data: {json.dumps(payload['data'], ensure_ascii=False)}")
    stored = payload["stored_confidence"]
    stored_str = f"{stored:.3f}" if stored is not None else "—"
    console.print(f"  stored confidence: {stored_str}")
    console.print(f"  live confidence  : {payload['live_confidence']:.3f}")
    console.print(f"  explain          : {payload['live_explain']}")


def _recompute_opportunities(db_session, row) -> int:
    """Re-run the relevant detector to recover the opportunities count.

    Only used by ``patterns show``; the cost is one extra scan over
    the observation window per show. Worth it for explainability.
    """
    from datetime import datetime, timedelta

    from newton.proactive.config import load_proactive_config
    from newton.proactive.patterns import sequence, time_based

    cfg = load_proactive_config().patterns
    now = datetime.now()
    window_start = now - timedelta(days=cfg.observation_window_days)
    sig = json.loads(row.pattern_data_json) if row.pattern_data_json else {}

    if row.pattern_type == "time":
        for obs in time_based.detect(
            db_session, row.user_id, window_start, cfg.pattern_timezone
        ):
            if obs.signature() == sig:
                return obs.opportunities
    elif row.pattern_type == "sequence":
        for obs in sequence.detect(
            db_session,
            row.user_id,
            window_start,
            cfg.sequence.default_window_seconds,
        ):
            if obs.signature() == sig:
                return obs.opportunities
    # context, or fell out of the window entirely
    return 0


@proactive_patterns.command("forget")
@click.argument("pattern_id", type=int)
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def patterns_forget(pattern_id: int, yes: bool) -> None:
    """Delete one pattern row. Use when a routine has changed and decay is too slow."""
    from newton.db import get_session
    from newton.models.user_pattern import UserPattern

    if not yes:
        click.confirm(f"Forget pattern #{pattern_id}?", abort=True)

    with get_session() as session:
        row = session.get(UserPattern, pattern_id)
        if row is None:
            click.secho(f"error: no pattern with id={pattern_id}", fg="red", err=True)
            sys.exit(1)
        session.delete(row)

    click.echo(f"forgot pattern #{pattern_id}")


@proactive.command("seed-test-data")
@click.option("--user", "user_id", default="sir", show_default=True)
@click.option("--weeks", default=4, show_default=True, type=int)
@click.option("--seed", default=42, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
def proactive_seed_test_data(
    user_id: str, weeks: int, seed: int, as_json: bool
) -> None:
    """Insert deterministic synthetic activity so the learner has data to chew on."""
    from newton.db import get_session
    from newton.proactive.patterns.seed import seed_test_data

    with get_session() as session:
        report = seed_test_data(session, user_id=user_id, weeks=weeks, seed=seed)

    payload = {
        "user_id": report.user_id,
        "weeks": report.weeks,
        "seed": report.seed,
        "sessions_added": report.sessions_added,
        "tool_approvals_added": report.tool_approvals_added,
        "expected_patterns": report.expected_patterns,
    }
    if as_json:
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    console = Console()
    console.print(
        f"seeded: {report.sessions_added} sessions, "
        f"{report.tool_approvals_added} tool_approvals "
        f"({weeks} weeks, seed={seed})"
    )
    for p in report.expected_patterns:
        console.print(f"  expect: {p}")


@proactive.command("predict")
@click.option("--user", "user_id", default="sir", show_default=True)
@click.option(
    "--mode",
    type=click.Choice(["off", "minimal", "smart", "aggressive"]),
    default=None,
    help="Override the configured default mode for this prediction.",
)
@click.option("--json", "as_json", is_flag=True)
def proactive_predict(user_id: str, mode: str | None, as_json: bool) -> None:
    """Show ranked predictions for ``user_id`` right now."""
    from newton.db import get_session
    from newton.proactive.anticipation import AnticipationEngine
    from newton.proactive.config import load_proactive_config
    from newton.proactive.context import assemble

    cfg = load_proactive_config()
    engine = AnticipationEngine(
        config=cfg.anticipation,
        pattern_timezone=cfg.patterns.pattern_timezone,
    )
    with get_session() as session:
        ctx = assemble(
            session,
            user_id,
            lookback_seconds=cfg.anticipation.sequence_relevance_seconds,
        )
        preds = engine.predict(session, ctx, mode=mode)

    payload = [
        {
            "pattern_id": p.pattern_id,
            "pattern_type": p.pattern_type,
            "action": p.action,
            "final": p.final,
            "eta": p.eta.isoformat() if p.eta else None,
            "notification_text": p.notification_text,
            "rationale": {
                "confidence": p.rationale.confidence,
                "relevance": p.rationale.relevance,
                "mode": p.rationale.mode,
                "threshold": p.rationale.threshold,
                "threshold_passed": p.rationale.threshold_passed,
                "factors": p.rationale.factors,
                "explain": p.rationale.explain(),
            },
        }
        for p in preds
    ]
    if as_json:
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    console = Console()
    if not preds:
        console.print(
            f"[dim]no predictions for {user_id} "
            f"(mode={mode or cfg.anticipation.default_mode})[/dim]"
        )
        return
    for i, p in enumerate(preds, 1):
        eta_str = p.eta.isoformat() if p.eta else "—"
        console.print(
            f"[bold]{i}.[/bold] {p.action}  final={p.final:.3f}  eta={eta_str}"
        )
        console.print(f"   text: {p.notification_text}")
        console.print(f"   why : {p.rationale.explain()}")


@proactive.command("schedule")
@click.option("--user", "user_id", default="sir", show_default=True)
@click.option(
    "--mode",
    type=click.Choice(["off", "minimal", "smart", "aggressive"]),
    default=None,
    help="Override the configured default mode.",
)
@click.option(
    "--urgent",
    is_flag=True,
    help="Bypass quiet hours (later steps will use this for calendar etc).",
)
@click.option("--json", "as_json", is_flag=True)
def proactive_schedule(
    user_id: str, mode: str | None, urgent: bool, as_json: bool
) -> None:
    """Run one scheduler tick: predict, gate, write rows."""
    from newton.db import get_session
    from newton.proactive.config import load_proactive_config
    from newton.proactive.scheduler import build_default_scheduler

    cfg = load_proactive_config()
    chosen_mode = mode or cfg.anticipation.default_mode
    scheduler = build_default_scheduler()

    with get_session() as session:
        report = scheduler.tick(session, user_id, chosen_mode, urgent=urgent)

    payload = {
        "user_id": report.user_id,
        "mode": report.mode,
        "reason": report.reason,
        "scheduled_ids": report.scheduled,
        "skipped": report.skipped,
    }
    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return

    console = Console()
    if report.reason:
        console.print(f"[dim]tick skipped: {report.reason}[/dim]")
    if report.scheduled:
        console.print(
            f"[green]scheduled[/green] {len(report.scheduled)} "
            f"notification(s): {report.scheduled}"
        )
    for s in report.skipped:
        console.print(
            f"[yellow]skipped[/yellow]  pattern #{s['pattern_id']}: {s['reason']}"
        )


@proactive.command("notifications")
@click.option("--user", "user_id", default=None, help="Filter to one user.")
@click.option("--last", "last_n", default=10, show_default=True, type=int)
@click.option(
    "--pending-only",
    is_flag=True,
    help="Show only notifications without a recorded user_response.",
)
@click.option("--json", "as_json", is_flag=True)
def proactive_notifications(
    user_id: str | None, last_n: int, pending_only: bool, as_json: bool
) -> None:
    """List recent proactive_notifications rows."""
    from sqlalchemy import select

    from newton.db import get_session
    from newton.models.proactive_notification import ProactiveNotification
    from newton.proactive.alerts import display_text

    with get_session() as session:
        q = select(ProactiveNotification)
        if user_id:
            q = q.where(ProactiveNotification.user_id == user_id)
        if pending_only:
            q = q.where(ProactiveNotification.user_response.is_(None))
        q = q.order_by(ProactiveNotification.notification_id.desc()).limit(last_n)
        rows = list(session.execute(q).scalars().all())

    data = [
        {
            "notification_id": r.notification_id,
            "user_id": r.user_id,
            "trigger_pattern_id": r.trigger_pattern_id,
            # display_text strips the [kind] prefix from alert rows.
            # Scheduler rows have no prefix, so this is a pass-through.
            "text": display_text(r.notification_text),
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            "user_response": r.user_response,
            "response_at": r.response_at.isoformat() if r.response_at else None,
        }
        for r in rows
    ]
    if as_json:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False))
        return

    console = Console()
    if not data:
        console.print("[dim]no notifications[/dim]")
        return
    for d in data:
        status = d["user_response"] or "pending"
        console.print(
            f"#{d['notification_id']:3d} [{status}] ({d['sent_at']}) {d['text']}"
        )


@proactive.command("react")
@click.argument("notification_id", type=int)
@click.option(
    "--accept",
    "reaction",
    flag_value="accepted",
    help="Record an acceptance.",
)
@click.option(
    "--reject",
    "reaction",
    flag_value="rejected",
    help="Record a rejection.",
)
@click.option(
    "--ignore",
    "reaction",
    flag_value="ignored",
    help="Record an explicit ignore (auto-ignore happens after the configured grace).",
)
@click.option("--json", "as_json", is_flag=True)
def proactive_react(notification_id: int, reaction: str, as_json: bool) -> None:
    """Record sir's reaction to a notification."""
    from newton.db import get_session
    from newton.proactive.learning import record_reaction

    if not reaction:
        click.secho(
            "error: pass one of --accept / --reject / --ignore",
            fg="red",
            err=True,
        )
        sys.exit(1)

    try:
        with get_session() as session:
            result = record_reaction(session, notification_id, reaction)
    except ValueError as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)

    payload = {
        "notification_id": result.notification_id,
        "user_id": result.user_id,
        "pattern_id": result.pattern_id,
        "reaction": result.reaction,
        "response_at": result.response_at.isoformat(),
    }
    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(
        f"recorded {reaction} for notification #{notification_id} "
        f"(pattern #{result.pattern_id})"
    )


@proactive.command("watch")
@click.option("--user", "user_id", default=None, help="Filter to one user.")
@click.option(
    "--interval",
    type=float,
    default=2.0,
    show_default=True,
    help="Seconds between DB polls.",
)
@click.option(
    "--no-desktop",
    is_flag=True,
    help="Don't try the notify-send channel — CLI only.",
)
def proactive_watch(user_id: str | None, interval: float, no_desktop: bool) -> None:
    """Stream pending proactive notifications until Ctrl-C."""
    import time

    from sqlalchemy import select

    from newton.db import get_session
    from newton.models.proactive_notification import ProactiveNotification
    from newton.proactive.delivery import (
        CLIDeliveryChannel,
        DeliveryDispatcher,
        DesktopDeliveryChannel,
    )

    dispatcher = DeliveryDispatcher()
    dispatcher.add(CLIDeliveryChannel())
    if not no_desktop:
        dispatcher.add(DesktopDeliveryChannel())

    click.echo("watching pending proactive notifications (Ctrl-C to stop)")
    try:
        while True:
            with get_session() as session:
                q = select(ProactiveNotification).where(
                    ProactiveNotification.user_response.is_(None)
                )
                if user_id:
                    q = q.where(ProactiveNotification.user_id == user_id)
                q = q.order_by(ProactiveNotification.notification_id)
                rows = list(session.execute(q).scalars().all())

            for row in rows:
                dispatcher.deliver(row)

            time.sleep(interval)
    except KeyboardInterrupt:
        click.echo("\nstopped watching")


def _parse_duration(text: str) -> float:
    """Parse '1h', '30m', '45s', or a bare number-of-seconds."""
    text = text.strip().lower()
    if not text:
        raise ValueError("empty duration")
    if text[-1] == "h":
        return float(text[:-1]) * 3600.0
    if text[-1] == "m":
        return float(text[:-1]) * 60.0
    if text[-1] == "s":
        return float(text[:-1])
    return float(text)


@proactive.command("mode")
@click.argument("mode", required=False)
@click.option("--user", "user_id", default="sir", show_default=True)
@click.option(
    "--for",
    "for_duration",
    default=None,
    help="Time-bounded duration like '1h', '30m', '45s'. Omit for permanent.",
)
@click.option(
    "--list",
    "do_list",
    is_flag=True,
    help="List all users' modes instead of changing one.",
)
@click.option("--json", "as_json", is_flag=True)
def proactive_mode(
    mode: str | None,
    user_id: str,
    for_duration: str | None,
    do_list: bool,
    as_json: bool,
) -> None:
    """Change a user's proactive mode (off/minimal/smart/aggressive)."""
    from newton.db import get_session
    from newton.proactive.modes import (
        VALID_MODES,
        list_modes,
        resolve_mode,
        set_mode,
    )

    if do_list:
        with get_session() as session:
            modes = list_modes(session)
        payload = [
            {
                "user_id": m.user_id,
                "mode": m.mode,
                "revert_at": m.revert_at.isoformat() if m.revert_at else None,
            }
            for m in modes
        ]
        if as_json:
            click.echo(json.dumps(payload, indent=2))
            return
        if not payload:
            click.echo("(no users)")
            return
        for m in payload:
            extra = f" → reverts at {m['revert_at']}" if m["revert_at"] else ""
            click.echo(f"{m['user_id']:8s} {m['mode']}{extra}")
        return

    if mode is None:
        # No mode argument and not --list ⇒ show this user's current mode.
        with get_session() as session:
            resolved = resolve_mode(session, user_id)
        payload = {
            "user_id": resolved.user_id,
            "mode": resolved.mode,
            "revert_at": resolved.revert_at.isoformat() if resolved.revert_at else None,
            "reverted_now": resolved.reverted_now,
        }
        if as_json:
            click.echo(json.dumps(payload, indent=2))
            return
        extra = f" (reverts at {resolved.revert_at})" if resolved.revert_at else ""
        click.echo(f"{user_id}: {resolved.mode}{extra}")
        return

    if mode not in VALID_MODES:
        click.secho(
            f"error: mode must be one of {VALID_MODES}, got {mode!r}",
            fg="red",
            err=True,
        )
        sys.exit(1)

    for_seconds = None
    if for_duration is not None:
        try:
            for_seconds = _parse_duration(for_duration)
        except ValueError as e:
            click.secho(f"error: bad --for value: {e}", fg="red", err=True)
            sys.exit(1)

    try:
        with get_session() as session:
            result = set_mode(session, user_id, mode, for_seconds=for_seconds)
    except ValueError as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)

    payload = {
        "user_id": result.user_id,
        "mode": result.mode,
        "revert_at": result.revert_at.isoformat() if result.revert_at else None,
    }
    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return
    extra = f" (reverts at {result.revert_at})" if result.revert_at else ""
    click.echo(f"{user_id} → {mode}{extra}")


@proactive.command("recall-check")
@click.argument("message")
@click.option("--user", "user_id", default="sir", show_default=True)
@click.option("--persona", "persona_id", default="jarvis", show_default=True)
@click.option(
    "--mode",
    type=click.Choice(["off", "minimal", "smart", "aggressive"]),
    default=None,
    help="Override the user's stored mode for this check.",
)
@click.option("--json", "as_json", is_flag=True)
def proactive_recall_check(
    message: str,
    user_id: str,
    persona_id: str,
    mode: str | None,
    as_json: bool,
) -> None:
    """Run one vault-driven recall check against ``message``.

    Useful for verification before the message-insert hook is wired
    in a later block. Fires a real proactive_notifications row when
    the top vault match crosses the configured threshold.
    """
    import asyncio

    from newton.db import get_session
    from newton.proactive.config import load_proactive_config
    from newton.proactive.modes import resolve_mode
    from newton.proactive.recall import check

    cfg = load_proactive_config()

    async def _run() -> dict:
        with get_session() as session:
            effective_mode = (
                mode
                or resolve_mode(
                    session, user_id, default=cfg.anticipation.default_mode
                ).mode
            )
            event = await check(
                session,
                message,
                user_id,
                persona_id,
                mode=effective_mode,
                config=cfg.recall,
            )
            return {
                "fired": event.fired,
                "reason": event.reason,
                "notification_id": event.notification_id,
                "note_id": event.note_id,
                "score": event.score,
                "mode": effective_mode,
            }

    try:
        payload = asyncio.run(_run())
    except Exception as e:  # noqa: BLE001
        click.secho(f"error: {type(e).__name__}: {e}", fg="red", err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    console = Console()
    if payload["fired"]:
        console.print(
            f"[green]fired[/green]  notification #{payload['notification_id']} "
            f"(note {payload['note_id']}, score {payload['score']:.3f})"
        )
    else:
        score = payload["score"]
        s = f" score={score:.3f}" if score is not None else ""
        console.print(f"[dim]no recall[/dim]  reason={payload['reason']}{s}")


def main() -> None:
    """Console-script entry point."""
    cli()  # type: ignore[no-value-for-parameter]


if __name__ == "__main__":
    main()
