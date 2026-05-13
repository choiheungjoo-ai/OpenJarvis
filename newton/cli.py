"""Newton CLI — entry point for operator commands.

Used by ``sir`` (and not by end users — end users speak to Newton via voice,
web, or mobile). Keep this CLI focused on operations: DB migration, persona
seeding, vault indexing, telemetry inspection, etc.

Implementation note: a click ``group`` is used so subcommands can be added in
later steps (1.7 adds ``init`` / ``db`` / ``personas`` / ``users`` / ``seed``).
For now the group is bare on purpose — running ``newton`` with no subcommand
just prints help.

CLI logic stays thin. Real work happens in ``newton.core.*`` services so the
same operations can be invoked from voice, web, or MCP later without
duplicating logic.
"""

from __future__ import annotations

import click

from newton import __version__

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


# Future subcommands (added in Step 1.7):
#   cli.add_command(init_cmd)        # newton init
#   cli.add_command(config_group)    # newton config show / set
#   cli.add_command(db_group)        # newton db migrate / status
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
