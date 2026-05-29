# Newton v4 — Block 4: ⭐ Proactive Engine

> Master plan: `newton-v4-master.md`
> Tech stack: `newton-v4-tech-stack.md`
> JARVIS gap analysis (13 capabilities): `newton-v4-jarvis-gap.md`
> Terminology: `TERMINOLOGY.md`
> Prerequisite: Block 3 complete (`v0.3.0-block3`, `docs/newton/block-3-summary.md`)
>
> **Goal:** Build the engine that makes Newton *initiate* rather than only
> respond. This is the block where Newton starts to feel like movie JARVIS.

---

## 0. Block 4 — overall goals

The behavioural shift this block delivers: Newton stops being Siri and
starts being JARVIS. It watches, learns sir's routines, anticipates, and
speaks up usefully.

Four sub-systems wired together:

1. **Background monitoring daemon** — continuously samples system state
   (CPU / GPU / memory / battery / temperature / network), time, calendar
   handles, screen activity hooks. Local only. ACL-respecting.
2. **Pattern recognition** — learns sir's weekly / daily / contextual
   routines from session history, message timing, vault activity, and
   monitored signals. Stored as `user_patterns` rows.
3. **Anticipation engine** — turns patterns + current context into
   predicted next actions with a confidence score. Below threshold →
   silent. Above → propose.
4. **Proactive notification system** — the *voice* of Newton's
   initiative. Throttled, mode-aware, quiet-hours-aware, learns from
   sir's accept / reject reactions.

This block ships the **common engine**. Specific JARVIS-gap capabilities
(calendar in block 9, smart home in block 9, OS commands in block 7,
screen / ambient awareness in block 6) land in their natural blocks but
use this engine. See `jarvis-gap.md` for the full 13-capability map.

### Locked decisions (entering Block 4)

| Item | Decision | Source |
|------|----------|--------|
| **Proactive mode default** | `smart` (clear patterns only) | master.md §1.7 |
| **Mode levels** | off / minimal / smart / aggressive | master.md §1.7 |
| **Mode switching** | by voice command, immediate effect | master.md §1.7 |
| **Quiet hours default** | 23:00–07:00, configurable | master.md §1.7 |
| **Daemon technology** | systemd user service (already required by environment) | master.md §10 |
| **Sampling interval** | adaptive — 5s when active, 60s when idle | this block |
| **Pattern store** | `user_patterns` table (laid down in block 1) | block 1 schema |
| **Notification store** | `proactive_notifications` table (laid down in block 1) | block 1 schema |
| **Confidence threshold (smart)** | 0.7 | jarvis-gap.md §6 |
| **Confidence threshold (aggressive)** | 0.5 | jarvis-gap.md §6 |
| **Rejection learning** | every "ignored" or "rejected" reaction lowers that pattern's confidence | this block |
| **Delivery channel** | block 4 ships CLI / desktop notification; voice delivery wires in block 5 | scope |
| **Capability dispatch** | uses block 2 ToolRegistry — proactive engine *triggers* tools, doesn't bypass approval | safety |
| **Tables already exist** | `system_metrics`, `user_patterns`, `proactive_notifications`, `screen_captures`, `calendar_events` (block 1 schema, empty until now) | block 1 |

### Completion criteria (block as a whole)

```bash
# Daemon up
$ uv run newton proactive start
proactive daemon started (PID 12345)
sampling: 60s idle, 5s active
mode: smart

$ uv run newton proactive status
mode: smart
quiet_hours: 23:00-07:00 (currently active=no)
patterns tracked: 47
notifications today: 3 (2 accepted, 1 ignored)
last sample: 12s ago

# Mode switching
$ uv run newton proactive mode aggressive
mode -> aggressive

# Patterns
$ uv run newton proactive patterns list
47 patterns:
  daily_routine: 12 (morning startup, coding focus, evening shutdown, ...)
  weekly_routine: 8 (Monday meeting prep, Friday review, ...)
  context: 27 (long-coding-needs-break, low-battery-near-deadline, ...)

# Manual trigger for testing
$ uv run newton proactive test "long_coding_session"
[proactive] pattern matched (confidence 0.82)
[proactive] would notify: "Sir, you've been coding for 2 hours. A short break might help."
[proactive] not delivered (test mode)

# Notification log
$ uv run newton proactive notifications --last 10
[2026-05-30 09:50] calendar_pre_meeting: "Sir, your weekly meeting starts in 10 minutes" -> accepted
[2026-05-30 10:15] battery_low_warning: "Sir, battery at 18%" -> ignored
...

# Tests
$ uv run pytest tests/newton/ -v
# Block 1-3: ~173 + Block 4: ~70 = ~243 passed
```

Block 4 ships the **engine**. Real-world wins (calendar alerts, screen
help, IoT, etc.) accumulate across blocks 5–9 as each capability plugs
into this engine.

---

## 1. Block 4 — 10 steps

Each step: one focused change, one verification, one commit.
`ruff check` + `ruff format` clean before commit.

Estimated total: **15–20 days at sir's pace.** Heavy because the daemon
architecture and pattern learning need careful design.

---

### Step 4.1 — Monitoring daemon foundation (1.5 days)

**Goal:** A long-running process that samples system metrics into
`system_metrics`, survives sir's session, restarts on crash.

**Outputs:**

- `newton/proactive/daemon.py`
  - `class ProactiveDaemon` — main loop
  - adaptive sampling (5s active / 60s idle)
  - graceful shutdown on SIGTERM
- `newton/proactive/monitors/system.py` — psutil CPU / memory / disk / battery
- `newton/proactive/monitors/gpu.py` — nvidia-ml-py VRAM / temp
- `newton/proactive/monitors/network.py` — connection + speed (optional)
- `scripts/newton/newton-proactive.service` — systemd user unit file
- `newton/cli.py` — `newton proactive start`, `stop`, `status`
- `tests/newton/proactive/test_daemon.py`

**Dependencies:**

```bash
uv add psutil nvidia-ml-py
```

**Verification:**

```bash
uv run newton proactive start
sleep 30
uv run newton proactive status
# at least 6 samples in system_metrics (60s interval → 30s in idle mode gives 0,
# but force-active during test → 6 samples at 5s)
sqlite3 data/newton.db "SELECT COUNT(*) FROM system_metrics WHERE captured_at > datetime('now', '-1 minute')"
uv run newton proactive stop

uv run pytest tests/newton/proactive/test_daemon.py -v
```

**Risk:** systemd user services on WSL2 need `systemctl --user` enabled.
**Mitigation:** fallback to a Python-only daemon mode (`newton proactive start --foreground`) for development; systemd unit ships but is optional.

**Commit:** `feat(proactive): monitoring daemon foundation`

---

### Step 4.2 — Threshold-based alerts (1 day)

**Goal:** Simplest proactive behaviour — when a metric crosses a
threshold, raise a notification.

This is the *training wheels* of proactivity. No pattern learning yet;
just "battery < 20% → notify".

**Outputs:**

- `newton/proactive/alerts.py` — threshold definitions + checker
- `config/proactive.yaml` — user-configurable thresholds
- `tests/newton/proactive/test_alerts.py`

**Default thresholds (from jarvis-gap.md §3.1):**

```yaml
proactive:
  thresholds:
    cpu_percent: 90
    gpu_percent: 85
    vram_percent: 95
    memory_percent: 90
    disk_percent: 90
    battery_percent_warning: 20
    battery_percent_critical: 10
    cpu_temp_c: 80
    gpu_temp_c: 83
    network_speed_drop_percent: 50
  cooldown_minutes: 15           # don't repeat the same alert within 15 min
```

**Flow:**

```
daemon samples metric
    ↓
threshold checker
    ↓
threshold exceeded + cooldown expired
    ↓
create proactive_notifications row (status: pending)
    ↓
[step 4.7 will deliver it; for now it just sits in DB]
```

**Verification:**

```bash
# Simulate battery low (mock)
uv run newton proactive test-alert battery_low
# notification row created
sqlite3 data/newton.db "SELECT notification_text, status FROM proactive_notifications ORDER BY created_at DESC LIMIT 1"
# "Sir, battery at 18%" | pending
```

**Commit:** `feat(proactive): threshold-based alerts`

---

### Step 4.3 — Pattern recognition foundation (2 days)

**Goal:** Detect repeated time-based and sequence-based patterns from
existing data sources.

**Outputs:**

- `newton/proactive/patterns/__init__.py`
- `newton/proactive/patterns/time_based.py` — weekly / daily routines
- `newton/proactive/patterns/sequence.py` — "X often follows Y"
- `newton/proactive/patterns/context.py` — "when context Z, sir does W"
- `newton/proactive/patterns/learner.py` — orchestrates pattern detection runs
- `newton/cli.py` — `newton proactive patterns list / show / forget`
- `tests/newton/proactive/test_patterns.py`

**Inputs the learner reads:**

- `sessions` table — when does sir activate, with which persona, how long
- `messages` table — message timing, content topics (via simple keyword extraction)
- `system_metrics` — accumulated by step 4.1
- `vault_notes` — when notes are created / modified
- `tool_approvals` — what tools sir runs, when

**Pattern detection runs:**

```
Once daily at 03:00 (configurable):
    learner.run_daily()
        - find weekly patterns (sessions clustered by weekday + hour)
        - find sequence patterns (tool X often followed by tool Y within 10 min)
        - find context patterns (when battery low AND time > 22:00, sir tends to shut down)
    update user_patterns rows (insert new, increment occurrences on match)
```

**Schema (extending block 1's `user_patterns`):**

```sql
-- user_patterns already created in block 1, but let's clarify what goes in pattern_data_json

-- time_based example:
{
    "kind": "weekly",
    "weekday": 1,                  -- 0=Mon
    "hour": 9,
    "minute_start": 50,
    "action": "calendar_meeting_prep",
    "observed_count": 7
}

-- sequence example:
{
    "kind": "sequence",
    "after_tool": "vault_search",
    "then_tool": "vault_write",
    "within_seconds": 600,
    "observed_count": 12
}

-- context example:
{
    "kind": "context",
    "preconditions": [
        {"metric": "battery_percent", "op": "<", "value": 25},
        {"time_after": "21:00"}
    ],
    "action": "shutdown",
    "observed_count": 5
}
```

**Verification:**

```bash
# Seed synthetic session data spanning 4 weeks
uv run newton proactive seed-test-data
uv run newton proactive patterns learn --once
uv run newton proactive patterns list
# expect at least 3 weekly patterns, 2 sequence patterns

uv run pytest tests/newton/proactive/test_patterns.py -v
```

**Risk:** Pattern learner false positives (one-off events treated as
patterns). **Mitigation:** require `observed_count >= 3` before any
pattern can fire; `confidence = min(1.0, occurrences / 10)`.

**Commit:** `feat(proactive): pattern recognition (time/sequence/context)`

---

### Step 4.4 — Anticipation engine (2 days)

**Goal:** Given the current moment + recent context, return ranked
predicted actions with confidence scores.

**Outputs:**

- `newton/proactive/anticipation.py`
  - `class AnticipationEngine`
  - `predict(now: datetime, context: Context) -> list[Prediction]`
- `newton/proactive/context.py` — assembles current context (time, active session, recent metrics, recent messages, calendar handle)
- `tests/newton/proactive/test_anticipation.py`

**Prediction shape:**

```python
@dataclass
class Prediction:
    pattern_id: int
    action: str                    # e.g. "calendar_meeting_prep"
    confidence: float              # 0.0 - 1.0
    rationale: str                 # human-readable why
    eta: datetime | None           # when the action would fire
    notification_text: str | None  # what to say to sir, if anything
```

**Prediction flow:**

```
context = Context.assemble()
    ↓
candidates = all user_patterns where preconditions match `context`
    ↓
for each candidate:
    confidence = min(1.0, candidate.occurrences / 10)
    apply rejection penalty (see step 4.6)
    ↓
filter: confidence >= mode_threshold
        (smart: 0.7, aggressive: 0.5, minimal: 0.9, off: never)
    ↓
sort by confidence desc
    ↓
return top 5
```

**Verification:**

```bash
# With patterns from step 4.3 in DB
uv run newton proactive predict
# top 3 predictions printed with confidence + rationale

uv run pytest tests/newton/proactive/test_anticipation.py -v
```

**Commit:** `feat(proactive): anticipation engine with confidence scoring`

---

### Step 4.5 — Proactive notification scheduler (1.5 days)

**Goal:** Turn predictions into scheduled notifications, respecting mode,
quiet hours, and cooldown.

**Outputs:**

- `newton/proactive/scheduler.py`
  - `Scheduler` — periodically asks AnticipationEngine, creates `proactive_notifications` rows
  - Quiet-hours enforcement
  - Mode-aware threshold lookup
- `newton/proactive/quiet_hours.py` — handles configurable windows + timezone
- `tests/newton/proactive/test_scheduler.py`

**Decision flow per scheduler tick (every 60 s):**

```
mode == off                        → skip
in quiet_hours                     → skip (except for `urgent` priority)
predictions = anticipation.predict(now)
    ↓
filter:
    - already-pending row for same pattern? skip (cooldown)
    - confidence < mode_threshold? skip
    ↓
for top prediction:
    create proactive_notifications row (status: scheduled)
```

**Verification:**

```bash
uv run newton proactive start
sleep 70
# scheduler tick happens, may create a notification
sqlite3 data/newton.db "SELECT notification_text, status FROM proactive_notifications WHERE status='scheduled'"
```

**Commit:** `feat(proactive): notification scheduler with quiet hours`

---

### Step 4.6 — Reaction learning + nag prevention (1.5 days)

**Goal:** When sir reacts to a notification (accept / reject / ignore),
update the underlying pattern's confidence. Prevent the same suggestion
from being repeated after rejection.

**Outputs:**

- `newton/proactive/learning.py`
  - `record_reaction(notification_id, reaction: 'accepted'|'rejected'|'ignored')`
  - reaction → pattern update
- `newton/cli.py` — `newton proactive react <notification_id> --accept`/`--reject`/`--ignore`
- `tests/newton/proactive/test_learning.py`

**Update rules:**

```
accepted:
    pattern.occurrences += 1
    notification_penalty = 0
rejected:
    pattern.occurrences = max(1, pattern.occurrences - 2)
    notification_penalty for this pattern = +0.2 (lasts 7 days)
ignored:                              # no explicit response within 5 min
    pattern.occurrences unchanged
    notification_penalty for this pattern = +0.05 (lasts 2 days)
```

`anticipation.predict()` subtracts the cumulative penalty from
confidence before threshold check. So a rejected pattern won't surface
again for a week.

**Verification:**

```bash
# Manual reaction
uv run newton proactive notifications --last 1
# id: 42
uv run newton proactive react 42 --reject

# Same pattern should not fire again for 7 days
uv run newton proactive predict --include-suppressed
# shows pattern 42 with confidence 0.45 (was 0.65), suppressed=yes
```

**Commit:** `feat(proactive): reaction learning + nag prevention`

---

### Step 4.7 — Notification delivery: CLI + desktop (1 day)

**Goal:** Actually deliver pending notifications to sir.

Block 4 ships CLI prints + desktop notifications (libnotify on
Linux / WSL2 via the `notify-send` shim). Voice delivery wires in
block 5 by adding a new `DeliveryChannel`.

**Outputs:**

- `newton/proactive/delivery/__init__.py`
- `newton/proactive/delivery/base.py` — `class DeliveryChannel(ABC)`
- `newton/proactive/delivery/cli.py` — print to a long-lived `newton proactive watch` command
- `newton/proactive/delivery/desktop.py` — `notify-send` for Linux desktops
- `newton/cli.py` — `newton proactive watch` (streams notifications)
- `tests/newton/proactive/test_delivery.py`

**Pattern parallel to block 2's `ApprovalChannel`:**

```python
class DeliveryChannel(ABC):
    name: ClassVar[str]
    async def deliver(self, notification: Notification) -> Reaction: ...

class CLIDeliveryChannel(DeliveryChannel):
    name = "cli"
    # prints to active `newton proactive watch` if running; otherwise marks as 'queued'

class DesktopDeliveryChannel(DeliveryChannel):
    name = "desktop"
    # uses notify-send
```

Block 5 will add `VoiceDeliveryChannel` without touching block 4.

**Verification:**

```bash
# Terminal 1
uv run newton proactive watch

# Terminal 2
uv run newton proactive test-notification "Sir, test message"

# Terminal 1 prints:
# [12:34:56] proactive: Sir, test message
```

**Commit:** `feat(proactive): delivery channel abstraction + CLI/desktop`

---

### Step 4.8 — Mode commands + proactive_mode in users table (half-day)

**Goal:** sir can change proactive mode by command. Block 5 adds voice
trigger; block 4 ships the CLI side.

**Outputs:**

- `migrations/008_proactive_mode.sql` — adds `proactive_mode` column to `users` (default: 'smart')
- `newton/proactive/modes.py` — mode handlers, time-bounded mode (e.g. "off for 1 hour, then revert to smart")
- `newton/cli.py` — `newton proactive mode <off|minimal|smart|aggressive> [--for 1h]`
- `tests/newton/proactive/test_modes.py`

**Schema:**

```sql
ALTER TABLE users ADD COLUMN proactive_mode TEXT NOT NULL DEFAULT 'smart';
ALTER TABLE users ADD COLUMN proactive_mode_revert_at TIMESTAMP;
```

`proactive_mode_revert_at` is NULL for permanent modes. Time-bounded
("off for 1 hour") sets it; the scheduler checks it and reverts when
elapsed.

**Verification:**

```bash
uv run newton proactive mode off --for 1h --user sir
# users.proactive_mode = 'off', revert_at = now+1h

# After 1h (or simulated)
uv run newton proactive tick
# automatic revert to 'smart'
sqlite3 data/newton.db "SELECT proactive_mode FROM users WHERE user_id='sir'"
# smart
```

**Commit:** `feat(proactive): mode commands with time-bounded reverts (migration 008)`

---

### Step 4.9 — Proactive recall integration with vault (1.5 days)

**Goal:** When sir's current conversation touches a topic that matches
an old conversation summary in vault, surface it.

This is where block 3's long-term memory pays off.

**Outputs:**

- `newton/proactive/recall.py` — semantic similarity check against `_auto/conversations/` notes
- Hooks into `messages` insert (each new message → check for relevant past)
- `tests/newton/proactive/test_recall.py`

**Flow:**

```
sir's new message arrives (in any active session)
    ↓
recall.check(message, user_id, persona_id)
    ↓
vault search restricted to `_auto/conversations/` notes
    ↓
top match score > 0.85?
    ↓
yes → create proactive_notifications row:
       "Sir, last time you asked about this you decided X.
        Want me to surface that conversation?"
no   → silent
```

**Mode awareness:** proactive recall only fires in `smart` or
`aggressive` mode, never `minimal` or `off`.

**Verification:**

```bash
# Assume vault has a summary from last week mentioning "Block 3 design"
# sir starts a new session, asks "what did we decide about embeddings"
# proactive recall fires:
# "Sir, last week's conversation T1217 covered this. Surface it?"

uv run pytest tests/newton/proactive/test_recall.py -v
```

**Commit:** `feat(proactive): vault-driven recall on relevant new messages`

---

### Step 4.10 — Block 4 summary + tag (1–2 hours)

**Goal:** Lock the block, list what shipped, define Block 5 entry conditions.

**Outputs:**

- `docs/newton/block-4-summary.md`
- `docs/newton/cli.md` — final pass for new commands
- `README.md` — Block 4 marked complete
- `pyproject.toml` — lockfile tidied
- Git tag: `v0.4.0-block4`

**Block 5 entry conditions (provisional):**

- `newton proactive start/stop/status` works
- `newton proactive mode` works (CLI side; voice side comes in block 5)
- `system_metrics` populates continuously
- `user_patterns` has detected patterns from seeded test data
- Anticipation engine returns predictions with confidence
- Scheduler respects mode + quiet hours
- Reactions update pattern confidence
- Two delivery channels work (CLI + desktop)
- Proactive recall hooks into messages and uses vault
- All pytest cases pass (~243 total)
- Preflight 9/9 still ✓
- OpenJarvis: still 0 files modified

**Commit + tag:** `chore: block 4 complete`

---

## 2. Deliberately not in Block 4

These 13 capabilities live in their *natural* blocks; this block only
provides the proactive infrastructure they call into:

- ❌ **Calendar integration** — block 9 (uses scheduler for "10 minutes before meeting" alerts)
- ❌ **Smart home / IoT** — block 9 (uses scheduler for morning / evening routines)
- ❌ **Screen awareness** — block 6 (uses monitor pattern from this block)
- ❌ **Ambient awareness** — block 6
- ❌ **OS command execution** — block 7
- ❌ **Real-time translation** — block 7
- ❌ **HUD** — block 11 (uses delivery channel from this block; adds visual overlay)
- ❌ **Meeting mode** — block 5 (uses scheduler for "meeting starting" alerts)
- ❌ **Wellness / health** — opt-in, block 9 or later, default off
- ❌ **Security monitoring (unknown face, etc.)** — block 6 (uses scheduler)
- ❌ **Voice delivery channel** — block 5

Principle: *this block is the engine, not the car.*

---

## 3. Risk matrix

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Daemon crashes lose monitoring data | Med | systemd restart=on-failure; metrics are advisory, not authoritative |
| systemd user services don't work on WSL2 | Med | Foreground mode fallback (`newton proactive start --foreground`) |
| Pattern learner false positives (one-offs) | High | `observed_count >= 3` threshold; rejection learning further dampens |
| Notifications too frequent → sir disables proactive entirely | High | smart default + cooldown + nag prevention; bias toward silence |
| Quiet hours misconfigured (timezone) | Med | use `users.timezone` (block 4 also reads it); default Asia/Seoul; explicit `--tz` flag |
| Recall surfaces wrong old conversations | Med | semantic threshold 0.85, sir can dismiss + lower threshold next time |
| psutil / nvidia-ml-py on RTX 5090 | Low | RTX 5090 supported in nvidia-ml-py >= 12; pinned in tech-stack |
| Proactive mode column added late breaks block 1 invariants | Low | migration 008 is additive (new column with default); FK invariants preserved |
| Reaction reporting forgotten by sir | Med | `ignored` state auto-recorded after 5 min; explicit react commands optional |
| 15–20 day estimate optimistic | Med | Block 3 was 15–25; block 4 has more new concepts. Re-estimate after step 4.4 |

---

## 4. After Block 4 — opening message for the next chat

```markdown
# Newton v4 — Block 5 start (Voice Layer + meeting mode)

## Context
- Newton: multi-persona AI OS, OpenJarvis fork
- Environment: RTX 5090 + WSL2 Ubuntu + systemd
- Location: ~/newton-v4/

## Design docs
[newton-v4-master.md]
[newton-v4-tech-stack.md]
[newton-v4-voice.md]      # block 5 details
[newton-v4-engines.md]
[newton-v4-block-4.md]    # complete
[newton-v4-block-5.md]    # this block
[TERMINOLOGY.md]

## Blocks 1–4 result
- v0.1.0-block1: identity & data foundation (13 tables)
- v0.2.0-block2: tool calling + approval hook + provider registry
- v0.3.0-block3: persona engine + vault + ACL + RAG + memory
- v0.4.0-block4: proactive engine — monitoring + patterns + anticipation + delivery
  - Background daemon sampling system / GPU / network
  - Pattern learner with time / sequence / context detection
  - Anticipation engine with confidence scoring
  - Mode-aware scheduler (off/minimal/smart/aggressive)
  - Quiet hours, cooldown, nag prevention
  - CLI + desktop delivery channels (voice channel coming this block)
  - Proactive recall into vault conversation summaries

## Next
Block 5 step 5.1 — Silero VAD integration.
```

---

## 5. Honest reality check

**Time estimate:** **15–20 days at sir's pace.** New paradigm (long-running
daemon, pattern learning) takes thought.

**Riskiest steps:**

- **Step 4.3** (pattern recognition) — easy to write, hard to tune so
  sir doesn't get annoyed
- **Step 4.6** (reaction learning) — incorrectly attribute rejection to
  pattern X when sir rejected for an unrelated reason
- **Step 4.9** (proactive recall) — semantic similarity false matches
  can make Newton look stupid

**Simplest steps:**

- 4.1 (daemon) — boring plumbing
- 4.8 (mode commands) — straightforward
- 4.10 (summary)

**Most important step:**

- **Step 4.6** (reaction learning + nag prevention). Without this, smart
  mode degrades into aggressive mode within a week as occurrences pile up.

**Behavioural shift:**

After block 4 sir's experience with Newton changes qualitatively. Before
block 4: "sir asks, Newton answers." After block 4: "Newton occasionally
speaks up without being asked — usefully, hopefully."

**Assets carried over from Blocks 1–3:**

- `user_patterns`, `proactive_notifications`, `system_metrics`,
  `screen_captures`, `calendar_events` tables — schema exists; block 4
  fills them
- `ApprovalChannel` pattern from block 2 → `DeliveryChannel` parallel
- Vault search from block 3 → proactive recall
- Long-term memory from block 3 → ammunition for recall
- ~173 pytest cases — must still pass

---

## 6. Starting checklist

Before Block 4 begins:

- [ ] `git status` clean, on `newton-main`, HEAD at `v0.3.0-block3`
- [ ] `uv run newton status` reports green
- [ ] `uv run pytest tests/newton/ -v` → ~173 passed (blocks 1–3)
- [ ] `./scripts/newton/preflight.sh` → 9/9 ✓
- [ ] `psutil`, `nvidia-ml-py` can be installed
- [ ] `notify-send` available on the host (or accept the desktop-channel skip)
- [ ] `systemctl --user` enabled (or accept foreground-only daemon)
- [ ] sir has 3–4 weeks of focused work available
- [ ] At least 4 weeks of session history accumulated since block 3 (so the pattern learner has data; can be backfilled with synthetic data if needed)

---

Ready when sir is. Step 4.1 is the entry point.
