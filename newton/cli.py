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


def main() -> None:
    """Console-script entry point."""
    cli()  # type: ignore[no-value-for-parameter]


if __name__ == "__main__":
    main()
