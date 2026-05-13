"""Newton CLI — entry point for operator commands.

Used by ``sir`` (and not by end users — end users speak to Newton via voice,
web, or mobile). Keep this CLI focused on operations: DB migration, persona
seeding, vault indexing, telemetry inspection, etc.

Implementation note: a click ``group`` is used so subcommands can be added in
later steps (1.7 adds ``init`` / ``personas`` / ``users`` / ``seed``).

CLI logic stays thin. Real work happens in ``newton.config`` / ``newton.db`` /
future ``newton.core.*`` so the same operations can be invoked from voice,
web, or MCP later without duplicating logic.
"""

from __future__ import annotations

import json
import sys

import click
from rich.console import Console
from rich.table import Table

from newton import __version__
from newton.config import ConfigError, load_config
from newton.db import DataError, init_db, migration_status

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
    # No subcommand → show help. Avoids the "did nothing" feeling.
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ─────────────────────────────────────────────────────────────────────────────
# config group  —  inspect Newton's loaded configuration
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
        # ``model_dump`` honours pydantic's serialization; mode='json' keeps
        # types like nested models flattened to JSON-friendly dicts.
        click.echo(
            json.dumps(cfg.model_dump(mode="json"), indent=2, ensure_ascii=False)
        )
        return

    console = Console()

    # ── Personas table ──
    p_table = Table(
        title="Personas",
        show_header=True,
        header_style="bold",
        title_style="bold",
    )
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

    # ── Identity policy ──
    i_table = Table(
        title="Identity policy",
        show_header=True,
        header_style="bold",
        title_style="bold",
    )
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

    # ── One-line summary ──
    fb = cfg.identity.fallback
    fb_str = ", ".join(fb.methods) if fb.enabled and fb.methods else "disabled"
    console.print(
        f"guest_mode={'on' if cfg.identity.guest_mode_enabled else 'off'} "
        f"· fallback={fb_str}",
        style="dim",
    )


# ─────────────────────────────────────────────────────────────────────────────
# db group  —  database / migrations
# ─────────────────────────────────────────────────────────────────────────────


@cli.group()
def db() -> None:
    """Manage Newton's database (migrations, status)."""


@db.command("migrate")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit JSON: { applied: [...], already_applied: [...] }",
)
def db_migrate(as_json: bool) -> None:
    """Apply any pending migrations.  Idempotent — safe to rerun."""
    console = Console()

    try:
        # Snapshot before so we can show what was already done vs what's new.
        before = migration_status()
        already = list(before.applied)
        applied_now = init_db()
    except DataError as e:
        click.secho(f"error: {e}", fg="red", err=True)
        sys.exit(1)

    if as_json:
        click.echo(
            json.dumps(
                {"applied": applied_now, "already_applied": already},
                indent=2,
            )
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
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit JSON: { applied: [...], pending: [...], up_to_date: bool }",
)
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
    table = Table(
        title="Migrations",
        show_header=True,
        header_style="bold",
        title_style="bold",
    )
    table.add_column("version", style="cyan", justify="right")
    table.add_column("status")
    table.add_column("filename")

    # Applied rows first.  We only have filenames for *pending* migrations
    # in MigrationStatus; for applied versions we just show the version
    # number — the SQL files may not even exist on disk any more in a
    # restored deployment.
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


# Future subcommands (added in Step 1.7):
#   cli.add_command(init_cmd)        # newton init  (migrate + seed)
#   cli.add_command(personas_group)  # newton personas list / show
#   cli.add_command(users_group)     # newton users list / register
#   cli.add_command(seed_cmd)        # newton seed


# ─────────────────────────────────────────────────────────────────────────────
# Entry point used by ``newton`` console script (wired up in Step 1.2d via
# pyproject.toml). Also works for ``python -m newton.cli``.
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    """Console-script entry point."""
    cli()  # type: ignore[no-value-for-parameter]


if __name__ == "__main__":
    main()
