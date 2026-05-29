# Newton v4 — Block 7: Search + Analysis + OS Commands + Translation + Autoresearch

> Master plan: `newton-v4-master.md`
> Tech stack: `newton-v4-tech-stack.md`
> Engines (Provider matrix): `newton-v4-engines.md`
> Terminology: `TERMINOLOGY.md`
> Prerequisite: Block 6 complete (`v0.6.0-block6`, `docs/newton/block-6-summary.md`)
>
> **Goal:** Turn Newton from "knows my notes" into "knows the world."
> Web search, document analysis, video understanding, OS commands by
> voice, real-time translation, and autoresearch (Karpathy-style overnight
> agentic loops).

---

## 0. Block 7 — overall goals

The Provider Registry pattern from block 2 finally has *real providers*
to register. Five capability groups ship in this block:

1. **Web search** — SearXNG (default, self-hosted) + Brave / Tavily /
   Firecrawl (registered but dormant until sir activates)
2. **Document analysis** — MarkItDown for PDF / Word / Excel / PPT →
   markdown → main LLM
3. **Image analysis** — Qwen 2.5 VL (already loaded for block 6) wrapped
   as a tool
4. **Video analysis** — yt-dlp + Whisper + main LLM (multi-step
   pipeline)
5. **OS commands by voice** — pyautogui for file / app / system
   operations
6. **Real-time translation** — uses block 5 STT + main LLM + block 5 TTS
7. **Autoresearch** — `research.loop` capability: editable asset + single
   metric + time-box, scheduled by block 4 for overnight runs

### Locked decisions (entering Block 7)

| Item | Decision | Source |
|------|----------|--------|
| **Default web search provider** | SearXNG (free, self-hosted, no API key, no quota) | engines.md §1 |
| **Web search alternates** | Brave (paid), Tavily (free tier 1000/mo), Firecrawl (free tier 1000/mo) | engines.md §1 |
| **Document analysis** | MarkItDown (Microsoft, MIT) | engines.md §2 |
| **Image analysis** | Qwen 2.5 VL (already provisioned in block 6) | block 6 |
| **Video downloader** | yt-dlp (public domain) | engines.md §3 |
| **Video transcription** | re-use Whisper (block 5) | block 5 |
| **OS automation** | pyautogui (BSD) | engines.md §10 |
| **Translation routing** | sir's STT → main LLM (Qwen 2.5 32B is multilingual) → TTS in target language | jarvis-gap.md §3.9 |
| **Autoresearch design** | Karpathy pattern: editable asset + single scalar metric + time-boxed cycles | sir's earlier decision |
| **Autoresearch scheduler** | block 4 scheduler (night runs) | sir's earlier decision |
| **Autoresearch tool risk** | risk 2 (WRITE_LOCAL) since it writes files; sir approves once per loop start, not per cycle | this block |
| **OS command risk** | risk varies: launch app = 2, file delete = 4, system shutdown = 4 (block 2 approval policies apply) | block 2 pattern |

### Completion criteria (block as a whole)

```bash
# SearXNG running
$ uv run newton providers list | grep web.search
capability=web.search
  * active   searxng (free, unlimited, self-hosted)
            brave (paid, $5/mo, 0/1000 used)
            tavily (free_tier, 1000/mo, 0/1000 used)
            firecrawl (free_tier, 1000/mo, 0/1000 used)

# Web search via tool
$ uv run newton tools run web_search --args '{"query":"Qwen 2.5 release notes"}' \
    --user sir --persona jarvis
[ToolResult ok]
matches:
  - title: ...

# Document parsing
$ uv run newton tools run doc_parse --args '{"path":"~/Downloads/spec.pdf"}'
[markdown output]

# Image analysis
$ uv run newton tools run image_describe --args '{"path":"/tmp/photo.jpg"}'
[Vision LLM description]

# OS command (with approval)
$ uv run newton tools run os_open_app --args '{"app":"VS Code"}' --user sir --persona jarvis
[approval] os_open_app (risk: 2)
[sir: yes via voice]
[VS Code launches]

# Translation
$ uv run newton voice translate --from ja --to ko --listen 30
[sir's Japanese friend speaks for 30s]
[real-time Korean subtitles + optional TTS summary]

# Autoresearch
$ uv run newton autoresearch start \
    --asset email_draft.md \
    --metric tone_score \
    --iterations 100 \
    --time-box 5m
[approval] autoresearch start (risk: 2)
[sir: yes]
[scheduled for tonight; result tomorrow morning]

$ uv run newton autoresearch status
running 47/100, best score 8.2 so far, ETA 3h 12m

# Tests
$ uv run pytest tests/newton/ -v
# Blocks 1-6: ~388 + Block 7: ~110 = ~498 passed
```

After block 7, sir can ask Newton anything about the world, control the
desktop by voice, translate live conversations, and dispatch long
optimization tasks for overnight runs.

---

## 1. Block 7 — 12 steps

Each step: one focused change, one verification, one commit.
`ruff check` + `ruff format` clean before commit.

Estimated total: **20–28 days at sir's pace.** This is a wide block —
many capabilities, but each is a relatively contained provider
implementation.

---

### Step 7.1 — SearXNG self-host + provider (1.5 days)

**Goal:** Local SearXNG instance + Block 2 provider wrapper.

**Outputs:**

- `docker-compose.yml` — add SearXNG service
- `scripts/newton/searxng-up.sh`, `searxng-config.yaml`
- `newton/providers/builtin/searxng.py` — Provider for capability `web.search`
- `tests/newton/providers/test_searxng.py`

**Verification:**

```bash
docker compose up -d searxng
curl http://localhost:8080/search?q=test&format=json

uv run newton tools run web_search --args '{"query":"Newton AI"}'
# returns matches
```

**Risk:** SearXNG depends on upstream engines (Google, Bing, ...) which
may rate-limit. **Mitigation:** retry + alternate provider swap to Brave
if SearXNG keeps returning empty results.

**Commit:** `feat(providers): SearXNG self-hosted web.search`

---

### Step 7.2 — Alternate web.search providers (Brave / Tavily / Firecrawl) (1 day)

**Goal:** Register the alternates without activating them. Each becomes
hot-swappable via `newton providers swap`.

**Outputs:**

- `newton/providers/builtin/brave.py` — Brave Search API ($5/mo)
- `newton/providers/builtin/tavily.py` — Tavily (1000 free / mo)
- `newton/providers/builtin/firecrawl.py` — Firecrawl (1000 free / mo)
- `config/providers.yaml` — API key handling (sir adds keys when activating)
- Free quota tracking via `provider_usage` (block 2 table)
- `tests/newton/providers/test_alternate_search.py`

**Each provider:**

```python
class TavilyProvider(Provider):
    name = "tavily"
    capability = "web.search"
    cost_model = "free_tier"
    free_quota = 1000

    async def execute(self, request: WebSearchRequest) -> WebSearchResponse:
        # Tavily API call
        # Increments provider_usage row
        ...
```

**Verification:**

```bash
uv run newton providers list | grep web.search
# 4 providers listed; SearXNG active

uv run newton providers swap web.search tavily --permanent
# tavily now default

uv run newton providers swap web.search searxng --permanent
# back to free
```

**Commit:** `feat(providers): Brave/Tavily/Firecrawl web.search alternates`

---

### Step 7.3 — Document analysis provider (MarkItDown) (1 day)

**Goal:** PDF / Word / Excel / PPT → markdown → main LLM digest.

**Outputs:**

- `newton/providers/builtin/markitdown.py` — Provider for capability `doc.parse`
- `newton/tools/builtin/doc_parse.py` — tool wrapping the provider (risk 1)
- `tests/newton/tools/test_doc_parse.py`

**Dependencies:**

```bash
uv add markitdown
```

**Verification:**

```bash
echo "Test PDF content" > /tmp/test.txt
# (use a real PDF for actual testing)
uv run newton tools run doc_parse --args '{"path":"~/Downloads/sample.pdf"}'
# returns markdown text + structure
```

**Risk:** Scanned (image-based) PDFs are not parsed by MarkItDown.
**Mitigation:** documented limit; sir can run them through OCR first
(out of scope for block 7).

**Commit:** `feat(providers): MarkItDown doc.parse`

---

### Step 7.4 — Image analysis tool (1 day)

**Goal:** Tool wrapper around block 6's Vision LLM provider for
arbitrary image questions.

**Outputs:**

- `newton/tools/builtin/image_describe.py` — risk 1
- `newton/tools/builtin/image_qa.py` — risk 1, supports follow-up questions
- `tests/newton/tools/test_image_tools.py`

**Verification:**

```bash
uv run newton tools run image_describe --args '{"path":"/tmp/photo.jpg"}'
# "A photo of a laptop on a wooden desk with coffee cup."

uv run newton tools run image_qa --args \
    '{"path":"/tmp/photo.jpg","question":"What color is the coffee cup?"}'
# "The coffee cup is white with a small green logo."
```

**Commit:** `feat(tools): image_describe and image_qa tools`

---

### Step 7.5 — Video analysis pipeline (1.5 days)

**Goal:** Download video → extract audio → Whisper transcribe → main
LLM summarize.

**Outputs:**

- `newton/providers/builtin/yt_dlp.py` — Provider for capability `video.download`
- `newton/tools/builtin/video_summarize.py` — multi-step tool: download → transcribe → summarize
- `tests/newton/tools/test_video.py`

**Dependencies:**

```bash
uv add yt-dlp
```

**Tool behaviour:**

```
input: YouTube URL or local video path
    ↓
yt-dlp downloads (or skip if local) → /tmp/video-<hash>.mp4
    ↓
ffmpeg extracts audio → /tmp/audio-<hash>.wav
    ↓
Whisper transcribes (block 5)
    ↓
main LLM summarizes (with optional keyframe Vision LLM pass)
    ↓
saved to data/vault/_auto/videos/<title>.md (ACL: sir)
returns summary + saved-path
```

**Risk levels:**

- `video_download` — risk 3 (READ_NETWORK), default require_approval
- `video_summarize` — risk 3 (combines download + processing)

**Verification:**

```bash
uv run newton tools run video_summarize --args \
    '{"url":"https://www.youtube.com/watch?v=..."}' \
    --user sir --persona jarvis
# downloads, transcribes, summarizes
# saves to data/vault/_auto/videos/<title>.md
```

**Risk:** Large videos can take 10+ min to transcribe. **Mitigation:**
async; status check command (`newton tools status <task_id>`).

**Commit:** `feat(tools): video summarization pipeline`

---

### Step 7.6 — OS commands (file / app) (1.5 days)

**Goal:** Voice-controllable file and application operations via
pyautogui.

**Outputs:**

- `newton/tools/builtin/os_open_app.py` — risk 2, launches app
- `newton/tools/builtin/os_close_app.py` — risk 2
- `newton/tools/builtin/os_focus_app.py` — risk 1
- `newton/tools/builtin/os_file_open.py` — risk 2, opens file in default app
- `newton/tools/builtin/os_file_find.py` — risk 1, searches paths
- `newton/tools/builtin/os_file_move.py` — risk 2, moves a file
- `newton/tools/builtin/os_file_delete.py` — risk 3 (WRITE intent + irreversibility), always require_approval
- `tests/newton/tools/test_os_tools.py`

**Dependencies:**

```bash
uv add pyautogui
```

**Safety:**

- App lists / file paths are validated against an allowlist initially
  (sir's home, Downloads, Documents). Configurable.
- Delete operations move to trash, never `unlink()` directly (use
  `send2trash`).
- Approval prompts include the *exact* file path or app name.

**Verification:**

```bash
uv run newton tools run os_open_app --args '{"app":"VS Code"}' \
    --user sir --persona jarvis --auto-yes
# VS Code launches

uv run newton tools run os_file_find --args '{"query":"newton","path":"~/newton-v4/"}' \
    --user sir --persona jarvis
# returns matching files

uv run newton tools run os_file_delete --args '{"path":"/tmp/test.txt"}' \
    --user sir --persona jarvis --auto-yes
# sent to trash; recoverable
```

**Commit:** `feat(tools): OS commands (open/close/focus apps + file ops)`

---

### Step 7.7 — System diagnostics + cleanup tools (1 day)

**Goal:** Voice-controllable system maintenance.

**Outputs:**

- `newton/tools/builtin/os_system_status.py` — risk 1, comprehensive status
- `newton/tools/builtin/os_cleanup_temp.py` — risk 2, /tmp + browser cache cleanup
- `newton/tools/builtin/os_update_check.py` — risk 3 (READ_NETWORK), checks system updates
- `newton/tools/builtin/os_shutdown.py` — risk 4, immediate or delayed shutdown (always require_approval)
- `tests/newton/tools/test_os_diagnostics.py`

**Verification:**

```bash
uv run newton tools run os_system_status
# CPU 12% / GPU 5% / disk 67% / battery N/A (desktop)

uv run newton tools run os_cleanup_temp --args '{"older_than_days":7}' \
    --user sir --persona jarvis --auto-yes
# frees X GB
```

**Commit:** `feat(tools): system diagnostics and cleanup tools`

---

### Step 7.8 — Real-time translation (1.5 days)

**Goal:** Live conversation translation, document translation.

**Outputs:**

- `newton/translate/__init__.py`
- `newton/translate/realtime.py` — STT → main LLM (translate) → TTS in target language
- `newton/translate/document.py` — file → MarkItDown → main LLM → translated markdown
- `newton/cli.py` — `newton voice translate --from X --to Y [--listen N]`
- `newton/tools/builtin/translate_text.py` — risk 0 (no IO)
- `newton/tools/builtin/translate_document.py` — risk 2
- `tests/newton/translate/test_translation.py`

**Language pairs (Qwen 2.5 multilingual coverage):**

```
ko ↔ en, ja, zh, es, fr, de, ru, ...
auto-detect input language if `--from auto`
```

**Real-time meeting flow:**

```
Block 5 voice meeting mode is on
    ↓
incoming audio (foreign speaker)
    ↓
Whisper STT with --language flag
    ↓
main LLM: "Translate to {target_lang} preserving meaning and tone"
    ↓
optional: TTS in target language for sir
optional: HUD subtitle (block 11)
optional: save full transcript + translation to meeting note
```

**Verification:**

```bash
# Translate text immediately
uv run newton tools run translate_text --args '{"text":"こんにちは","from":"ja","to":"ko"}'
# "안녕하세요"

# Translate a document
uv run newton tools run translate_document --args \
    '{"path":"~/Downloads/spec.pdf","to":"ko"}' \
    --user sir --persona jarvis --auto-yes
# saves translated markdown to data/vault/_auto/translations/

# Real-time (in meeting mode)
uv run newton voice meeting start --translate-from ja --translate-to ko
# Japanese speech transcribed + translated in real-time
```

**Commit:** `feat(translate): real-time + document translation`

---

### Step 7.9 — Autoresearch foundation (2 days)

**Goal:** Karpathy-style agentic loop. Editable asset + single metric +
time-boxed cycles.

**Outputs:**

- `migrations/011_autoresearch.sql` — `autoresearch_jobs`, `autoresearch_cycles` tables
- `newton/autoresearch/__init__.py`
- `newton/autoresearch/job.py`
  - `class AutoResearchJob` — orchestrator
  - asset file (sir-owned, single editable file)
  - metric function (LLM-rubric or computable)
  - time-box per cycle
  - iteration count or stop condition
- `newton/autoresearch/runner.py` — runs one cycle
- `newton/autoresearch/metrics.py` — pluggable metric implementations
- `newton/tools/builtin/autoresearch_start.py` — risk 2
- `newton/cli.py` — `newton autoresearch start/status/stop/result`
- `tests/newton/autoresearch/test_job.py`

**Schema:**

```sql
CREATE TABLE autoresearch_jobs (
    job_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT NOT NULL,
    asset_path        TEXT NOT NULL,        -- editable file relative to vault
    metric_name       TEXT NOT NULL,        -- 'tone_score', 'test_pass_rate', etc.
    metric_config_json TEXT,                -- rubric details
    iterations_target INTEGER NOT NULL,
    cycle_time_box_sec INTEGER NOT NULL,
    status            TEXT NOT NULL,        -- 'scheduled' / 'running' / 'paused' / 'complete' / 'aborted'
    started_at        TIMESTAMP,
    completed_at      TIMESTAMP,
    best_score        REAL,
    best_cycle_id     INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE autoresearch_cycles (
    cycle_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id            INTEGER NOT NULL,
    iteration         INTEGER NOT NULL,
    asset_snapshot    TEXT NOT NULL,        -- the file content tried this cycle
    score             REAL,
    keep_or_discard   TEXT,                 -- 'keep' / 'discard'
    duration_sec      REAL,
    started_at        TIMESTAMP,
    completed_at      TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES autoresearch_jobs(job_id) ON DELETE CASCADE
);
```

**Metric plug-ins (initial set):**

- `tone_score` — LLM rubric: "rate this email's friendliness 0–10"
- `test_pass_rate` — runs `pytest` on a code asset, returns pass ratio
- `length_target` — closer to a target token count = higher score
- `custom_llm_rubric` — sir provides a rubric prompt

**Cycle flow:**

```
[start of cycle]
    ↓
current_best = read(asset_path)
    ↓
mutation_prompt = "Suggest a variation of this asset to improve {metric}"
    ↓
candidate = main LLM produces variation (in cycle_time_box_sec)
    ↓
score = metric.evaluate(candidate)
    ↓
score > current_best_score?
   yes → write candidate to asset_path; record as keep
    no → discard
    ↓
log cycle in autoresearch_cycles
    ↓
[next cycle]
```

**Verification:**

```bash
echo "Hello team, I think we should reconsider this approach." > /tmp/email.md

uv run newton autoresearch start \
    --asset /tmp/email.md \
    --metric tone_score \
    --rubric "friendly but professional, 0-10" \
    --iterations 20 \
    --time-box 30s \
    --user sir
# requires approval (risk 2)

# After it runs:
uv run newton autoresearch status
# 20/20 complete, best 8.7, 6 keep, 14 discard

uv run newton autoresearch result <job_id>
# shows best version + diff vs original
```

**Risk:** Cost — every cycle is an LLM call (~1 sec of GPU). 100 cycles
= ~2 min of GPU + electricity. Negligible for local; non-trivial if
sir ever runs on cloud.

**Commit:** `feat(autoresearch): foundation with editable asset + metric + cycles`

---

### Step 7.10 — Autoresearch scheduling via Block 4 (1 day)

**Goal:** Hook autoresearch into Block 4 scheduler so jobs run overnight
during sir's idle hours.

**Outputs:**

- `newton/autoresearch/scheduler.py`
  - integrates with `newton/proactive/scheduler.py`
  - runs jobs during quiet_hours (default 23:00–07:00)
  - or on sir's explicit "go now"
- `newton/proactive/scheduler.py` — extended to know about autoresearch jobs
- `tests/newton/autoresearch/test_scheduling.py`

**Behaviour:**

```
sir: starts autoresearch job at 22:00 with "schedule for tonight"
    ↓
job status: scheduled, target_start: tomorrow 00:00 (if quiet hours start at 23:00 + 1h margin)
    ↓
block 4 scheduler tick at 23:30 → quiet hours active + jobs pending → start job
    ↓
job runs in background (block 4 daemon hosts it)
    ↓
sir wakes up
    ↓
block 4 proactive announces:
  "Sir, your autoresearch job completed. 100/100 cycles, best score 9.4.
   Want to see the result?"
```

**Verification:**

```bash
uv run newton autoresearch start \
    --asset /tmp/draft.md \
    --metric tone_score \
    --iterations 100 \
    --time-box 30s \
    --schedule overnight
# scheduled

uv run newton autoresearch list
# 1 pending job, eta tonight 23:30

# Simulate time advance for testing
uv run newton proactive tick --simulate-time "23:30"
# job starts

uv run newton autoresearch status <job_id>
# running, 47/100, best 8.2
```

**Commit:** `feat(autoresearch): scheduled overnight runs via Block 4`

---

### Step 7.11 — Tool: autoresearch_propose for LLM-driven start (1 day)

**Goal:** Let JARVIS / Friday propose autoresearch jobs based on sir's
conversation, with sir's approval.

**Outputs:**

- `newton/tools/builtin/autoresearch_propose.py` — risk 2
- Tool description guides LLM to use it for:
  - "tweak this email until it sounds perfect"
  - "improve this function's performance"
  - "find the best wording for this pitch"
- `tests/newton/tools/test_autoresearch_propose.py`

**Tool flow:**

```
sir: "JARVIS, this email isn't quite right — try variations overnight"
    ↓
JARVIS chooses tool autoresearch_propose with args:
  asset_path: <current draft>
  metric: tone_score
  iterations: 100
  time_box: 30s
    ↓
[approval hook fires — risk 2]
sir: "yes, go" (via voice channel — block 5)
    ↓
job created, scheduled for tonight
    ↓
JARVIS confirms: "Sir, scheduled. Results in the morning."
```

**Verification:**

```bash
# Manual test of the LLM-orchestrated flow
# (Requires full block 1-7 stack running)

# Or unit test the tool directly:
uv run pytest tests/newton/tools/test_autoresearch_propose.py -v
```

**Commit:** `feat(tools): autoresearch_propose for LLM-driven workflow`

---

### Step 7.12 — Block 7 summary + tag (1–2 hours)

**Goal:** Lock the block.

**Outputs:**

- `docs/newton/block-7-summary.md`
- `docs/newton/cli.md` — final pass
- `README.md` — Block 7 marked complete
- Git tag: `v0.7.0-block7`

**Block 8 entry conditions (provisional):**

- All Web search providers registered (SearXNG default + 3 alternates)
- doc_parse / image / video tools work
- OS command tools work with approval hook
- Real-time translation works
- Autoresearch end-to-end (manual + scheduled)
- LLM can propose autoresearch via tool
- All pytest cases pass (~498 total)
- Preflight 9/9 still ✓
- OpenJarvis: still 0 files modified

**Commit + tag:** `chore: block 7 complete`

---

## 2. Deliberately not in Block 7

- ❌ **Gesture-driven OS commands** — block 8 (uses block 7 tools but triggered by gesture)
- ❌ **Email / messenger sending** — block 9
- ❌ **Calendar manipulation** — block 9
- ❌ **Smart home control** — block 9
- ❌ **Persistent web crawling jobs** — out of scope
- ❌ **Cloud LLM fallback when local is overloaded** — local-only principle holds
- ❌ **Custom autoresearch metric authoring UI** — config-file-based for now

---

## 3. Risk matrix

| Risk | Impact | Mitigation |
|------|--------|-----------|
| SearXNG upstream blocked / rate-limited | Med | Fallback to Brave; tested in step 7.1 |
| Brave / Tavily / Firecrawl API keys leaked into git | High | `.gitignore` for config/providers.yaml; documented |
| MarkItDown fails on scanned PDFs | Med | Document the limit; OCR is out of scope |
| Vision LLM swap conflicts with main LLM during video summarization | Med | Sequence operations; never run both at once |
| pyautogui delete = data loss | High | send2trash, never unlink; require_approval at risk 3 |
| OS commands launched on wrong window (focus race) | Med | Verify window focus before action; small sleep |
| Translation quality bad on rare language pairs | Low | Document Qwen 2.5 supported set |
| Autoresearch infinite loops or runaway cost | High | Iteration cap + time-box per cycle + total time cap |
| Autoresearch overwrites a file sir is still editing | High | Lock asset_path while job runs; sir warned at start |
| Provider Registry race conditions during hot-swap | Med | swap operations are atomic via single transaction |
| 20–28 day estimate optimistic | Med | Mid-block re-estimate after step 7.5 |

---

## 4. After Block 7 — opening message for the next chat

```markdown
# Newton v4 — Block 8 start (Motion + Gesture + UI control)

## Context
- Newton: multi-persona AI OS, OpenJarvis fork
- Environment: RTX 5090 + WSL2 Ubuntu + systemd
- Location: ~/newton-v4/

## Design docs
[newton-v4-master.md]
[newton-v4-tech-stack.md]
[newton-v4-gestures.md]   # block 8 17-step decomposition
[newton-v4-engines.md]
[newton-v4-block-7.md]    # complete
[newton-v4-block-8.md]    # this block
[TERMINOLOGY.md]

## Blocks 1–7 result
- v0.7.0-block7: search + analysis + OS + translation + autoresearch
  - 4 web.search providers; SearXNG default
  - MarkItDown doc.parse
  - Image / video analysis
  - OS commands (open / close / file ops) with approval
  - Real-time translation in meeting mode
  - Autoresearch overnight runs via Block 4

## Next
Block 8 step 8.1 — MediaPipe Hand integration.
```

---

## 5. Honest reality check

**Time estimate:** **20–28 days at sir's pace.** Block 7 is the *widest*
block — many providers, each independent. Linear effort scales.

**Riskiest steps:**

- **Step 7.6** (OS commands) — file system actions are easy to break
- **Step 7.9** (autoresearch) — new concept; correctness of the
  optimization loop matters
- **Step 7.11** (LLM-driven autoresearch) — requires solid prompt
  engineering for tool description

**Simplest steps:**

- 7.1, 7.2, 7.3, 7.4 — provider wrappers around stable libraries

**Most important step:**

- **Step 7.9** (autoresearch). This is *Newton's leverage moment* —
  sir gives Newton a task and goes to sleep. Future Newton value will
  multiply if this works well.

**Behavioural shift:**

After block 7, sir's interaction with Newton stops being only synchronous.
Long-running tasks (overnight autoresearch, multi-video summarization)
free sir to do other things. Newton becomes a *background agent*, not
just a chatbot.

**Assets carried over:**

- Block 2 ProviderRegistry → now full of real providers
- Block 2 tool approval → applies to every new tool
- Block 4 scheduler → hosts autoresearch overnight runs
- Block 4 DeliveryChannel → notifies sir when autoresearch completes
- Block 5 STT + TTS → drives translation pipeline
- Block 6 Vision LLM → image / video tools
- ~388 pytest cases must still pass

---

## 6. Starting checklist

Before Block 7 begins:

- [ ] Block 6 tagged `v0.6.0-block6`, `newton status` green
- [ ] Pytest ~388 passing
- [ ] Docker Desktop running (SearXNG container)
- [ ] At least one alternate web.search API key obtained (optional;
      SearXNG works without)
- [ ] `pyautogui` install successful (display server available — X11 or
      WSLg)
- [ ] `yt-dlp` installable
- [ ] `markitdown` installable
- [ ] At least 20 GB free disk (autoresearch cycle snapshots)
- [ ] sir has 4–6 weeks of focused work

---

Ready when sir is. Step 7.1 is the entry point.
