# Newton v4 — Block 2, Step 2.1 Investigation & Decision Memo

> Status: **complete**
> Date: 2026-05-29
> Branch: `newton-main` · HEAD at investigation time: `bdc6ad5`
> Probe harness: `scripts/newton/block-2.1-probe.sh`
> Raw probe output: `docs/newton/block-2.1-probe-output.txt`
> Spec: `newton-v4-block-2.md` §1 Step 2.1
> Time spent: under the 1-day hard cap.

This memo answers the five investigation items, records the load-bearing
decision (Newton's tool layer is fully self-owned; OpenJarvis is used as an
LLM runtime only), and serves as ground truth for Steps 2.2–2.9.

---

## 0. Executive decision

**Newton ships its own tool layer end-to-end.** OpenJarvis's `BaseTool`
hierarchy and its ~60 concrete tools are **not** imported, subclassed, or
adapted. The only thing Newton imports from OpenJarvis is the **Ollama
inference engine** (`src/openjarvis/engine/ollama.py`) — the LLM runtime —
which is unrelated to the tool-calling layer and is consistent with Block 1's
"import is fine, edits are not" rule.

This is **Path B** (full separation), chosen over Path A (wrap OpenJarvis
`BaseTool`). Rationale in §6.

| Concern | Decision |
|---|---|
| Tool base class | Newton's own `newton.tools.base.Tool(ABC)` |
| Tool result wrapper | Newton's own `newton.tools.base.ToolResult` |
| Tool registry + dispatch | Newton's own `newton.tools.registry.ToolRegistry` |
| Args/returns schema | Pydantic **v2** `BaseModel` |
| Risk levels | **5 retained (0..4)** — all five are exercised by real tools |
| LLM runtime | **import** OpenJarvis `OllamaEngine`; never modify |
| OpenJarvis tool code | not used at all |

---

## 1. Item 1 — Does OpenJarvis have tool / function-calling code? Where?

**Yes, extensively.** OpenJarvis has a mature tool subsystem.

- Base class: `src/openjarvis/tools/_stubs.py` → `class BaseTool(ABC)`.
- ~60 concrete tools under `src/openjarvis/tools/`, spanning compute
  (`calculator.py`, `think.py`), local fs (`file_read.py`, `file_write.py`),
  process/exec (`shell_exec.py`, `code_interpreter.py`, `repl.py`), network
  (`http_request.py`, `web_search.py`, `browser.py`), messaging
  (`channel_tools.py`), agent control (`agent_tools.py`), knowledge/memory
  (`knowledge_*`, `storage_tools.py`, `memory_manage.py`), and more.
- A separate **skills** subsystem (`src/openjarvis/skills/`) layers on top,
  including `tool_adapter.py` (`SkillTool(BaseTool)`) and `tool_translator.py`.
- `src/openjarvis/tools/mcp_adapter.py` (`MCPToolAdapter(BaseTool)`) bridges
  MCP servers into the same `BaseTool` interface.

**Implication:** Newton is *not* filling a vacuum. The choice is reuse vs.
own — not build-from-nothing. See §6.

---

## 2. Item 2 — How are tool calls wired through the LLM adapter (Ollama)?

**Tool calls are wired at the engine layer, and the Ollama backend supports
them natively.**

- `src/openjarvis/engine/ollama.py` → `@EngineRegistry.register("ollama")`,
  `class OllamaEngine(InferenceEngine)`.
- The engine accepts a `tools=` kwarg, sends it to Ollama's native HTTP API,
  and parses `tool_calls` back out of both the non-streaming response
  (`data["message"]["tool_calls"]`) and the streamed chunks.
- It normalizes Ollama's quirk that **tool-call arguments arrive as dicts,
  not JSON strings**, and it implements a **retry-without-tools fallback**
  (`retry_without_tools=bool(tools)`) when a tools-enabled call fails.
- Tool *dispatch* (actually executing the chosen tool) does **not** live in
  the engine — it lives in the agents (`src/openjarvis/agents/`), e.g.
  `orchestrator.py::_run_function_calling` / `_exec_tool`. Tools are injected
  into agents (`OrchestratorAgent(engine, model, tools=tools, ...)`), not
  pulled from a central tool registry.

**Implication:** There is a clean seam. Newton can import `OllamaEngine` to
talk to the LLM and keep its **own** dispatch loop. Newton does not need —
and should not adopt — OpenJarvis's agent-embedded dispatch.

---

## 3. Item 3 — Dependencies (pydantic v1 vs v2, jsonschema, instructor)

**Pydantic v2, unambiguously.**

- `pyproject.toml`: `pydantic>=2` (and `pydantic>=2.0` in the `server` extra).
- Installed: **pydantic 2.12.5**, sqlalchemy 2.0.48, click 8.3.1.
- Source-signal scan across OpenJarvis: **36** v2 signals
  (`model_config`, `field_validator`, `model_dump`, `model_validate`),
  **0** v1 signals (`class Config:`, `@validator`, `.dict()`, `parse_obj`).
- `jsonschema`, `instructor`, `ollama` (python client) are **NOT installed** —
  OpenJarvis talks to Ollama over raw HTTP (`httpx`), not the `ollama` pip
  client, and does not depend on `instructor` for structured output.

**Implication:** Newton standardizes on **Pydantic v2 `BaseModel`** for
`args_schema` / `returns_schema`. The Step 2.2 provisional shapes need no
v1/v2 adjustment. No `jsonschema`/`instructor` dependency is introduced.
This **resolves** the open risk row "Pydantic v1 vs v2 mismatch" in the
block-2 risk matrix — there is no mismatch.

---

## 4. Item 4 — Register into OpenJarvis's registry, or keep our own?

**Keep Newton's own registry and dispatch itself.**

- OpenJarvis uses the registry pattern heavily, but for *other* axes:
  `EngineRegistry` (engines), `AgentRegistry` (agents), `LearningRegistry`
  (optimizers), plus an internal `EditApplierRegistry`. There is **no central
  `ToolRegistry`**. Tools are passed into agents as a `tools=` list, not
  registered into a global tool table.
- Therefore "register Newton tools into OpenJarvis's tool registry" is not
  even an option — the target does not exist.
- Newton's safety circuit (risk levels, `tool_policies`, `ApprovalChannel`,
  `tool_approvals` logging, dry-run) has no counterpart in OpenJarvis's
  agent-injection model and would have nowhere natural to attach.

**Implication:** `newton.tools.registry.ToolRegistry` is justified and
necessary. Newton owns `register / get / list / dispatch`, and `dispatch`
is where the approval hook (Step 2.6) intercepts.

---

## 5. Item 5 — Risk-level re-check: keep 5 levels, or collapse to 4 / 3?

**Keep all 5 levels (0..4).** Every level is exercised by a real, shipping
tool, so collapsing would lose genuine signal. Bucketing OpenJarvis's tools
against the proposed scale:

| Risk | Level | Representative OpenJarvis tools |
|---|---|---|
| 0 | SAFE | `CalculatorTool`, `ThinkTool` |
| 1 | READ_LOCAL | `FileReadTool`, `GitStatusTool`, `GitLogTool`, `GitDiffTool` |
| 2 | WRITE_LOCAL | `FileWriteTool`, `ApplyPatchTool`, `GitCommitTool`, `ShellExecTool`* |
| 3 | READ_NETWORK | `WebSearchTool`, `HttpRequestTool`, `BrowserNavigateTool`, `BrowserExtractTool` |
| 4 | WRITE_NETWORK | `ChannelSendTool`, `AgentSendTool`, `ImageGenerateTool`† |

\* `ShellExecTool` / `CodeInterpreterTool` are arguably *above* 4 (arbitrary
code execution). See the note below — Newton does not need to resolve this in
Block 2 because it ships none of these tools yet, but it is flagged for the
block that introduces an exec-class tool (Block 7, `os.command`).

† network-side generation; placed at 4 as a write-to-network class.

**Decision:** The 5-level scale (`TERMINOLOGY.md` §4, block-2 §0) is
**retained as-is**. The deferred "may collapse to 4 or 3" note in
`TERMINOLOGY.md` §12 is now **resolved → 5 confirmed**, and that line should
move out of the Deferred Decisions section.

**Follow-up (not Block 2):** consider whether an exec-class action
(arbitrary shell / code) deserves an explicit level 5 or a separate
"dangerous" flag orthogonal to the 0..4 network axis. Defer to the block
that first ships such a tool. Newton's own `echo_to_file` (risk 2) stays the
Block-2 approval-hook trigger as specified.

---

## 6. Path A vs Path B — why full separation

OpenJarvis's `BaseTool` is good, so the choice was real.

**Path A — wrap/import `BaseTool`.** Reuse ~60 tools immediately.
- ✗ Couples Newton's safety circuit to an upstream class Newton must never
  edit; any upstream change to `BaseTool` can break Newton silently.
- ✗ OpenJarvis tools assume agent-injection + agent-side dispatch; Newton's
  policy/approval/provider model would have to be retrofitted onto a flow it
  doesn't own.
- ✗ Risk level, `ToolContext`, `ApprovalChannel`, dry-run, and provider
  hot-swap have no place in `BaseTool`; Newton would be adapting around it
  everywhere anyway.
- ✓ Free tools today.

**Path B — Newton's own `Tool(ABC)` (CHOSEN).**
- ✓ Matches block-2 §0 locked decisions ("Newton owns its own layer",
  "OpenJarvis 0 lines touched") exactly.
- ✓ The safety circuit (risk → policy → approval → log → provider) is the
  whole point of Block 2 and lives natively in Newton's own abstraction.
- ✓ Clean dependency surface: Newton imports only the Ollama **engine** for
  LLM calls, nothing from `openjarvis.tools` / `openjarvis.skills`.
- ✓ No exposure to upstream refactors of the tool/skill subsystem.
- ✗ Newton re-implements tools it wants later (web_search, etc.) — but those
  arrive as **providers** in Blocks 6/7/9 under Newton's own registry anyway,
  so this is not duplicated work; it's the planned design.

**Boundary, precisely stated:**

```
Newton tool layer        = 100% Newton-owned
  newton.tools.base.Tool / ToolResult / RiskLevel
  newton.tools.registry.ToolRegistry  (register/get/list/dispatch)
  newton.tools.policy / approval      (Steps 2.5/2.6)
  newton.providers.*                  (Step 2.7')

OpenJarvis usage         = LLM runtime ONLY
  import openjarvis.engine.ollama.OllamaEngine   (talk to the model)
  never import openjarvis.tools.*  / openjarvis.skills.*  / openjarvis.agents.*
  never modify any OpenJarvis file
```

The LLM-call seam (import `OllamaEngine`) is itself deferred to whichever
block first needs Newton to drive an actual model with tool-calls; Block 2's
dispatch is exercised directly via CLI, so even the Ollama import is not yet
required by Block 2's own completion criteria. It is documented here so the
boundary is unambiguous when that wiring lands.

---

## 7. Confirmations carried into Steps 2.2–2.9

- **2.2** — Tool base shapes from the spec stand as-is. Pydantic v2.
  `RiskLevel` IntEnum 0..4 unchanged. No v1 compatibility shims.
- **2.3** — `ToolRegistry` is Newton-owned; no attempt to reuse an upstream
  tool registry (none exists). `dispatch()` is the approval-hook seam.
- **2.4** — `echo` / `system_info` / `echo_to_file` are Newton tools, not
  thin wrappers over `CalculatorTool` / `FileWriteTool`. `psutil` is the only
  new dep (already planned).
- **2.5/2.6** — policy matrix + `ApprovalChannel` ABC proceed exactly as
  specified; nothing upstream to integrate with.
- **2.7'** — `ProviderRegistry` is independent of `EngineRegistry`. Naming is
  distinct on purpose (`capability` strings like `demo.echo`, not engine ids).

## 8. Doc deltas this memo triggers

- `TERMINOLOGY.md` §12: remove "Risk level count … may collapse" — **resolved
  to 5**. Move nothing into §4; §4 already states 5.
- `newton-v4-block-2.md` §0 locked table: the two rows "Tool representation"
  and "Risk classification" are now **confirmed** rather than provisional;
  the "(final shape confirmed in Step 2.1)" / "explicitly revisited" caveats
  can be marked done.
- block-2 risk matrix: rows "OpenJarvis has a conflicting tool abstraction"
  and "Pydantic v1 vs v2 mismatch" → **closed** (full separation; v2 only).
