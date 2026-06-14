# Block 4 — Proactive Engine

Tag: `v0.4.0-block4`
Branch: `newton-main`

## What this block delivers

The behavioural shift from Siri to JARVIS. After block 4 Newton stops
being a thing that only answers when asked and starts being a thing
that occasionally speaks up — usefully, hopefully. A background daemon
samples system state, a learner detects routines, an anticipation
engine ranks predictions by confidence × relevance, a scheduler turns
those into rows in `proactive_notifications` while respecting mode and
quiet hours, delivery channels surface them on CLI and desktop, and a
reaction-learning path makes the system shut up about things sir has
rejected.

Concretely:

- A `ProactiveDaemon` (monitor loop) that samples CPU / memory /
  battery via psutil and GPU util / temperature via pynvml (best-effort,
  disappears cleanly on GPU-less hosts). Adaptive interval — 5s when a
  session is open, 60s when idle — and a sliced shutdown that returns
  within ~500 ms of SIGTERM regardless of the current sleep window.
- Threshold-based alerts: a YAML-driven set of `cpu_high`, `gpu_high`,
  `memory_high`, `gpu_temp_hot`, `battery_low`, `battery_critical`
  rules, with a `[kind]` storage prefix that lives only in the DB
  (storage-only — never reaches the user; `display_text` strips it).
  Four more rules ship dormant (`vram_high`, `disk_high`, `cpu_temp_hot`,
  `network_slow`) so future monitors wake them up with zero code
  change.
- A pattern learner for **time** patterns (weekly buckets in
  `pattern_timezone`) and **sequence** patterns (A → B within window,
  back-to-back A dedupes to one anchor, approved-only). **Context**
  patterns are deferred; `patterns/context.py` explains the schema gap
  that blocks them and what needs to land first.
- A three-factor confidence model that replaces the design doc's
  `min(1.0, occurrences / 10)`:

      confidence = consistency × volume_factor × recency_factor × (1 - penalty)

  Every coefficient is in `config/proactive.yaml`; no magic numbers in
  Python. `ConfidenceBreakdown` exposes the math so `patterns show`
  prints why a number landed where it did. `occurrences` is rewritten
  each learn run (the in-window count) — idempotent across re-runs and
  naturally decay-aware.
- An anticipation engine that reads **stored** confidence (no
  re-running the learner per-tick) and multiplies by **relevance**
  from a swappable `RelevanceStrategy`. Default
  `TimeProximityRelevance` decays time patterns with a Gaussian σ in
  config and treats sequence patterns as binary (1.0 if the A-event
  ran inside the window, else 0.0). Mode thresholds
  (off/minimal/smart/aggressive) live in config; the engine holds no
  constants of its own. `off` uses 1.01 so the `>=` check has no
  special case.
- A notification scheduler with three gates the engine doesn't
  enforce: `mode=off` short-circuit (logged for telemetry), quiet
  hours (default 23:00-07:00 in `pattern_timezone`, wraps midnight,
  bypassable by `urgent`), and per-pattern cooldown keyed on
  `trigger_pattern_id`. Mode `__auto__` resolves the user's stored
  `users.proactive_mode` and heals any expired time-bounded revert in
  the same call.
- Reaction learning: `accepted` / `rejected` / `ignored` write the
  existing `user_response` column. The doc's "mutate
  `user_patterns.occurrences`" path is rejected because the learner
  rewrites that column each run; instead the *penalty* is computed at
  predict time from recent reaction history (`rejected_weight` × N
  within `rejected_ttl_days`, plus `ignored_weight` × N within
  `ignored_ttl_days`, clipped to [0, 1]). Auto-ignore flips
  unanswered rows to `ignored` after `auto_ignore_minutes` so quiet
  rejection (no response) is still a signal.
- A `DeliveryChannel` ABC, parallel to block 2's `ApprovalChannel`,
  with `CLIDeliveryChannel` (stream write) and `DesktopDeliveryChannel`
  (`notify-send`, falls back to delivered=False when the binary is
  absent). The `DeliveryDispatcher` fans a notification to every
  channel and dedupes by id in-process; auto-ignore handles
  long-horizon dedup. The `[kind]` and `[recall:N]` storage markers
  are stripped by `display_text` at the channel boundary — every
  surface stays uniform.
- Migration 010 adds `users.proactive_mode` (`CHECK` constrained,
  default `smart`) and `users.proactive_mode_revert_at` (NULL for
  permanent). `newton.proactive.modes.set_mode` + `resolve_mode` wrap
  reads and writes; `apply_revert_due` heals expired reverts in batch.
- Vault-driven proactive recall: `newton.proactive.recall.check`
  semantic-searches `_auto/conversations/` for the new message, picks
  the top hit, and writes a `[recall:<note_id>] …` row when
  `score >= min_score` (0.85 default) and the note isn't in per-note
  cooldown. The searcher is injectable so unit tests run without
  Qdrant + TEI. Recall fires only in `smart`/`aggressive` mode.

What this block deliberately does **not** include: a real LLM
generating the predicted notification text (block 5's voice layer
polishes the templates), context patterns (the action-event stream
isn't in the schema yet), `users.timezone` per-user (deferred to
whichever step actually needs per-user differentiation; KST is
configured globally for now), the SQLAlchemy `after_insert` hook
on `messages` that auto-fires recall (block 5's runtime), and the
systemd timer that runs `patterns learn --once` daily (block 4.8 or
later, paired with the mode-revert timer).

## Steps and commits

| Step | Outcome                                                        | Commit     |
|------|----------------------------------------------------------------|------------|
| 4.1  | Monitoring daemon foundation (psutil + best-effort pynvml)     | `bcdcb8f`  |
| 4.2  | Threshold-based alerts (storage-only `[kind]` prefix)          | `f300709`  |
| 4.3  | Pattern recognition (time/sequence) + three-factor confidence  | `2833e75`  |
| 4.4  | Anticipation engine (confidence × relevance, swappable strategy) | `f2ff566` |
| 4.5  | Notification scheduler + quiet hours                           | `3673733`  |
| 4.6  | Reaction learning + nag prevention                             | `449ea15`  |
| 4.7  | Delivery channels (CLI + desktop)                              | `249f206`  |
| 4.8  | Mode commands + migration 010 (`users.proactive_mode`)         | `e46ccb3`  |
| 4.9  | Vault-driven proactive recall                                  | `28297a6`  |
| 4.10 | This summary + tag `v0.4.0-block4`                             | (this tag) |

## Key design decisions (locked)

These shape every following block.

**The daemon doesn't import any CUDA-bound library.**
GPU monitors go through pynvml (NVML over `/dev/nvidia*`, not CUDA),
gated behind the existing `gpu-metrics` extra. The core stays
importable on a GPU-less laptop. The strategy-D rule we held all
through block 3 holds here too.

**Storage markers are stripped at the channel boundary, by one helper.**
Two storage flavours exist: alerts carry `[<kind>]` (4.2) for cooldown
lookups, recall carries `[recall:<note_id>]` (4.9) for per-note
cooldown. `alerts.display_text` strips either — *all* user-facing
surfaces (CLI watch, desktop notify-send, notifications list, predict
JSON, test-alert CLI) go through it. New flavours add one alternation
to the regex; surfaces don't change. Tests assert the prefix is gone
on every render path.

**Confidence and relevance are separate concerns.**
The learner writes a stored confidence to `user_patterns` (cheap reads
for the anticipation engine + the scheduler). The anticipation engine
multiplies that by a live-computed relevance and an externally-supplied
penalty. The breakdown is fully explainable: `patterns show` prints
both stored and live-recomputed confidence (so config drift is
visible, not silent); `proactive predict` prints the rationale chain
including which mode threshold was checked and whether it passed.

**`occurrences` is the learner's source of truth.**
The doc proposed mutating `occurrences` on accept / reject. We don't —
the learner rewrites that column each run to the in-window count, and
reactions would fight that. Reactions become *penalty* instead,
computed at predict time from `user_response` history. No schema
change, no race between the learner and the reaction tracker.

**Mode thresholds live in config; the engine holds no constants.**
`off` uses 1.01 so a `>=` test handles it without a special case for
"never fire." Adding a new mode = edit the YAML; the engine grows
nothing.

**Quiet hours, cooldowns, sigmas, TTLs, weights — all in config.**
`config/proactive.yaml` is the user-tuning surface. There's a
`ProactiveConfig` pydantic root with seven sub-sections (`thresholds`,
`cooldown_minutes`, `patterns`, `anticipation`, `scheduler`,
`reactions`, `recall`). A `proactive.local.yaml` overlay is supported
for sir-only overrides without dirtying git.

**Pattern detection is intentionally narrow in 4.3.**
Time + sequence ship; context is stubbed with a docstring that lays
out the missing pieces (an action-event stream, episode detection
from discrete samples). The schema's `pattern_type CHECK` already
allows `'context'` so a future detector drops in with no migration.

**Recall is opt-in and mode-aware.**
Default `enabled=true` only in `smart` / `aggressive`. The min-score
gate (0.85) is conservative on purpose; tune down as the summarizer
matures.

## What you can do after this block

```bash
# Daemon
uv run newton proactive start --foreground         # samples + checks alerts + scheduler
uv run newton proactive status
uv run newton proactive stop

# One-shot smoke
uv run newton proactive start --foreground --once

# Alerts
uv run newton proactive test-alert battery_low

# Patterns
uv run newton proactive seed-test-data            # 4-week deterministic scenario
uv run newton proactive patterns learn --once
uv run newton proactive patterns list
uv run newton proactive patterns show <id>        # stored + live confidence + breakdown
uv run newton proactive patterns forget <id>

# Anticipation
uv run newton proactive predict --user sir --mode smart

# Scheduler
uv run newton proactive schedule --user sir --mode smart [--urgent]

# Reactions
uv run newton proactive notifications --last 10
uv run newton proactive react <id> --accept|--reject|--ignore

# Mode
uv run newton proactive mode aggressive --user sir
uv run newton proactive mode off --user sir --for 1h
uv run newton proactive mode --user sir            # show current
uv run newton proactive mode --list                # snapshot all users

# Delivery (live)
uv run newton proactive watch --user sir

# Recall (smoke)
uv run newton proactive recall-check "embeddings architecture" --user sir --persona jarvis
```

## Verification

Block-4 acceptance criteria, all met:

- `uv run newton init` applies migrations 001 through 010; idempotent.
- The daemon samples `system_metrics` rows on the configured cadence,
  shuts down on SIGTERM within ~500 ms, and survives misbehaving
  monitors.
- Threshold alerts insert `proactive_notifications` rows with the
  `[kind]` storage prefix; every user-facing surface displays
  prefix-stripped text.
- The pattern learner is idempotent: running `learn --once` twice
  produces the same set of `user_patterns` rows with identical
  `occurrences`. Confidence reflects consistency × volume × recency ×
  (1 - penalty); the breakdown is explainable through
  `patterns show`.
- The anticipation engine returns ranked predictions with rationale.
  Mode thresholds gate the output. The relevance strategy is
  swappable.
- The scheduler writes rows for the top-N predictions, respects mode
  / quiet hours / per-pattern cooldown, and heals expired
  time-bounded modes before reading anything.
- `record_reaction` updates `user_response` and `response_at`. A
  pattern with repeated recent rejections sees its score driven below
  threshold; one rejection alone subtracts the configured weight.
  Auto-ignore flips unanswered rows after `auto_ignore_minutes`.
- Two delivery channels (`cli`, `desktop`) deliver pending rows.
  `watch` streams them. The `[kind]` and `[recall:N]` markers are
  stripped at every surface.
- `proactive mode` changes the stored value; a `--for 1h` setting
  reverts on the next tick after the hour elapses.
- `recall.check` writes a `[recall:<note_id>]` row when the top vault
  match crosses 0.85; below threshold, no row.
- `uv run pytest tests/newton/` reports **427 passed** (unit), with
  another **39** marker tests (qdrant / embedding) available when
  Docker is up. New tests added in block 4: **182** (baseline 245 →
  427).
- OpenJarvis files: still **zero** modifications.

## Known limits (resolved in later blocks)

- **No real LLM produces the predicted notification text yet.** The
  templates in `AnticipationEngine._notification_text` are
  first-pass; block 5's voice layer polishes prose and routing.
- **The `messages` insert hook for proactive recall isn't wired.**
  `recall.check` exists and is callable, with full test coverage and
  a CLI smoke command. Block 5's runtime wires the auto-trigger.
- **`patterns learn` runs only via `--once`.** The systemd timer that
  fires it daily belongs alongside the daemon and mode-revert timer.
  Likely a later block-4 patch or the start of block 5.
- **`users.timezone` is still absent.** `pattern_timezone` in the
  YAML covers weekday bucketing and quiet hours for now. The column
  lands when per-user differentiation actually matters.
- **Context patterns return `[]`.** The action-event stream and
  episode-detection helper are prerequisites; `patterns/context.py`
  docstring explains the gap.

## Entry conditions for block 5

Block 5 can assume:

- `newton proactive` is fully wired: `start / stop / status`,
  `test-alert`, `patterns {list, show, forget, learn --once}`,
  `seed-test-data`, `predict`, `schedule`, `notifications`,
  `react`, `mode`, `watch`, `recall-check`.
- `proactive_notifications` rows carry their lifecycle in
  `user_response` + `response_at` columns. Implicit "pending" is the
  absence of a response.
- `display_text` strips every storage marker (`[kind]` and
  `[recall:N]`). Block 5 voice delivery just renders the result.
- `DeliveryChannel` is the seam for `VoiceDeliveryChannel`. The
  dispatcher and watch loop need no edits.
- `AnticipationEngine.predict` takes a `mode` parameter; the
  scheduler resolves `users.proactive_mode` and passes it through.
- `recall.check` is callable; the message-insert hook is the
  remaining wiring.
- `tests/newton/_schema_helpers.py` continues to derive expectations
  from disk; migration 010 needed no edits to earlier blocks' tests.

If `newton status` reports everything green and
`uv run pytest tests/newton/` shows 427 unit passes (plus 39 marker
tests with Docker up), block 5 is good to start.
