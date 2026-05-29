# Newton v4 — Block 1: OpenJarvis Fork + Newton Foundation ✅ COMPLETE

> Master plan: `newton-v4-master.md`
> Tech stack: `newton-v4-tech-stack.md`
> Terminology: `TERMINOLOGY.md`
> Status: **complete** — tag `v0.1.0-block1`, HEAD `71c6f93`
> Canonical post-completion record: `docs/newton/block-1-summary.md`
>
> **Goal:** Build a foundation solid enough that 10 more blocks can be
> stacked on top without flexing it. This block ships no user-facing
> behaviour — only the bedrock.

---

## 0. Block 1 — overall goals

Five concerns wired together in one block:

1. **OpenJarvis fork as the LLM substrate.** Stanford SAIL's OpenJarvis
   provides the Ollama wrapper, learning loop, and Tauri shell. Newton
   extends but never modifies it.
2. **Newton package skeleton.** A sibling Python package (`newton/`)
   that imports from OpenJarvis but lives separately.
3. **DB schema.** 13 tables defining users, personas, sessions,
   messages, ACL, gestures, emotion, registration, security, monitoring,
   patterns, notifications, screen captures, calendar — laid out
   completely upfront so later blocks just fill rows.
4. **Persona as first-class citizen.** 3 personas (Butler, JARVIS,
   Friday) seeded; `${OWNER_DISPLAY_NAME}` placeholder substitution
   at render time; real names live in DB only.
5. **CLI surface for inspection.** 7 subcommands (init, status, config,
   db, personas, users, seed) for sir to verify state at any time.

No functional behaviour ships in Block 1. The point is *substrate*. Hence
the careful step decomposition.

### Locked decisions (entering Block 1)

| Item | Decision | Source |
|------|----------|--------|
| **Base** | Fork OpenJarvis (Stanford SAIL, Apache 2.0) | master.md §0 |
| **Repo location** | `~/newton-v4/` in WSL2 Ubuntu | master.md §10 |
| **OpenJarvis modification policy** | **0 files modified.** Newton lives next to it | master.md §0 |
| **Python build tool** | uv (already OpenJarvis baseline) | OpenJarvis |
| **DB engine** | SQLite (with strict FK enforcement) | tech-stack.md §1 |
| **ORM** | SQLAlchemy 2.x sync style | tech-stack.md §1 |
| **Migrations** | Bare `.sql` files + custom runner; no Alembic | this block |
| **Persona count** | 3 (Butler, JARVIS, Friday) | master.md §1.1 |
| **User count** | 2 (sir/Alex, gf/Stella) | master.md §1.1 |
| **Real names** | DB only, never in committed config | master.md §1.4 |
| **Placeholder** | `${OWNER_DISPLAY_NAME}` substituted at render time | master.md §1.4 |
| **ChatSession naming** | `ChatSession` class (not `Session`, to avoid SQLAlchemy `Session` shadow) | this block |
| **Timestamp policy** | naive UTC `TIMESTAMP` columns until Block 4 introduces tz where needed | this block |
| **Foreign key enforcement** | `PRAGMA foreign_keys = ON` at every connection (SQLite is opt-in) | this block |
| **ON DELETE rule** | personal data → CASCADE; audit/security → SET NULL; activity-blocking → RESTRICT | this block |
| **CLI design** | thin CLI, thick library; idempotent commands; `--json` flag with stable contract | this block |

### Completion criteria (block as a whole)

```bash
# OpenJarvis baseline works
$ cd ~/newton-v4
$ uv run jarvis ask "Hello"
# response received

# Newton extension commands work
$ uv run newton init
✓ DB created at data/newton.db
✓ Applied 1 migration (001_initial.sql)
✓ Seeded 3 personas: butler, jarvis, friday
✓ Seeded 2 users: sir (Alex), gf (Stella)

$ uv run newton personas list
butler   (public, default)
jarvis   (owner: sir,   default for: sir)
friday   (owner: gf,    default for: gf)

$ uv run newton users list
sir   Alex    (default persona: jarvis)
gf    Stella  (default persona: friday)

$ uv run newton status
DB:        ✓ data/newton.db (13 tables + _migrations)
Personas:  3
Users:     2
Sessions:  0
Tests:     38 / 38 passing
Preflight: 9 / 9 ✓

# Tests
$ uv run pytest tests/newton/ -v
========== 38 passed ==========
```

After Block 1 sir cannot *do* anything with Newton beyond inspecting
its identity. That's correct — Block 1 ships the *floor*.

---

## 1. Block 1 — 8 steps

Each step: one focused change, clear completion criteria, verification
command, ends with a git commit. `ruff check` + `ruff format` clean
before commit.

Total time: **1–2 weeks at sir's pace.** Completed within estimate.

---

### Step 1.1 — OpenJarvis fork + clone + smoke test (0.5–1 day)

**Goal:** OpenJarvis runs from sir's machine. Newton branches off it.

**Outputs:**

- GitHub fork: `choiheungjoo-ai/OpenJarvis`
- WSL clone to `~/newton-v4/`
- Branch `newton-main` created and active
- `uv sync --extra dev` succeeds; `uv run jarvis ask "Hello"` returns a response
- `pre-commit install` ran
- Initial preflight script: `scripts/newton/preflight.sh` with 5–6
  basic checks (Python version, uv present, .venv exists, ollama
  reachable, jarvis CLI works)

**Verification:**

```bash
git remote -v             # origin = sir's fork
git branch                # * newton-main
uv run jarvis ask "Hello" # response received
./scripts/newton/preflight.sh
```

**Risk:** OpenJarvis upstream layout could be unstable. **Mitigation:**
pinned commit hash captured at fork time; documented.

**Commit:** `chore: OpenJarvis fork + preflight scaffold`

---

### Step 1.2 — Newton package skeleton + preflight expansion (1 day)

**Goal:** Newton's own Python package, sibling to OpenJarvis.

**Outputs:**

- `newton/__init__.py` — package init with `__version__ = "0.1.0-dev"`
- `newton/cli.py` — empty CLI dispatcher (Click or Typer)
- `newton/config.py` — empty Pydantic config loader stub
- `newton/db.py` — empty DB module stub
- `pyproject.toml` — adds `newton` to packages, declares the `newton`
  console script
- `scripts/newton/preflight.sh` — full 9 checks:
  1. Python version (3.12+)
  2. uv present
  3. `.venv/` exists
  4. Ollama service running
  5. Jarvis CLI works
  6. Newton package imports
  7. `newton --help` works
  8. `data/` writable
  9. `config/` readable
- `docs/newton/cli.md` — initial CLI command doc (placeholder for the 7 subcommands)

**Locked invariant established here:** OpenJarvis files unchanged.
Newton lives next to it. Every subsequent block honours this.

**Verification:**

```bash
uv sync                            # newton install hook runs
uv run python -c "from newton import __version__; print(__version__)"
uv run newton --help               # shows subcommand placeholders
./scripts/newton/preflight.sh      # 9/9 ✓
```

**Commit:** `feat: add newton package skeleton`

---

### Step 1.3 — personas.yaml + config loader (0.5–1 day)

**Goal:** Declarative persona definitions loaded via Pydantic.

**Outputs:**

- `config/personas.yaml` — 3 personas with `${OWNER_DISPLAY_NAME}` placeholders
- `newton/config.py` — Pydantic loader for personas
- `newton/persona.py` — `render_personality(persona, owner, partner)` function
- `tests/newton/test_config.py`

**personas.yaml shape:**

```yaml
personas:
  - persona_id: butler
    name: "Butler"
    role: "public default"
    personality: |
      You are a professional, polite butler. You serve every user with
      equal courtesy. You do not use real names.

  - persona_id: jarvis
    name: "JARVIS"
    role: "owner-bound"
    owner_user_id: sir
    personality: |
      You are JARVIS, addressing ${OWNER_DISPLAY_NAME} as "sir" or by
      first name. British butler tone. Concise. Anticipate when patterns
      are clear. Default to silence when uncertain.

  - persona_id: friday
    name: "Friday"
    role: "owner-bound"
    owner_user_id: gf
    personality: |
      You are Friday, addressing ${OWNER_DISPLAY_NAME} warmly. Casual
      tone. Pay attention to mood. Be supportive.
```

**Locked rule:** real names never in committed config. They live in
`users.display_name` (DB only). YAML uses `${OWNER_DISPLAY_NAME}`; the
config loader leaves placeholders untouched until `render_personality()`
substitutes at render time (Block 3 wires the rendering).

**Verification:**

```bash
uv run python -c "from newton.config import load_personas; print(load_personas())"
# 3 personas printed with placeholders intact

uv run pytest tests/newton/test_config.py -v
```

**Commit:** `feat: persona config loading with pydantic`

---

### Step 1.4 — DB schema (1 day)

**Goal:** Lay down all 13 tables now. Later blocks just fill rows.

**Outputs:**

- `migrations/001_initial.sql` — full schema
- `newton/db.py` — connection factory with `PRAGMA foreign_keys = ON`
- `newton/migrations.py` — migration runner with `_migrations` tracking table
- `newton/cli.py` — `newton db migrate` subcommand
- `tests/newton/test_db.py`, `test_migrations.py`

**13 application-domain tables (forward-declared so later blocks need no schema work):**

1. `users` — sir, gf
2. `personas` — Butler, JARVIS, Friday
3. `user_persona_link` — many-to-many (each user has default + accessible personas)
4. `sessions` — chat session metadata
5. `messages` — per-session message log
6. `note_acl` — ACL cache for vault notes (filled in Block 3)
7. `gestures` — registered gesture metadata (filled in Block 8)
8. `emotion_log` — facial expression log (filled in Block 6)
9. `registration_requests` — guest registration approval queue
10. `guest_activity` — guest action log (filled Block 3+)
11. `auth_attempts` — security log (filled Block 5)
12. `system_metrics` — monitoring samples (Block 4 fills)
13. `user_patterns` — learned behaviour patterns (Block 4 fills)

Plus three forward-declared tables for Block 4 / 6 / 9 that ship in
this schema (so Block 4+ don't need schema changes): `proactive_notifications`,
`screen_captures`, `calendar_events`. Plus the `_migrations` runner table.

The "13 tables" count in `block-1-summary.md` refers to the
application-domain tables above.

**ON DELETE policy locked here:**

```sql
-- Personal data → CASCADE
sessions(user_id) → users           ON DELETE CASCADE
messages(session_id) → sessions     ON DELETE CASCADE

-- Audit / security → SET NULL (preserve the audit row)
auth_attempts(user_id) → users      ON DELETE SET NULL
registration_requests(user_id) → users ON DELETE SET NULL

-- Activity-blocking → RESTRICT (refuse delete if used)
sessions(persona_id) → personas     ON DELETE RESTRICT
```

This three-bucket rule applies to every block's new tables.

**FK enforcement at every connection** (SQLite quirk: FKs are opt-in
per connection). `newton/db.py` runs `PRAGMA foreign_keys = ON` on
every connection acquire.

**Verification:**

```bash
uv run newton db migrate
sqlite3 data/newton.db ".tables"
# application tables + _migrations listed

sqlite3 data/newton.db "PRAGMA foreign_keys"
# 1 (enabled per connection)

uv run pytest tests/newton/test_db.py tests/newton/test_migrations.py -v
```

**Commit:** `feat: SQL schema with multi-tenant persona model`

---

### Step 1.5 — SQLAlchemy ORM models (1 day)

**Goal:** Python representation of every table.

**Outputs:**

- `newton/models/__init__.py`
- `newton/models/user.py`, `persona.py`, `session.py`, `message.py`,
  `acl.py`, `gesture.py`, `emotion.py`, `auth.py`, `monitoring.py`,
  `patterns.py`, `calendar.py`
- Sync SQLAlchemy 2.x style with type annotations
- `tests/newton/test_models.py`

**Class naming convention locked:**

- `User`, `Persona`, `Message`, `Gesture`, etc. — straightforward
- **`ChatSession`** instead of `Session` — avoids shadowing
  `sqlalchemy.orm.Session`. Important rule honoured throughout the codebase.

**Verification:**

```bash
uv run python -c "from newton.models import User, ChatSession, Persona; print('ok')"

uv run pytest tests/newton/test_models.py -v
```

**Commit:** `feat: SQLAlchemy ORM models for all 13 tables`

---

### Step 1.6 — Seed (0.5–1 day)

**Goal:** Insert 3 personas + 2 users into the fresh DB. Idempotent.

**Outputs:**

- `newton/seed.py` — loads personas.yaml, inserts personas, prompts for
  user display names
- `newton/cli.py` — `newton init` (runs migrate + seed)
- `tests/newton/test_seed.py`

**Seed shape:**

```python
def seed_personas(session):
    """Idempotent. Re-running adds nothing."""
    for persona_config in load_personas():
        existing = session.get(Persona, persona_config.persona_id)
        if existing:
            continue                  # idempotent
        session.add(Persona(...))
    session.commit()

def seed_users(session, *, sir_display_name="Alex", gf_display_name="Stella"):
    """Same idempotence rule. Real names accepted as arguments
    (CLI prompts for them); never hard-coded."""
    ...
```

**Seeding order:** personas first (no FK deps), then users (link by
default_persona_id).

**Verification:**

```bash
uv run newton init                          # first run
# ✓ Seeded 3 personas, 2 users

uv run newton init                          # second run (idempotent)
# ✓ DB already initialized

uv run newton personas list
# butler / jarvis / friday

uv run newton users list
# sir Alex / gf Stella

uv run pytest tests/newton/test_seed.py -v
```

**Commit:** `feat: persona + user seeding (Alex/Stella) with CLI`

---

### Step 1.7 — `newton status` + CLI documentation (1 day)

**Goal:** Single command that shows everything at a glance. Final pass
on `docs/newton/cli.md`.

**Outputs:**

- `newton/cli.py` — finishes all 7 subcommands:
  - `newton init` — migrate + seed
  - `newton status` — unified snapshot (with `--json` for stable contract)
  - `newton config show` — current config dump
  - `newton db migrate / status` — migration status
  - `newton personas list / show`
  - `newton users list / show`
  - `newton seed` — explicit re-seed (idempotent)
- `docs/newton/cli.md` — full command reference
- `tests/newton/test_cli.py`

**`newton status` design (rich-formatted by default, `--json` for scripts):**

```
$ uv run newton status

Newton v4.0.1
=============
DB:        ✓ data/newton.db (13 tables + _migrations)
Personas:  3 (butler, jarvis, friday)
Users:     2 (sir, gf)
Sessions:  0
Messages:  0
Tests:     38 / 38 passing
Preflight: 9 / 9 ✓

$ uv run newton status --json
{
  "db_ok": true,
  "tables": 13,
  "personas": 3,
  "users": 2,
  "sessions": 0,
  "messages": 0,
  "tests_passing": 38,
  "tests_total": 38,
  "preflight_ok": true
}
```

**Locked rule:** `--json` is the stable contract; prose output is
informational and may change. Scripts depend on JSON, sir reads prose.

**Verification:**

```bash
uv run newton status
uv run newton status --json | jq .

uv run pytest tests/newton/test_cli.py -v
```

**Commit:** `feat: 'newton status' command + CLI docs`

---

### Step 1.8 — Block 1 summary + tag (1–2 hours)

**Goal:** Lock the block. Define Block 2 entry conditions.

**Outputs:**

- `docs/newton/block-1-summary.md` — *the* canonical record of what
  shipped
- `README.md` — Block 1 marked complete
- Git tag: `v0.1.0-block1`

**Block 2 entry conditions (defined here, honoured by Block 2):**

- `git status` clean, on `newton-main`, HEAD at `v0.1.0-block1`
- `uv run newton status` reports green
- `uv run pytest tests/newton/ -v` → 38 passed
- `./scripts/newton/preflight.sh` → 9/9 ✓
- DB has 13 tables + `_migrations`
- 3 personas + 2 users seeded
- OpenJarvis: 0 files modified (verified via `git log` on OpenJarvis upstream commits)

**Commit + tag:** `docs: block 1 summary — identity & data foundation`

---

## 2. Deliberately not in Block 1

These belong to later blocks and were explicitly held out:

- ❌ **Tool calling** — Block 2
- ❌ **Approval hook** — Block 2
- ❌ **Provider registry** — Block 2
- ❌ **Vault parser** — Block 3
- ❌ **RAG / Qdrant / embeddings** — Block 3
- ❌ **Persona engine routing logic** — Block 3 (Block 1 just stores personas)
- ❌ **Proactive monitoring** — Block 4
- ❌ **Voice in / out** — Block 5
- ❌ **Vision** — Block 6
- ❌ **Anything functional** — Block 1 is *only* the substrate

The discipline of "no functional behaviour in Block 1" protects every
subsequent block from foundation rework.

---

## 3. Risk matrix

| Risk | Impact | Mitigation |
|------|--------|-----------|
| OpenJarvis upstream changes break the fork | Med | Pinned commit hash at fork; merge upstream as discrete steps later |
| SQLite FK enforcement forgotten on a connection | High | `db.py` factory pattern enforces; tests verify `PRAGMA foreign_keys=1` |
| ORM `Session` name collision with SQLAlchemy | Med | Locked: use `ChatSession`. Searchable codebase rule. |
| Migration mid-run failure leaves DB inconsistent | Med | Each migration in a single SQL file; transactional; `_migrations` row only inserted on success |
| Seed run twice → duplicate rows | Med | Idempotent design: check before insert |
| Real names accidentally committed to YAML | High | YAML has only placeholders; pre-commit hook greps for known names; sir reviewed at every commit |
| 13-table schema turns out wrong at Block 3+ | Med | Forward-declared; if change needed, migration `002_*.sql` added; no rewrite |
| Forgetting `--json` stable contract breaks scripts | Low | Documented; integration tests assert JSON keys present |
| 1-2 week estimate optimistic | Low | Was accurate; completed within estimate |

---

## 4. After Block 1 — opening message for the next chat

This is the template that launched Block 2:

```markdown
# Newton v4 — Block 2 start (Tool Calling + Approval Hook + Provider Registry)

## Context
- Newton: multi-persona AI OS, OpenJarvis fork
- Environment: RTX 5090 + WSL2 Ubuntu + systemd
- Location: ~/newton-v4/

## Design docs
[newton-v4-master.md]
[newton-v4-tech-stack.md]
[newton-v4-engines.md]
[newton-v4-block-1.md]    # complete (this file)
[newton-v4-block-2.md]    # next
[TERMINOLOGY.md]

## Block 1 result
- v0.1.0-block1: OpenJarvis fork + Newton foundation
  - 13 tables + _migrations
  - 3 personas + 2 users seeded
  - 7 CLI subcommands
  - 38 pytest cases passing
  - Preflight 9/9
  - OpenJarvis: 0 files modified

## Next
Block 2 step 2.1 — OpenJarvis boundary + Newton tool layer design.
```

---

## 5. Honest reality check

**Time estimate:** **1–2 weeks at sir's pace.** Completed within estimate.

**Riskiest steps:**

- **Step 1.4** (schema) — wrong design here would haunt every later block
- **Step 1.5** (ORM) — naming and class structure decisions ripple forward

**Simplest steps:**

- 1.1, 1.6, 1.7, 1.8 — straightforward

**Most important step:**

- **Step 1.4** (DB schema). Every subsequent block fills tables; if
  the schema is wrong, blocks 2–11 all pay the cost. Worth the
  forward-declaration effort.

**Behavioural shift after Block 1:**

Nothing visible to sir. Newton exists as a name, a database, a set of
CLI commands that report state. The point is that *Block 2 onwards
has somewhere stable to build*.

**Assets established by Block 1, used by every later block:**

- `~/newton-v4/` layout convention
- `newton/` package coexisting with OpenJarvis
- 13 tables already there for later blocks to populate
- `PRAGMA foreign_keys=1` discipline
- `ChatSession` class naming
- ON DELETE rule (CASCADE / SET NULL / RESTRICT, three buckets)
- Idempotent CLI commands
- `--json` stable contract
- Thin CLI, thick library
- OpenJarvis: 0 files modified invariant
- Display names in DB only

---

## 6. Starting checklist

The conditions sir confirmed before starting Block 1:

- [x] WSL2 Ubuntu running
- [x] Python 3.12 available
- [x] uv installed
- [x] Ollama installed and serving
- [x] Disk space ≥ 100 GB free (models accumulate)
- [x] Git configured (user.name, user.email, SSH key)
- [x] GitHub account ready (for the fork)
- [x] sir comfortable with terminal-only operation
- [x] At least 1-2 weeks of focused work available
- [x] master.md + tech-stack.md + TERMINOLOGY.md in `~/newton-v4/docs/newton/design/`

---

Block 1 is complete. This document is preserved for history and for the
pattern it established. Subsequent block plans (block-2.md, block-3.md, ...)
follow the same structure: §0 goals + locked decisions + completion
criteria, §1 N steps with one focused change each, §2 deliberately
not in this block, §3 risk matrix, §4 after-block opening message,
§5 honest reality check, §6 starting checklist.

For operational status today, see `docs/newton/block-1-summary.md`.

Good work, sir.
