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


def main() -> None:
    """Console-script entry point."""
    cli()  # type: ignore[no-value-for-parameter]


if __name__ == "__main__":
    main()
