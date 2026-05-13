# Block 1 — Identity & Data Foundation

Tag: `v0.1.0-block1`
Branch: `newton-main`

## What this block delivers

The plumbing that makes Newton a multi-persona, multi-user system instead
of a single-tenant chatbot. After block 1, the database knows who can
talk to which persona, the CLI can bootstrap a fresh machine to a usable
state, and every later block can build on a verified foundation.

Concretely:

- A configuration loader that parses and validates `personas.yaml`.
- A SQLite schema covering 13 tables across identity, auth, guest, and
  proactive concerns, with foreign-key constraints enforced.
- A migration runner that applies idempotent SQL files in order.
- SQLAlchemy 2.x ORM models for every table.
- A seeder that lays down three personas (Butler, JARVIS, Friday) and
  two users (`sir`/Alex, `gf`/Stella) in foreign-key-safe order.
- A CLI with seven subcommands covering setup, inspection, and debugging.
- 38 pytest cases keeping it honest.

What this block deliberately does **not** include: voice routing, vault,
tool calling, proactive engine, web UI. Those come in blocks 2 through 10.

## Steps and commits

| Step | Outcome                                              | Commit     |
|------|------------------------------------------------------|------------|
| 1.1  | OpenJarvis fork verified, preflight passes 9/9       | `v0.0.1-fork` |
| 1.2  | `newton/` package skeleton + `scripts/newton/`       | `de55414`  |
| 1.3  | Pydantic config loader, `${OWNER_DISPLAY_NAME}` substitution | `91ce3a6`  |
| 1.4  | SQL schema + idempotent migration runner             | `10f4451`  |
| 1.5  | SQLAlchemy ORM models for all 13 tables              | `511b992`  |
| 1.6  | Seed (Alex/Stella) + CLI init/seed/personas/users    | `4ccc92d`  |
| 1.7  | `newton status` command + `docs/newton/cli.md`       | `5db58a2`  |
| 1.8  | This summary + tag `v0.1.0-block1`                   | (this tag) |

## Key design decisions (locked)

These shape every following block, so they're written down once here.

**Newton lives next to OpenJarvis, not inside it.**
OpenJarvis is treated as an upstream LLM runtime. Newton's code lives
under `newton/`, `scripts/newton/`, `tests/newton/`, `docs/newton/`,
`migrations/`, `config/`, `data/`. We never touch OpenJarvis files —
this keeps future merges from upstream clean.

**Personal names live in the database, not in git.**
`personas.yaml` carries `${OWNER_DISPLAY_NAME}` placeholders. The real
names (`Alex`, `Stella`) sit in `users.display_name`. Substitution
happens at LLM-call time via `render_personality()`. The repository can
be hosted publicly without leaking household identities.

**Sync SQLAlchemy 2.x, no Alembic.**
Newton uses synchronous SQLAlchemy with the `Mapped[T]` / `mapped_column`
style. Migrations are bare `.sql` files under `migrations/`, applied by
our own runner. Alembic was considered and rejected as overkill for the
expected migration cadence; if it becomes useful later, the
`_migrations` table is already laid out compatibly.

**Foreign keys are enforced at the database, not just in code.**
Every relation has a `FOREIGN KEY` clause. `PRAGMA foreign_keys = ON`
is set on every connection via a SQLAlchemy `connect` event listener,
so there is no way to forget at a call site. ON DELETE follows a clear
rule:

- Personal data (sessions, screen_captures, calendar) → `CASCADE`
  (deleting a user wipes their stuff, GDPR-friendly).
- Audit / security records (auth_attempts, registration_requests) →
  `SET NULL` (keep the trail, drop the personal pointer).
- Activity-blocking relations (sessions referencing a persona) →
  `RESTRICT` (can't delete a persona that's in use).

**ChatSession, not Session.**
The SQL table is `sessions`, but the Python class is `ChatSession` so it
doesn't shadow `sqlalchemy.orm.Session`. Tests, fixtures, and call sites
all read more clearly as a result.

**Idempotency everywhere.**
`db migrate`, `seed`, and `init` are all safe to rerun. The seeder reads
rows before inserting rather than relying on `INSERT OR IGNORE`, which
is verbose but transparent under `pdb`.

**`--json` is part of the contract; human output isn't.**
Every command that prints data supports `--json`. Tooling targets that;
the prose output is informational and may shift between versions.

**Thin CLI, thick library.**
`newton/cli.py` is mostly click boilerplate. Real work lives in
`newton.config`, `newton.db`, `newton.seed`, `newton.models`, so the
same operations are reusable from voice, web, and MCP integrations in
later blocks without duplication.

## What you can do after this block

```bash
# First-time setup on a fresh machine
uv run newton init

# Snapshot of system state
uv run newton status

# Inspect anything
uv run newton config show
uv run newton personas list
uv run newton users list
uv run newton db status

# Run the suite
uv run pytest tests/newton/ -v
```

`newton status` is the single best command for "is everything OK?"

## Verification

Block-1.md acceptance criteria, all met:

- `uv run newton init` creates the database, applies migration 001,
  inserts 3 personas, 2 users, 2 user_persona_link rows. Idempotent
  on rerun.
- `uv run newton personas list` shows
  `butler (public, default)`, `jarvis (owner: Alex)`, `friday (owner: Stella)`.
- `uv run newton users list` shows
  `sir Alex default: jarvis`, `gf Stella default: friday`.
- `sqlite3 data/newton.db ".tables"` lists all 13 tables plus `_migrations`.
- `uv run pytest tests/newton/ -v` reports `38 passed`.
- `./scripts/newton/preflight.sh` reports `9/9 ✓`.
- OpenJarvis's own test collection still works (one unrelated
  `polars` import error, pre-existing).

## Known limits (resolved in later blocks)

- **No fallback auth yet.** Voice/face embeddings are nullable columns;
  the actual capture pipeline lands in blocks 4 (voice) and 5 (face).
  PIN/passphrase fallback policy is parsed from `personas.yaml` but
  not yet enforced — block 5 adds the verifier.
- **`default_persona_id` on users is a soft pointer.** No foreign key
  on the column. This is intentional — the persona may be renamed or
  re-scoped, and the user's preference should survive. Resolution
  happens at lookup time.
- **No timezone awareness.** SQLite `TIMESTAMP` columns are naive UTC
  by convention. Block 8 (proactive) introduces explicit `tzinfo` where
  scheduling needs it.
- **Empty proactive tables.** `system_metrics`, `user_patterns`,
  `proactive_notifications`, `screen_captures`, `calendar_events` have
  schema but no producers yet. Block 8 wires the producers.
- **No web/voice/tool surface.** Block 1 is operator-only. End users
  will get their interface in blocks 3 (channel routing) and 7 (web UI).

## Entry conditions for block 2

Block 2 (Tool calling + approval hook) can assume:

- `newton init` has been run on the target machine.
- `sir` and `gf` exist in the database with `display_name` set.
- The three personas exist with their `system_prompt` and
  `voice_config_json` populated.
- `get_session()` yields a working SQLAlchemy session against the
  Newton SQLite database with foreign keys enforced.
- `render_personality(persona, owner_display_name)` is the canonical
  way to materialize a persona's system prompt for an LLM call.

If `newton status` reports everything green, block 2 is good to start.
