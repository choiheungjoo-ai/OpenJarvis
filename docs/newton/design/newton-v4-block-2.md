# Newton v4 — Block 2: Tool Calling + Approval Hook + Provider Registry

> Master plan: `newton-v4-master.md`
> Tech stack: `newton-v4-tech-stack.md`
> Engines (provider patterns): `newton-v4-engines.md`
> Terminology: `TERMINOLOGY.md`
> Prerequisite: Block 1 complete (`v0.1.0-block1`, `docs/newton/block-1-summary.md`)
>
> **Goal:** Build the layer that lets Newton safely mediate between an LLM
> and external tools. Every capability added in blocks 3+ rides on this layer.

---

## 0. Block 2 — overall goals

Three concerns wired together in one block:

1. **Tool calling infrastructure.** Newton's own layer for defining,
   registering, and dispatching tools. OpenJarvis is used as an LLM
   runtime (Ollama wrapper) only — Newton never modifies OpenJarvis files,
   per Block 1's locked principle.
2. **Approval hook.** The decision-and-logging circuit that decides what
   happens with a tool call: auto-allow, prompt sir, or deny. The vault
   itself arrives in Block 3, so Block 2 ships *interface + decision
   logging + dry-run* — actual vault writes wire in during Block 3.
3. **Provider registry.** Per-capability registry that holds multiple
   competing providers with one active default and runtime hot-swap.
   Block 2 ships the abstraction plus two dummy providers; real providers
   (SearXNG, Gmail, ...) land in blocks 6 / 7 / 9.

### Locked decisions (entering Block 2)

| Item | Decision | Source |
|------|----------|--------|
| **Tool-calling direction** | Newton owns its own layer | Block 1 "OpenJarvis 0 lines touched" |
| **OpenJarvis usage** | Import its Ollama wrapper if useful; never modify | Same |
| **Provider registry scope** | Included in Block 2 (abstraction + dummies) | master.md §7 |
| **Approval hook write target** | Block 2 logs decisions only; vault writes happen in Block 3 | Vault doesn't exist yet |
| **Tool representation** | ABC + Pydantic BaseModel (final shape confirmed in Step 2.1) | Investigation-first |
| **Risk classification** | 5 levels (0..4), explicitly revisited in Step 2.1 after OpenJarvis investigation | sir decision |
| **Approval channel** | Full ABC abstraction now — `ApprovalChannel` + `CLIApprovalChannel` ship in Block 2; voice / push channels added in later blocks without touching Block 2 code | sir decision |
| **Provider registry + hot-swap** | One merged step (2.7), not two. default-then-override pattern. | sir decision |
| **`tool_policies` UNIQUE** | Use sentinel `'*'` instead of NULL, because SQLite treats NULL ≠ NULL in UNIQUE constraints | sir decision |
| **`tool_approvals` FK on delete** | Both `persona_id` and `user_id` use `SET NULL` — consistent with Block 1's audit-log rule | sir decision |

### Completion criteria (block as a whole)

```bash
# New commands all work
$ uv run newton tools list
echo            (risk: 0 / SAFE)
system_info     (risk: 1 / READ_LOCAL)
echo_to_file    (risk: 2 / WRITE_LOCAL)

$ uv run newton tools show echo
Name:           echo
Risk:           0 (SAFE)
Args schema:    { "text": "string" }
Returns schema: { "text": "string" }
Default policy: auto_allow

# Risk 0..1 auto-allow
$ uv run newton tools run echo --args '{"text":"hi"}' --user sir --persona jarvis
[policy] echo (risk: 0 / SAFE) -> auto_allow
{"text": "hi"}

# Risk 2 triggers the approval hook naturally
$ uv run newton tools run echo_to_file --args '{"text":"x","path":"/tmp/newton-echo.txt"}' --user sir --persona jarvis --dry-run
[hook] echo_to_file (risk: 2 / WRITE_LOCAL) requires approval (dry-run)
ToolResult(status=needs_approval, metadata={preview: {...}})

# Provider registry + hot-swap
$ uv run newton providers list
capability=demo.echo
  * active   echo_loud      (free)
            echo_quiet     (free)

$ uv run newton providers swap demo.echo echo_quiet
swapped. active=echo_quiet (capability=demo.echo)

$ uv run newton providers swap demo.echo echo_loud --once
swapped (scope=once). next call only.

# Tests
$ uv run pytest tests/newton/ -v
# Block 1: 38 passed + Block 2: ~55 added = ~93 passed
```

Functional behaviour is still limited — only dummy tools and dummy
providers ship. Real web search, real email, etc. arrive in blocks 6 / 7 / 9.
Block 2 ships the **circuit**.

---

## 1. Block 2 — 9 steps

Each step:

- One focused change
- Clear completion criteria + verification command
- Ends with one git commit
- `ruff check` + `ruff format` clean before commit

Step 2.7 in v1 (Provider abstraction) and Step 2.8 (Hot-swap) are merged
into a single Step 2.7'. Total: 9 steps.

---

### Step 2.1 — OpenJarvis boundary + Newton tool layer design (half-day to 1 day)

**Goal:** Write down what "Newton's own layer" actually looks like, on
paper. No code. Just a decision memo.

If OpenJarvis already has a Pydantic-based tool schema, Newton may
**import** it (Newton never modifies OpenJarvis — but it can use it).
The investigation makes that explicit.

**Investigation items:**

1. Does OpenJarvis have tool / function-calling code? Where?
2. How does OpenJarvis wire tool calls through its LLM adapter (Ollama)?
3. What dependencies does OpenJarvis bring in (pydantic v1 vs v2,
   jsonschema, instructor, ...)?
4. Can Newton register tools into OpenJarvis's registry, or should it
   keep a separate registry and dispatch itself?
5. **Risk classification re-check.** With real OpenJarvis tools in view,
   are 5 levels (0..4) appropriate, or should it collapse to 4 or 3?

**Output:**

- `docs/newton/block-2-investigation.md` — investigation findings +
  final decision memo
- Example decision summary:
  ```
  - Tool representation: Pydantic v2 BaseModel for args + returns schemas
  - Tool base class: ABC `newton.tools.base.Tool`
  - Result wrapper: `newton.tools.base.ToolResult`
  - Risk levels: 5 retained (0..4) — OpenJarvis tools span all 5
  - Dispatch: Newton ToolRegistry (separate from OpenJarvis's, if any)
  - LLM calls: import OpenJarvis Ollama wrapper (do not modify)
  ```

**Verification:**

- ✅ `docs/newton/block-2-investigation.md` exists
- ✅ Subsequent steps can reference it as ground truth

**Risk:**

- OpenJarvis code base may be large → easy to spend days in there.
  **Hard cap: 1 day.** If the cap is hit, mark "investigation in progress"
  and proceed to 2.2 with current best understanding.

**Commit:** `docs(block-2): tool layer design decision`

---

### Step 2.2 — Tool abstraction: base class + ToolResult + risk levels (half-day)

**Goal:** Lock the interface every tool follows.

**Outputs:**

- `newton/tools/__init__.py`
- `newton/tools/base.py`
  - `class Tool(ABC)` — abstract base
  - `class ToolResult(BaseModel)` — result wrapper
  - `class RiskLevel(IntEnum)` — 0..4
- `tests/newton/tools/test_base.py`

**Provisional shapes (refined in 2.1):**

```python
from abc import ABC, abstractmethod
from enum import IntEnum
from typing import Literal
from pydantic import BaseModel

class RiskLevel(IntEnum):
    SAFE          = 0  # echo, math
    READ_LOCAL    = 1  # system_info, file_read
    WRITE_LOCAL   = 2  # file_write, vault_write
    READ_NETWORK  = 3  # web_search, http_get
    WRITE_NETWORK = 4  # email_send, kakao_send

class ToolResult(BaseModel):
    status: Literal["ok", "error", "needs_approval", "denied"]
    data: dict | None = None
    error: str | None = None
    metadata: dict = {}

class Tool(ABC):
    name: str
    description: str
    risk: RiskLevel
    args_schema: type[BaseModel]
    returns_schema: type[BaseModel]

    @abstractmethod
    async def execute(self, args: BaseModel, context: "ToolContext") -> ToolResult: ...

    def args_model(self, raw: dict) -> BaseModel:
        return self.args_schema(**raw)
```

`ToolContext` is a small dataclass holding `user_id`, `persona_id`,
`session_id`, `dry_run`, `auto_approve` flags.

**Verification:**

```bash
uv run pytest tests/newton/tools/test_base.py -v
# Tool / ToolResult / RiskLevel import, instantiate, serialize
```

**Risk:** Pydantic v1 vs v2. OpenJarvis version dictates — confirmed in 2.1.

**Commit:** `feat(tools): base abstractions for tool calling`

---

### Step 2.3 — ToolRegistry: register / lookup / dispatch (half-day)

**Goal:** Find tools by name and run them.

**Outputs:**

- `newton/tools/registry.py`
  - `class ToolRegistry` — singleton or explicit instance
  - `register(tool)`, `get(name)`, `list()`, `dispatch(name, args, context)`
- `tests/newton/tools/test_registry.py`

**Key behaviours:**

- `dispatch()` validates args → consults policy (wired in 2.5–2.6) → executes → returns `ToolResult`
- Duplicate registration raises `ToolError`
- `list()` is sorted by risk level

**Verification:**

```bash
uv run pytest tests/newton/tools/test_registry.py -v
# register / get / list / dispatch, duplicate-error, unknown-name-error
```

**Commit:** `feat(tools): tool registry with dispatch`

---

### Step 2.4 — Three dummy tools: echo, system_info, echo_to_file (half-day + 1 hour)

**Goal:** Validate tool abstraction against real implementations and
give Step 2.6 a natural risk-2 case to exercise the approval hook.

**Outputs:**

- `newton/tools/builtin/__init__.py`
- `newton/tools/builtin/echo.py` — risk 0, `{text}` → `{text}`
- `newton/tools/builtin/system_info.py` — risk 1, `{}` → CPU/memory/disk via psutil
- `newton/tools/builtin/echo_to_file.py` — risk 2, `{text, path}` → writes text to a `/tmp/`-scoped file, returns `{path, bytes_written}`
- `tests/newton/tools/test_builtin.py`

**Why `echo_to_file`:**

A real WRITE_LOCAL example. The path argument is locked to `/tmp/`
(safety) but the operation is technically a disk write, so risk = 2.
This gives Step 2.6 a real approval-hook trigger without inventing
fake danger via policy override.

**Dependency:**

```bash
uv add psutil
```

**Verification:**

```bash
uv run pytest tests/newton/tools/test_builtin.py -v
# echo("hi")        -> ToolResult(status=ok, data={"text": "hi"})
# system_info()     -> ToolResult(status=ok, data={"cpu_count": int, ...})
# echo_to_file(...) -> ToolResult(status=ok, data={"path": "/tmp/...", "bytes_written": N})
# echo_to_file with path outside /tmp/ -> ToolResult(status=error)
```

**Commit:** `feat(tools): echo, system_info, echo_to_file builtin tools`

---

### Step 2.5 — Approval policy matrix (1 day)

**Goal:** The table that decides: which tool, when called by whom, in
which persona, needs approval?

**Outputs:**

- `migrations/002_tool_policies.sql`
- `newton/tools/policy.py` — policy lookup + evaluation
- `newton/models/tool_policy.py` — ORM model
- `tests/newton/tools/test_policy.py`

**Schema:**

```sql
CREATE TABLE tool_policies (
    policy_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name     TEXT NOT NULL,
    persona_id    TEXT NOT NULL DEFAULT '*',   -- '*' means: applies to all personas
    user_id       TEXT NOT NULL DEFAULT '*',   -- '*' means: applies to all users
    decision      TEXT NOT NULL,               -- 'auto_allow' / 'require_approval' / 'always_deny'
    rationale     TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tool_name, persona_id, user_id)
);
```

**Sentinel `'*'` rationale:**

SQLite treats NULL ≠ NULL in `UNIQUE` constraints, which would silently
permit duplicate `(echo, NULL, NULL)` rows. Using the literal `'*'` as
the "all" wildcard makes the constraint behave correctly and the SQL
self-explanatory.

**Lookup priority (most specific first):**

```
1. (tool_name, persona_id, user_id)    — exact triple
2. (tool_name, persona_id, '*')         — persona scope
3. (tool_name, '*', user_id)            — user scope
4. (tool_name, '*', '*')                — tool default
5. fallback by risk level (no row found)
```

**Default seed (in `newton.seed`):**

- risk 0..1 → `auto_allow` at `('*', '*')`
- risk 2..3 → `require_approval` at `('*', '*')`
- risk 4    → `require_approval` at `('*', '*')` (per-persona whitelist allowed later)

**Verification:**

- Migration applies; `_migrations.version = 2`
- Seed populates default policies for echo / system_info / echo_to_file
- Priority test: specific override beats general
- FK cascade works (delete a user → that user's policy rows go)

**Commit:** `feat(tools): approval policy matrix with migration 002`

---

### Step 2.6 — Approval hook: ApprovalChannel ABC + decision log + dry-run (1 day + half-day for abstraction)

**Goal:** Wire policy into dispatch. When approval is required, ask sir
through a pluggable channel. Log every decision.

**Outputs:**

- `migrations/003_approval_log.sql`
- `newton/tools/approval.py`
  - `class ApprovalChannel(ABC)` — pluggable channel interface
  - `class CLIApprovalChannel(ApprovalChannel)` — Block 2 implementation
  - `class ApprovalRequest` — what to ask
  - `class ApprovalDecision` — what came back
  - hook entrypoint used by `ToolRegistry.dispatch`
- `newton/tools/registry.py` — dispatch wired through the hook
- `tests/newton/tools/test_approval.py`

**Schema:**

```sql
CREATE TABLE tool_approvals (
    approval_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name     TEXT NOT NULL,
    persona_id    TEXT,                          -- nullable: SET NULL on persona delete
    user_id       TEXT,                          -- nullable: SET NULL on user delete
    args_json     TEXT,
    risk          INTEGER NOT NULL,
    decision      TEXT NOT NULL,                 -- 'allowed' / 'denied' / 'dry_run'
    decided_by    TEXT,                          -- 'policy' (auto) / user_id (sir's prompt response)
    channel       TEXT,                          -- 'cli' / 'voice' / ... (records which channel asked)
    decided_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (persona_id) REFERENCES personas(persona_id) ON DELETE SET NULL,
    FOREIGN KEY (user_id)    REFERENCES users(user_id)    ON DELETE SET NULL
);
```

**FK SET NULL rationale:**

`tool_approvals` is an audit log. Block 1's locked rule (in
`block-1-summary.md`): audit / security records use `SET NULL` to
preserve the trail while dropping the personal pointer. `tool_approvals`
fits that category exactly.

**ApprovalChannel ABC (the abstraction sir asked for):**

```python
class ApprovalRequest(BaseModel):
    tool_name: str
    risk: RiskLevel
    args_summary: dict
    persona_id: str
    user_id: str
    rationale: str | None = None

class ApprovalDecision(BaseModel):
    allowed: bool
    decided_by: str       # 'sir', 'gf', 'policy', ...
    note: str | None = None

class ApprovalChannel(ABC):
    name: ClassVar[str]   # 'cli', 'voice', 'push', ...

    @abstractmethod
    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision: ...

class CLIApprovalChannel(ApprovalChannel):
    name = "cli"

    async def request_approval(self, request):
        print(f"\n[approval] {request.tool_name} (risk: {request.risk.name})")
        print(f"  persona: {request.persona_id}   user: {request.user_id}")
        print(f"  args:    {request.args_summary}")
        ans = input("Approve? [y/N]: ").strip().lower()
        return ApprovalDecision(
            allowed=(ans == "y"),
            decided_by=request.user_id,
        )
```

Block 5 adds `VoiceApprovalChannel`; Block 9 adds `PushApprovalChannel`.
Neither touches Block 2 code.

**Hook flow:**

```
dispatch(tool_name, args, context)
  → policy = lookup(tool, persona, user)
  → policy == auto_allow:
        execute + log(decision=allowed, decided_by='policy', channel=None)
  → policy == always_deny:
        ToolResult(denied) + log(decision=denied, decided_by='policy', channel=None)
  → policy == require_approval:
        if context.dry_run:
            ToolResult(needs_approval, metadata={preview: ...})
            log(decision=dry_run, decided_by='policy', channel=None)
        else:
            channel = ApprovalChannel.active()             # CLIApprovalChannel in Block 2
            decision = await channel.request_approval(...)
            if decision.allowed:
                execute + log(decision=allowed, decided_by=user_id, channel='cli')
            else:
                ToolResult(denied) + log(decision=denied, decided_by=user_id, channel='cli')
```

**Important:**

- Block 2 logs the decision — **no vault write yet.** Vault wiring is
  Block 3.
- `auto_approve` flag in `ToolContext` short-circuits prompts in tests
  so pytest never blocks on stdin.

**Verification:**

`echo` (risk 0) and `system_info` (risk 1) are both `auto_allow` by
default, so the natural approval-hook trigger is `echo_to_file`
(risk 2). The four verification cases below all use real defaults — no
policy override needed for the basic flow.

```bash
# 1. risk 0 (echo) — default auto_allow → execute, log decided_by='policy'
uv run newton tools run echo --args '{"text":"hi"}' --user sir --persona jarvis

# 2. risk 2 (echo_to_file) — default require_approval → dry-run preview
uv run newton tools run echo_to_file --args '{"text":"x","path":"/tmp/newton-echo.txt"}' \
    --user sir --persona jarvis --dry-run
# ToolResult(status=needs_approval, metadata.preview=...) + log decision=dry_run

# 3. risk 2 with --auto-yes — execute + log decided_by=sir
uv run newton tools run echo_to_file --args '{"text":"x","path":"/tmp/newton-echo.txt"}' \
    --user sir --persona jarvis --auto-yes

# 4. policy override → always_deny → denied
uv run newton tools policy set echo_to_file --user sir --decision always_deny
uv run newton tools run echo_to_file --args '{"text":"x","path":"/tmp/newton-echo.txt"}' \
    --user sir --persona jarvis
# ToolResult(status=denied)

# clean up
uv run newton tools policy unset echo_to_file --user sir

uv run pytest tests/newton/tools/test_approval.py -v
```

**Risk:**

- CLI prompt blocks pytest if reached → `auto_approve` in `ToolContext`
  guarantees tests never reach `input()`.
- Concurrency (two prompts at once) → Block 2 is serial. Async locking
  arrives with the voice channel in Block 5.

**Commit:** `feat(tools): approval hook with channel abstraction and decision logging`

---

### Step 2.7' — Provider Registry + Hot-swap (merged) (1.5 days)

**Goal:** Register multiple providers per capability, with one active
default chosen automatically and a runtime override mechanism for sir.

This is the merge of v1's Step 2.7 (registry) and Step 2.8 (hot-swap).
sir's framing: *"Default to the most-optimised provider Newton has
learned about; let me hot-swap when I want."*

**Outputs:**

- `newton/providers/__init__.py`
- `newton/providers/base.py`
  - `class Provider(ABC)` — `name`, `capability`, `cost_model`, `free_quota`, `execute`, `health_check`
- `newton/providers/registry.py`
  - `register(provider)`, `get_active(capability)`, `list_providers(capability)`
  - `swap(capability, name, scope: 'once' | 'session' | 'permanent')`
  - `peek_one_shot()` — internal, consumes a `once` swap
- `newton/providers/builtin/echo_loud.py` — dummy for capability `demo.echo`
- `newton/providers/builtin/echo_quiet.py` — second dummy for same capability
- `migrations/004_providers.sql`
- `newton/models/provider.py`
- `tests/newton/providers/test_base.py`
- `tests/newton/providers/test_registry.py`
- `tests/newton/providers/test_swap.py`

**Schema:**

```sql
CREATE TABLE provider_state (
    capability       TEXT PRIMARY KEY,           -- 'web.search', 'demo.echo', ...
    active_provider  TEXT NOT NULL,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE provider_usage (
    usage_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    capability       TEXT NOT NULL,
    provider_name    TEXT NOT NULL,
    units_used       INTEGER DEFAULT 1,
    used_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Provider base (provisional):**

```python
from typing import ClassVar

class Provider(ABC):
    name:        ClassVar[str]
    capability:  ClassVar[str]                     # 'web.search', 'demo.echo'
    cost_model:  ClassVar[str]                     # 'free', 'free_tier', 'paid'
    free_quota:  ClassVar[int | None] = None

    @abstractmethod
    async def execute(self, request: BaseModel) -> BaseModel: ...

    async def health_check(self) -> bool:
        return True
```

**Default selection on startup:**

1. Group registered providers by capability.
2. For each capability, if `provider_state` has a row, use it.
3. Otherwise pick the lowest-cost healthy provider (`cost_model` priority:
   free > free_tier > paid), record it as active.

**Hot-swap scopes:**

```
once       — applies to the next get_active(capability) only;
              auto-reverts after the next call
session    — applies for this process lifetime (in-memory only)
permanent  — written to provider_state; survives restart
```

**Verification:**

```bash
uv run pytest tests/newton/providers/ -v

uv run newton providers list
# capability=demo.echo
#   * active   echo_loud    (free)
#              echo_quiet   (free)

uv run newton providers swap demo.echo echo_quiet --once
uv run newton providers active demo.echo   # echo_quiet (once)
uv run newton providers active demo.echo   # echo_loud (reverted)

uv run newton providers swap demo.echo echo_quiet --permanent
# simulated restart (new ProviderRegistry instance) → still echo_quiet
```

**Commit:** `feat(providers): provider registry with default selection and hot-swap`

---

### Step 2.8 — CLI surface: `newton tools` + `newton providers` (1 day)

**Goal:** Expose every new capability through the operator CLI. (This is
v1's Step 2.9, renumbered after the 2.7+2.8 merge.)

**Outputs:**

- `newton/cli.py` — extended
- New subcommands:
  - `newton tools list [--json]`
  - `newton tools show <name> [--json]`
  - `newton tools run <name> --args <json> [--user <id>] [--persona <id>] [--dry-run] [--auto-yes]`
  - `newton tools policy list [--json]`
  - `newton tools policy set <tool> [--persona X] [--user Y] --decision <auto_allow|require_approval|always_deny>`
  - `newton tools policy unset <tool> [--persona X] [--user Y]`
  - `newton providers list [--json]`
  - `newton providers show <capability> [--json]`
  - `newton providers swap <capability> <provider> [--once|--session|--permanent]`
  - `newton providers active <capability>`
  - `newton providers usage [--json]`
- `newton status` extended — counts of tools / providers added to the snapshot
- `docs/newton/cli.md` updated — every new command documented with example
- `tests/newton/cli/test_tools_cli.py`, `test_providers_cli.py`

**Verification:**

```bash
uv run newton --help                    # tools, providers subcommands visible
uv run newton tools list --json         # parseable, 3 tools
uv run newton providers list --json     # parseable, demo.echo capability
uv run pytest tests/newton/cli/ -v
```

**Commit:** `feat(cli): tools and providers subcommands`

---

### Step 2.9 — Block 2 summary + tag (1–2 hours)

**Goal:** Capture the state of Block 2 and lay entry conditions for Block 3.
(This is v1's Step 2.10.)

**Outputs:**

- `docs/newton/block-2-summary.md` — same tone as `block-1-summary.md`
  - Completion-criteria checklist with checkmarks
  - Locked design decisions list (this document's §0 decisions, confirmed)
  - Entry conditions for Block 3
- `docs/newton/cli.md` — **final pass:** confirm every Block 2 command
  is documented, examples match actual output, `--json` shapes match.
  (Block 1 already shipped cli.md; this step is the audit.)
- `README.md` updated — Block 2 marked complete
- `pyproject.toml` lockfile tidied
- Git tag: `v0.2.0-block2`

**Block 3 entry conditions (provisional):**

- `newton tools list` shows echo, system_info, echo_to_file
- `newton tools run <name>` works end-to-end
- `newton providers list` works
- Tables present: `tool_policies`, `tool_approvals`, `provider_state`, `provider_usage`
- All pytest cases pass (~93 total)
- `./scripts/newton/preflight.sh` 9/9 ✓
- OpenJarvis: still 0 lines modified

**Verification:**

```bash
git log --oneline | head -15
git tag -l | grep block2

uv run newton status      # tool/provider counts reflected
```

**Commit + tag:** `chore: block 2 complete`

---

## 2. Deliberately not in Block 2

- ❌ **Vault writes** — Block 3 (hook logs decisions only)
- ❌ **Real web_search / Gmail / SearXNG providers** — Blocks 6 / 7 / 9
- ❌ **Persona RAG / long-term memory** — Block 3
- ❌ **Voice approval channel** — Block 5 (ABC is in place, implementation deferred)
- ❌ **Guest quarantine + JARVIS briefing** — Block 3 wiring
- ❌ **Provider cost monitoring alerts** — Block 4 (Proactive)
- ❌ **Concurrent approval prompts** — Block 5 (Block 2 is serial)

Principle: *add when needed, not before.*

---

## 3. Risk matrix

| Risk | Impact | Mitigation |
|------|--------|-----------|
| OpenJarvis has a conflicting tool abstraction; just importing breaks Newton | Med | Confirm in Step 2.1. If conflict → full separation (no import) |
| Pydantic v1 vs v2 mismatch | Med | Follow OpenJarvis's version; Newton stays aligned |
| CLI prompt blocks pytest | Low | `auto_approve` flag in `ToolContext`, tests always set it |
| 5-level risk classification doesn't match real OpenJarvis tools | Med | Step 2.1 reviews and collapses to 4 / 3 if appropriate |
| ApprovalChannel ABC over-specified before voice arrives | Low | Block 2 ships one concrete (CLI). ABC kept minimal — refine when Block 5 has real requirements |
| Provider registry DB-backed turns out to be overkill | Low | Easy to simplify schema in Step 2.7'; tests cover both code paths |
| 9 steps still too granular and momentum stalls | Low | sir already merged 2.7+2.8; further merging discouraged |
| 8–12 day estimate is itself wrong | Med | Re-estimate after Step 2.3; communicate adjustments openly |

---

## 4. After Block 2 — opening message for the next chat

```markdown
# Newton v4 — Block 3 start (Persona + Vault + ACL + RAG + long-term memory)

## Context
- Newton: multi-persona AI OS, OpenJarvis fork
- Environment: RTX 5090 + WSL2 Ubuntu + systemd
- Location: ~/newton-v4/

## Design docs (all English from this point)
[newton-v4-master.md]
[newton-v4-tech-stack.md]
[newton-v4-engines.md]
[newton-v4-voice.md]      # vault → biasing auto-strengthening (block 3 tail)
[newton-v4-block-2.md]    # complete
[newton-v4-block-3.md]    # this block
[TERMINOLOGY.md]

## Blocks 1+2 result
- v0.1.0-block1: identity & data foundation (13 tables)
- v0.2.0-block2: tool calling + approval hook + provider registry
  - 3 builtin tools (echo, system_info, echo_to_file)
  - 2 dummy providers (echo_loud, echo_quiet, capability=demo.echo)
  - ApprovalChannel ABC + CLIApprovalChannel concrete
  - 4 tables added (tool_policies, tool_approvals, provider_state, provider_usage)

## Next
Block 3 step 3.1 — Vault parser.
```

---

## 5. Honest reality check

**Time estimate:** **8–12 days at sir's pace**, depending on OpenJarvis depth.

**Riskiest step:** 2.1 (investigation). Deep dives can eat days. **Hard
cap: 1 day.**

**Simplest step:** 2.4 (dummy tools). Smoke-test role.

**Most important step:** 2.5–2.6 (policy + hook). This is the *safety
circuit*. Every capability in blocks 6 / 7 / 9 depends on it.

**Least exciting part:** still foundation. No user-visible features.
The payoff lands in Block 3 onward.

**Assets carried over from Block 1:**

- `personas`, `users` tables — FK targets for policies / approvals
- `render_personality()` — unused in Block 2, picked up in Block 3
- Migration runner + ORM pattern — reused directly
- `--json` contract — applied uniformly to new commands
- `newton status` — extended with new counts
- 38 pytest cases — must still pass (regression guard)

---

## 6. Starting checklist

Before Block 2 begins:

- [ ] `git status` clean, on `newton-main`, HEAD at `v0.1.0-block1`
- [ ] `uv run newton status` reports green (DB + 3 personas + 2 users)
- [ ] `uv run pytest tests/newton/ -v` → 38 passed
- [ ] `./scripts/newton/preflight.sh` → 9/9 ✓
- [ ] OpenJarvis upstream catch-up is **optional** (`git fetch upstream`;
      any merge from upstream is recommended *after* Block 2, not during)
- [ ] At least 5 GB free disk (OpenJarvis source + dependencies)
- [ ] No process-level block on adding `psutil` (Step 2.4 will install it)

---

Ready when sir is. Step 2.1 is the entry point.
