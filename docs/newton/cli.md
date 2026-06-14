# Newton CLI

Operator interface for `sir`. End users (sir, gf, guests) interact with
Newton via voice / web / mobile; this command line is for setup, debugging,
and recovery.

All commands are idempotent unless the documentation says otherwise. Where a
command emits output, a `--json` flag is available for tooling.

## Quick start

```bash
# First-time setup: create the database and seed the initial personas + users.
uv run newton init

# Check what Newton sees.
uv run newton status
```

That's it. Everything else is auxiliary.

## Command tree

```
newton
├── status        [--json]   snapshot of DB + personas + users + config
├── config show   [--json]   show parsed config/personas.yaml
├── db
│   ├── migrate   [--json]   apply pending migrations
│   └── status    [--json]   show applied / pending migrations
├── personas list [--json]   list personas (after seeding)
├── users list    [--json]   list users (after seeding)
├── seed          [--json]   insert initial personas + users
├── init          [--json]   migrate + seed in one shot
├── tools                    (block 2) list / run / show / policy
├── providers                (block 2) list / swap / active / usage
├── vault                    (block 3) RAG over the note vault
│   ├── index     [--json]   scan + chunk + embed + upsert to Qdrant
│   ├── search Q  --user --persona   ACL-filtered semantic search
│   └── quarantine           list / review guest activity
├── persona route --user --voice-stage2   resolve + render prompt
├── voice biasing            show / clear a user's STT bias dict
├── memory                   (block 3) summarize-session / recall
└── proactive                (block 4) monitoring + alerts + patterns + delivery
    ├── start                background sampler + alert + scheduler loop
    ├── stop                 SIGTERM the daemon, clear pidfile
    ├── status               daemon up? sample counts, last sample
    ├── test-alert <kind>    inject synthetic sample, force one rule
    ├── seed-test-data       deterministic 4-week activity for learning tests
    ├── patterns             learn --once / list / show / forget
    ├── predict              ranked predictions for now (confidence × relevance)
    ├── schedule             one tick: predict → gate → write rows
    ├── notifications        list recent rows (pending-only flag)
    ├── react <id>           --accept / --reject / --ignore
    ├── mode                 off/minimal/smart/aggressive [--for 1h] [--list]
    ├── watch                streaming delivery loop (CLI + desktop)
    └── recall-check <msg>   vault-driven recall against a message
```

## Conventions

**Human output** — colourful, prose-style, may change between versions.
Use this when reading at a terminal.

**`--json` output** — stable contract. Use this when scripting or piping
into other tools. Every command that prints data supports `--json`.

**Errors** — printed on stderr in red, with `error:` prefix. Exit code is
non-zero. JSON output mode still uses the same exit codes.

**Idempotency** — every mutating command (`db migrate`, `seed`, `init`) is
safe to rerun. Re-running is the recommended recovery action after most
transient failures.

## Reference

### `newton status`

Snapshot of Newton's data + configuration in one view. Read-only.

Sections:

- **Database**: path, file size, applied migration versions, schema state.
- **Personas**: count and per-persona summary (id, public/default flags,
  owner display name).
- **Users**: count and per-user summary (id, display name, default persona).
- **Config**: parsed `config/personas.yaml` summary (active retry profile,
  guest mode, fallback methods).

Use as the first command in any debugging session. If the database doesn't
exist yet, `status` still runs and reports "not initialized".

### `newton config show`

Pretty-print the parsed and validated `config/personas.yaml`. Verifies:

- Exactly one default persona.
- public/owner consistency (public personas have no owner; owner-bound
  personas are not public).
- Active retry profile is one of the defined profiles.

Errors are surfaced with a `ConfigError` and a clear pointer to the
offending field.

### `newton db migrate`

Apply any pending SQL migrations under `migrations/`. Files must match
`NNN_description.sql`. Each migration is wrapped in a single transaction,
so a failed migration rolls back cleanly.

After success, `_migrations.version` records the new high-water mark.
Re-running is a no-op once everything is applied.

### `newton db status`

Show which migration versions are applied vs pending. Read-only.

### `newton seed`

Insert three personas and two users in foreign-key-safe order:

```
1. users     — sir/Alex, gf/Stella
2. personas  — butler, jarvis, friday (FK on owner_user_id)
3. links     — user_persona_link rows (FK on both sides)
```

Idempotent — re-running inserts nothing if rows already exist.

Personality strings keep their `${OWNER_DISPLAY_NAME}` placeholder; the
substitution to real names happens at LLM-call time via
`newton.config.render_personality()`, not at seed time. This keeps
`personas.yaml` safe to commit to git.

### `newton personas list`

List personas after seeding. Human format follows block 1's design:

```
butler   (public, default)
jarvis   (owner: Alex)
friday   (owner: Stella)
```

`owner: Alex` is resolved by joining `personas.owner_user_id` against
`users.display_name`, so you see human names instead of opaque slugs.

### `newton users list`

List registered users:

```
sir   Alex     default persona: jarvis
gf    Stella   default persona: friday
```

### `newton init`

Convenience for first-time setup: `db migrate` followed by `seed`. Both
sub-steps are idempotent, so `newton init` itself is idempotent.

## Configuration sources

Two environment variables affect where Newton reads / writes:

- `NEWTON_CONFIG_DIR` — overrides the config directory (default:
  `<project_root>/config`).
- `NEWTON_DATA_DIR` — overrides the data directory (default:
  `<project_root>/data`).

The database is always `<data_dir>/newton.db`. The personas file is
always `<config_dir>/personas.yaml`.

These are used by the test suite to point Newton at a per-test
`tmp_path`. In production use they typically stay unset.

## Identity placeholders — what stays in git

`personas.yaml` (committed) carries:

```yaml
jarvis:
  owner: sir                  # opaque slug — fine to commit
  personality: |
    You are JARVIS, personal assistant to ${OWNER_DISPLAY_NAME}.
    ...
```

The real name `Alex` lives in `users.display_name` in the database, never
in committed configuration. This makes the repository safe to host in a
public fork without leaking household names.

`render_personality(persona, owner_display_name)` does the substitution at
LLM-call time. CLI commands that read configuration (such as
`config show`) do not substitute — they show the raw template, which is
the correct behaviour for inspecting what's on disk.

## Patterns we follow

- **Thin CLI, thick library** — every CLI command is a few lines that
  call into `newton.config` / `newton.db` / `newton.seed`. The same logic
  is reusable from voice, web, or MCP integrations later.
- **Stable JSON, evolving prose** — `--json` is part of the contract;
  the human output is informational only.
- **Idempotency first** — every mutating command can be safely retried.
- **Read before write** — every seeder checks existence before inserting,
  rather than relying on `INSERT OR IGNORE`. This is verbose but transparent
  in pdb.

## Future commands (not in block 1)

Reserved namespaces for upcoming blocks:

- `newton voice tts` — TTS routing, regenerate sample (block 5)

Delivered since block 1: `newton tools` / `newton providers` (block 2);
`newton vault`, `newton persona`, `newton voice biasing`, `newton memory`
(block 3); `newton proactive` (block 4).
