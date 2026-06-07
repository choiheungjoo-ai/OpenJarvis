# Block 2 — Tool Calling, Approval Hook & Provider Registry

Tag: `v0.2.0-block2`
Branch: `newton-main`

## What this block delivers

The safety circuit that lets a language model call a Python function on
sir's machine without that being a disaster. After block 2, Newton has a
tool subsystem with risk-classified calls, a cascading approval policy,
a CLI approval channel, an audit log of every decision, and a separate
hot-swappable provider registry for capability implementations. Every
later block that wants to make an LLM *do* something — read mail, write
a vault note, search the web, control the home — does it through this
circuit.

Concretely:

- A `Tool(ABC)` interface with `ToolResult`, `ToolContext`, and a 5-level
  `RiskLevel` (SAFE → WRITE_NETWORK).
- A `ToolRegistry` that owns `register / get / list / dispatch`, with a
  pluggable `PolicyHook` so dispatch is never reopened to add safety.
- Three built-in tools, one per Block-2 risk band:
  `echo` (risk 0), `system_info` (risk 1, psutil), `echo_to_file` (risk 2,
  confined to `<data_dir>/tool_scratch/` with traversal guard).
- A DB-backed approval policy matrix in `tool_policies` (tool × persona ×
  user → `auto_allow` | `require_approval` | `always_deny`) with cascading
  resolution and a fail-safe risk-based default.
- An `ApprovalChannel(ABC)` with three implementations:
  `CLIApprovalChannel` (blocking stdin prompt), `AutoApproveChannel`
  (still gated and logged), and `DenyChannel` (fallback when nothing
  interactive is available).
- An audit log table `tool_approvals` that records every decision that
  passed through the approval gate, including `always_deny` short-circuits.
- A separate `ProviderRegistry` for capability implementations, with
  three swap scopes (`once` / `session` / `permanent`) and DB persistence
  for the permanent scope via `provider_state`.
- Two demo providers (`echo_loud`, `echo_quiet`) under capability
  `demo.echo`, exercising every swap scope.
- A CLI surface covering 12 commands across `newton tools` and
  `newton providers`, including `tools run`, `tools policy` CRUD,
  `providers swap`, and runtime swap demonstration.
- `newton status` extended with tool/provider counts.
- 116 new pytest cases (154 total in `tests/newton/`).

What this block deliberately does **not** include: real network
providers (SearXNG/Brave/etc — block 7), MCP adapter, voice approval
channel, or any tool that does meaningful work in the real world beyond
echo and system-info. Those land where they have a use case.

## Steps and commits

| Step | Outcome                                              | Commit     |
|------|------------------------------------------------------|------------|
| 2.1  | Investigation memo: Newton owns its tool layer; OpenJarvis used only as LLM runtime | `25d7169`  |
| 2.2  | `Tool(ABC)`, `ToolResult`, `ToolContext`, `RiskLevel` | `f99d81f`  |
| 2.3  | `ToolRegistry` with injectable `PolicyHook` (Path C)  | `fb1df5b`  |
| 2.4  | Built-in tools: echo, system_info, echo_to_file       | `c7ef535`  |
| 2.5  | `tool_policies` table, cascade resolution, dynamic block-1 test helpers | `1ab85ec`  |
| 2.6  | Approval channels, `tool_approvals` audit log         | `5951dfb`  |
| 2.7  | `ProviderRegistry` with once/session/permanent scopes, `provider_state` | `f927f9c`  |
| 2.8a | `tools` and `providers` CLI groups with approval prompt | `4c099e3`  |
| 2.8b | Policy CRUD CLI, `decision` enum migration, status extension | `3e42f1b`  |
| 2.9  | This summary + tag `v0.2.0-block2`                    | (this tag) |

## Key design decisions (locked)

These shape every following block.

**Newton's tool layer is fully its own.**
Step 2.1 confirmed OpenJarvis has its own `BaseTool` hierarchy and ~60
concrete tools, plus a working Ollama engine. Newton imports the
**Ollama engine** when it needs to drive a model with tool-calls; it
does **not** import `openjarvis.tools.*` or subclass `BaseTool`. The
safety circuit (risk → policy → approval → log) is Newton's reason for
existing at the tool layer and lives natively in our own abstractions.
OpenJarvis files remain untouched.

**Five risk levels, all exercised.**
0 SAFE / 1 READ_LOCAL / 2 WRITE_LOCAL / 3 READ_NETWORK / 4 WRITE_NETWORK.
The 2.1 probe showed real tools at every band, so the scale did not
collapse to 4 or 3. An "exec-class" sixth level for arbitrary shell or
code execution is deferred to whichever block first ships such a tool
(block 7 is the candidate).

**Pydantic v2 throughout.**
The 2.1 probe showed OpenJarvis on pydantic 2.12.5 with zero v1 signals.
Newton standardises on v2 `BaseModel` for `args_schema` /
`returns_schema`. No v1 compatibility shims, no `jsonschema` /
`instructor` dependency.

**The approval policy is a cascading matrix in the database.**
`tool_policies` rows are keyed by (tool_name, persona_id, user_id) where
NULL is a wildcard. Resolution picks the most specific matching row.
When nothing matches, a risk-based default in code applies: risk ≥
WRITE_LOCAL needs approval, below it auto-allows. This means a brand-new
tool added without an explicit policy row is automatically conservative.

**Decision is a 3-state enum, not a boolean.**
The 2.5 schema started with `require_approval` (0/1) and was rebuilt in
migration 005 to `decision` (`auto_allow` | `require_approval` |
`always_deny`). `always_deny` short-circuits the channel — sir doesn't
get a prompt for tools they've already decided about.

**Dispatch never reopens for new safety features.**
Step 2.3 designed `ToolRegistry.dispatch` to take an *optional*
`PolicyHook`. 2.6 then plugged the real policy + approval logic in via
that hook without touching dispatch. Future safety additions (e.g. rate
limiting, geofencing) follow the same pattern.

**`tool_approvals` is an audit log, not a call log.**
Only decisions that involved the approval gate are recorded: prompts,
approvals, denials, and `always_deny` short-circuits. Auto-allowed calls
(risk 0–1 default, or a relaxing policy row) are not logged here.
General telemetry is the job of a future per-call log, not this table.

**`tool_approvals.user_id` is SET NULL on user delete.**
Matching block-1's audit-table convention (auth_attempts,
registration_requests): the decision trail outlives the user, only the
personal pointer drops.

**ApprovalChannel is fully abstract.**
The CLI prompt of block 2 is one implementation. Voice / push / async
channels in later blocks plug in by implementing the same `request()`
method. Nothing in policy or dispatch needs to change.

**Providers are a separate layer from tools.**
Tools carry approval/risk status; providers carry usage/cost telemetry.
A future `web_search` tool will *call* a `web.search` provider and wrap
its `ProviderResult` into the tool's `ToolResult`. `ProviderRegistry`
and `ToolRegistry` are deliberately not the same object.

**Provider swap precedence: once > session > permanent > default.**
A one-shot override wins because it represents the user's most recent
explicit intent for one call. Session beats permanent because the user
just typed it for this process. Permanent (DB-backed in `provider_state`)
beats the cost-priority default. `once` is consumed on read; `session`
and `permanent` are not.

**Test expectations are derived from filesystem, not hardcoded lists.**
Step 2.5 introduced `tests/newton/_schema_helpers.py` (migration versions
read from disk, model classes from package scan). Adding a migration or
a model file no longer requires editing assertion literals across the
block-1 test suite. This already paid for itself: 2.6, 2.7, 2.8 each
added at least one migration or model and required zero changes to
block-1 tests.

## What you can do after this block

```bash
# List tools, safest first
uv run newton tools list --json

# Run a safe tool
uv run newton tools run echo --args '{"text": "hi"}'

# Run a gated tool (blocking approval prompt)
uv run newton tools run echo_to_file --args \
  '{"relative_path": "note.txt", "text": "hello"}'

# ...or auto-approve for scripts
uv run newton tools run echo_to_file --yes --args \
  '{"relative_path": "note.txt", "text": "hello"}'

# Inspect a tool's args schema
uv run newton tools show echo_to_file --json

# Edit the policy matrix
uv run newton tools policy set echo_to_file --persona jarvis \
  --decision auto_allow --note "JARVIS is trusted for scratch writes"
uv run newton tools policy list --json
uv run newton tools policy unset echo_to_file --persona jarvis

# Hot-swap a provider
uv run newton providers list
uv run newton providers swap demo.echo echo_quiet --scope permanent
uv run newton providers active demo.echo
uv run newton providers test demo.echo --text "Hello Newton"
uv run newton providers usage --json
uv run newton providers health

# System snapshot now includes tool/provider counts
uv run newton status --json
```

## Verification

Block-2 acceptance criteria, all met:

- `uv run newton init` applies migrations 001 through 005; idempotent.
- `uv run newton tools list --json` returns three tools sorted by risk.
- `uv run newton tools run echo_to_file --args '{...}'` writes to
  `data/tool_scratch/` after sir's approval, refuses outside that tree.
- `uv run newton tools policy set ... --decision always_deny` blocks a
  subsequent `tools run` of the same tool, with the denial recorded in
  `tool_approvals`.
- `uv run newton providers swap demo.echo echo_quiet --scope permanent`
  persists across invocations; the change is in `provider_state`.
- `uv run newton providers list --json` shows the active provider per
  capability.
- `uv run newton status --json` includes `tools` and `providers` keys
  with counts and the active provider per capability.
- `uv run pytest tests/newton/ -v` reports **154 passed**.
- OpenJarvis files: still zero modifications.

## Known limits (resolved in later blocks)

- **No LLM in the loop yet.** Block 2 exercises the tool/provider
  circuit from the CLI. Wiring it to an actual model via Ollama happens
  in the block that first asks an LLM to call a tool (block 3 channel
  routing or block 4 voice).
- **CLI is the only approval channel.** Block 4+ will add voice
  approval (sir says "yes/no" to a TTS-spoken prompt) and possibly
  push notifications. They implement `ApprovalChannel` and slot in
  without touching policy or dispatch.
- **Demo providers only.** `echo_loud` / `echo_quiet` exist solely to
  exercise hot-swap. Real providers (SearXNG/Brave/Tavily/Firecrawl
  for `web.search`, MarkItDown for `doc.parse`, etc.) arrive in block 7.
- **No usage-quota enforcement.** `Provider.used_this_session` is a
  per-process counter; persistent monthly-quota accounting is deferred
  to whichever block ships a paid provider.
- **No risk-class beyond 4.** Arbitrary code/shell execution would
  benefit from an explicit "exec" level, but block 2 ships no such
  tool. Defer to block 7.
- **`tools run` writes prompts to stdout.** The blocking approval
  prompt and the JSON result share the same stream. Tests parse around
  it with a brace-balanced scanner, but a cleaner contract is
  prompt-to-stderr / data-to-stdout. Defer to a later CLI polish pass.

## Entry conditions for block 3

Block 3 (Vault + RAG + memory) can assume:

- `newton init` has been run; migrations 001–005 are applied.
- `ToolRegistry` and `ProviderRegistry` are importable from
  `newton.tools` and `newton.providers`. Builtins register through
  `register_builtins()` and `register_demo_providers()`.
- `build_policy_hook(get_session, approval_channel)` is the canonical
  way to assemble a hook for any surface (CLI, voice, web, MCP).
- Any new tool block 3 adds is registered the same way the three
  built-ins are; the safety circuit applies automatically.
- Any new capability block 3 adds (e.g. `embedding.encode`,
  `vault.search`) goes into `ProviderRegistry` with the same pattern
  as `demo.echo` had.
- `tests/newton/_schema_helpers.py` exists and derives model /
  migration expectations from disk, so adding tables in block 3 does
  not require editing block-1 / block-2 tests.

If `newton status` reports everything green and `uv run pytest
tests/newton/` shows 154 passed, block 3 is good to start.
