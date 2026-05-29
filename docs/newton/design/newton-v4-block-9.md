# Newton v4 — Block 9: Communication + Calendar + Smart Home

> Master plan: `newton-v4-master.md`
> Tech stack: `newton-v4-tech-stack.md`
> Engines (Provider matrix): `newton-v4-engines.md`
> Terminology: `TERMINOLOGY.md`
> Prerequisite: Block 8 complete (`v0.8.0-block8`, `docs/newton/block-8-summary.md`)
>
> **Goal:** Newton reaches into sir's life outside the desk —
> email, messengers, calendar, home devices. Every outbound action
> requires explicit approval. KakaoTalk handled with realistic constraints.

---

## 0. Block 9 — overall goals

Three capability groups land here:

1. **Communication** — Gmail, Outlook, Slack, Discord, Telegram, KakaoTalk
   (with constraints). Read-only by default; sending always gated by
   the approval hook (Block 2).
2. **Calendar** — Google Calendar, Outlook, CalDAV via MCP. Read + write
   (with approval). Proactive alerts (Block 4 scheduler integration).
3. **Smart home** — Home Assistant as the standard hub. Lights, climate,
   security, media control. Routine automation via Block 4 patterns.

This block is where Newton stops being a desktop tool and becomes a
household assistant.

### Locked decisions (entering Block 9)

| Item | Decision | Source |
|------|----------|--------|
| **Email read** | Gmail API (OAuth), Outlook (Microsoft Graph), IMAP fallback | engines.md §13 |
| **Email send** | risk 4 (WRITE_NETWORK) — always require_approval | block 2 default |
| **Slack / Discord / Telegram** | official APIs / bot tokens; sir's accounts | engines.md §13 |
| **KakaoTalk** | Yellow ID business account *or* read-only (Notification Listener) — sir picks per use case | engines.md §13 |
| **Calendar protocol** | MCP servers (google_calendar, outlook, caldav) | jarvis-gap.md §3.5 |
| **Smart home hub** | Home Assistant (Apache 2.0) | jarvis-gap.md §3.6 |
| **Approval channel for outbound** | `VoiceApprovalChannel` (Block 5) preferred; CLI fallback | block 5 |
| **Calendar caching** | `calendar_events` table (block 1 schema) | block 1 |
| **Cross-provider deduplication** | each event has `(source, external_id)` unique key | this block |
| **Smart home automation risk** | risk 2 (WRITE_LOCAL) — physical action requires approval; sir can set always-allow per device | this block |
| **Quiet hours apply to smart home automation** | yes — no light changes during 23:00–07:00 unless sir overrides | block 4 |

### Completion criteria (block as a whole)

```bash
# Email
$ uv run newton tools run email_list --args '{"folder":"inbox","limit":5}' --user sir
[5 recent emails returned with subject + sender + snippet]

$ uv run newton tools run email_send --args '{"to":"team@example.com","subject":"hello","body":"..."}' \
    --user sir --persona jarvis
[approval] email_send (risk: 4) -> require_approval
[voice] "Sir, send this email to team@example.com? Subject: hello."
[sir: yes]
[email sent]

# Calendar
$ uv run newton calendar events --next 7
[7 days of upcoming events from all configured providers]

$ uv run newton tools run calendar_add --args \
    '{"title":"Newton review","start":"2026-08-15T14:00","duration":60,"location":"home"}' \
    --user sir --persona jarvis
[approval] calendar_add (risk: 3) -> ...
[event created]

# Smart home
$ uv run newton home devices list
- light.living_room (on)
- light.bedroom (off)
- thermostat.main (22.5°C, target 23.0)

$ uv run newton home set light.living_room --state on --brightness 60
[approval if not in always-allow] -> physical action

# Routines via Block 4 patterns
$ uv run newton home routines list
- morning_routine: sir wake detected → lights 50%, no music
- evening_routine: 19:00 → warm lighting, dim
- away_mode: sir absence >2h → energy save

# Tests
$ uv run pytest tests/newton/ -v
# Blocks 1-8: ~593 + Block 9: ~115 = ~708 passed
```

After Block 9, Newton sees sir's inbox, manages sir's calendar, controls
sir's home — all under sir's explicit approval for outbound or physical
actions.

---

## 1. Block 9 — 13 steps

Each step: one focused change, one verification, one commit.
`ruff check` + `ruff format` clean before commit.

Estimated total: **18–25 days at sir's pace.** Wider than block 8 in
*surface area* (many third-party integrations) but each integration is
relatively small.

---

### Step 9.1 — Gmail OAuth + read-only (1.5 days)

**Goal:** sir authenticates Newton with Gmail. Read inbox, list folders,
get messages. No send yet.

**Outputs:**

- `newton/comms/gmail.py` — Gmail API wrapper
- `config/credentials/` directory (gitignored)
- `newton/cli.py` — `newton comms gmail auth`, `newton comms gmail status`
- `newton/tools/builtin/email_list.py` — risk 1
- `newton/tools/builtin/email_show.py` — risk 1
- `newton/tools/builtin/email_search.py` — risk 1
- `tests/newton/comms/test_gmail.py`

**Dependencies:**

```bash
uv add google-auth-oauthlib google-api-python-client
```

**Auth flow:**

```
sir runs: newton comms gmail auth
    ↓
browser opens OAuth consent
    ↓
sir grants Gmail read-only scope
    ↓
refresh token saved to config/credentials/gmail-<user_id>.json (0600 perms, gitignored)
    ↓
status verified
```

**Verification:**

```bash
uv run newton comms gmail auth
uv run newton comms gmail status   # connected, scope: gmail.readonly

uv run newton tools run email_list --args '{"folder":"inbox","limit":5}' --user sir
# 5 emails returned
```

**Risk:** OAuth token theft. **Mitigation:** file perms 0600, gitignore,
documented. Refresh tokens, never long-lived access tokens.

**Commit:** `feat(comms): Gmail OAuth read-only`

---

### Step 9.2 — Gmail send + approval flow (1 day)

**Goal:** Add `gmail.send` scope. Wire send through approval hook.

**Outputs:**

- Extend `newton/comms/gmail.py` with send capability
- `newton/tools/builtin/email_send.py` — risk 4 (WRITE_NETWORK)
- `newton/tools/builtin/email_reply.py` — risk 4
- `tests/newton/tools/test_email_send.py`

**Send flow:**

```
JARVIS proposes: email_send(to, subject, body, cc, bcc)
    ↓
ToolRegistry.dispatch → approval hook
    ↓
risk 4 → require_approval (default)
    ↓
VoiceApprovalChannel.request_approval:
    JARVIS speaks: "Sir, send email to <to>? Subject: <subject>."
    ↓
sir: yes / no
    ↓
yes → gmail.send → log success
no  → ToolResult(denied)
```

**Per-recipient always-allow (optional, sir's choice):**

`tool_policies` row: `email_send` for tool_name + persona_id=jarvis +
user_id=sir → require_approval (default). sir can override per-recipient
later by adding policy rows.

**Verification:**

```bash
uv run newton tools run email_send --args \
    '{"to":"me@example.com","subject":"test","body":"hi"}' \
    --user sir --persona jarvis --channel voice
# voice prompt; sir answers; sent
```

**Commit:** `feat(comms): Gmail send with approval hook`

---

### Step 9.3 — Outlook integration (1 day)

**Goal:** Microsoft Graph for Outlook accounts. Same read/send pattern.

**Outputs:**

- `newton/comms/outlook.py`
- email_list / email_send tools support `--provider outlook`
- `tests/newton/comms/test_outlook.py`

**Dependencies:**

```bash
uv add msal
```

**Verification:**

```bash
uv run newton comms outlook auth
uv run newton tools run email_list --args '{"provider":"outlook","folder":"inbox","limit":5}'
```

**Commit:** `feat(comms): Outlook Microsoft Graph integration`

---

### Step 9.4 — Slack + Discord + Telegram (1.5 days)

**Goal:** Three more messaging providers, each with read + send capability.

**Outputs:**

- `newton/comms/slack.py` — Slack Web API (bot token)
- `newton/comms/discord.py` — discord.py (bot token)
- `newton/comms/telegram.py` — python-telegram-bot (bot token)
- Tools:
  - `msg_list` (read) — risk 1
  - `msg_send` — risk 4 (WRITE_NETWORK)
  - `msg_search` — risk 1
- `tests/newton/comms/test_messengers.py`

**Dependencies:**

```bash
uv add slack-sdk discord.py python-telegram-bot
```

**Each provider takes a config block:**

```yaml
# config/providers.yaml
slack:
  bot_token: "${SLACK_BOT_TOKEN}"     # from env
  default_channel: "general"
discord:
  bot_token: "${DISCORD_BOT_TOKEN}"
  default_channel: "general"
telegram:
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  default_chat_id: 123456789
```

**Verification:**

```bash
export SLACK_BOT_TOKEN=xoxb-...
uv run newton tools run msg_send --args \
    '{"provider":"slack","channel":"#general","text":"test"}' \
    --user sir --persona jarvis --auto-yes
# message sent to slack
```

**Commit:** `feat(comms): Slack + Discord + Telegram integrations`

---

### Step 9.5 — KakaoTalk Yellow ID / read-only (1.5 days)

**Goal:** KakaoTalk has unusual restrictions vs other messengers. Two
modes; sir picks per use case.

**Background (engines.md §13):**

Kakao does NOT provide a general-purpose Send-As-User API for personal
accounts. Automating sends from sir's personal account violates TOS and
risks ban. Two legitimate paths:

- **Yellow ID (비즈니스 채널)** — official business channel. sir
  registers a business account; Kakao approves; sir can send notifications
  to subscribed users. *Outbound only, no two-way DM.*
- **Read-only via Notification Listener** — on sir's Android phone,
  Newton's companion app reads incoming KakaoTalk notifications (with
  sir's permission). *No send capability.*

**Outputs:**

- `newton/comms/kakao_yellow.py` — Yellow ID send
- `newton/comms/kakao_readonly.py` — receive-only via local notification stream (requires Android companion app, stub for now)
- Tools:
  - `kakao_send` (Yellow ID only) — risk 4
  - `kakao_list_recent` (read-only) — risk 1
- Docs: `docs/newton/kakaotalk-constraints.md` explaining limits
- `tests/newton/comms/test_kakao.py`

**Verification:**

```bash
# Yellow ID outbound (assumes Kakao business account registered)
uv run newton tools run kakao_send --args \
    '{"to":"subscriber_id_xyz","template":"hello"}' \
    --user sir --persona jarvis
# Yellow ID send; sir approves

# Read-only (assumes Android companion installed and sync running)
uv run newton tools run kakao_list_recent --args '{"limit":10}'
# 10 recent inbound notifications
```

**Risk:** Kakao policy changes. **Mitigation:** documented limits;
sir warned that personal-account sending is *not* supported.

**Commit:** `feat(comms): KakaoTalk Yellow ID + read-only modes`

---

### Step 9.6 — Communication tools tied to Proactive Engine (1 day)

**Goal:** Block 4 patterns can use comms tools for proactive notifications
(e.g. "urgent email from boss → notify sir").

**Outputs:**

- `newton/comms/proactive_hooks.py`
  - on-receive hooks for Gmail, Slack, etc. that the daemon polls
  - urgency detection (sender, subject keywords) feeds Block 4 scheduler
- `tests/newton/comms/test_proactive_comms.py`

**Pattern examples that Block 4 can now learn:**

```
context: "incoming email from <known_VIP> with 'urgent' or 'asap' in subject"
→ action: VoiceDeliveryChannel notification — "Sir, urgent email from <VIP>"

context: "Slack mention while sir is focused (block 4 emotion + Block 8 long-coding session)"
→ action: queue notification, deliver at next natural break (e.g. when focus pattern breaks)
```

**Verification:**

```bash
# Simulate inbound email from VIP
# (test mode sends a synthetic email event)
uv run newton comms simulate-inbound \
    --provider gmail \
    --from boss@company.com \
    --subject "URGENT: please reply"

# Block 4 should pick this up via context update
# Notification fires via VoiceDeliveryChannel
```

**Commit:** `feat(comms): proactive hooks for inbound urgency detection`

---

### Step 9.7 — Calendar foundation: Google Calendar via MCP (1.5 days)

**Goal:** Hook into sir's Google Calendar. Read events, add events,
move events, cancel events.

**Outputs:**

- `newton/calendar/google.py` — Google Calendar API wrapper (reuses Gmail OAuth refresh token where possible, but separate scope)
- Tools:
  - `calendar_events` — risk 1 (read)
  - `calendar_add` — risk 3 (WRITE_NETWORK, but lower than email because only sir's own calendar)
  - `calendar_move` — risk 3
  - `calendar_cancel` — risk 3
- Cache: writes/updates `calendar_events` table (block 1 schema)
- `newton/cli.py` — `newton calendar events --next 7`, `newton calendar sync`
- `tests/newton/calendar/test_google.py`

**Cache strategy:**

```
periodic sync (every 5 min via Block 4 daemon):
    fetch events from last_sync_at to now+30d
    upsert into calendar_events table
        key: (source='google', external_id)
```

**Verification:**

```bash
uv run newton calendar sync
# events synced from Google
uv run newton calendar events --next 7
# 7 days of events listed from cache

uv run newton tools run calendar_add --args \
    '{"title":"Newton review","start":"2026-08-15T14:00","duration":60}' \
    --user sir --persona jarvis --auto-yes
# event created on Google + cache updated
```

**Commit:** `feat(calendar): Google Calendar via MCP-style adapter`

---

### Step 9.8 — Outlook + CalDAV calendar (1 day)

**Goal:** Two more calendar sources. Same tools accept `--source` arg.

**Outputs:**

- `newton/calendar/outlook.py` — Microsoft Graph events
- `newton/calendar/caldav.py` — generic CalDAV (Apple Calendar, Naver Calendar, etc.)
- Multi-source sync orchestrator
- `tests/newton/calendar/test_outlook_caldav.py`

**Dependencies:**

```bash
uv add caldav
```

**Verification:**

```bash
uv run newton calendar add-source outlook
uv run newton calendar add-source caldav --url https://caldav.example.com
uv run newton calendar sync
# events from all 3 sources merged in calendar_events
```

**Commit:** `feat(calendar): Outlook + CalDAV support`

---

### Step 9.9 — Calendar proactive alerts (Block 4 integration) (1 day)

**Goal:** Block 4 scheduler reads `calendar_events`, fires
"meeting in 10 minutes" alerts.

**Outputs:**

- `newton/calendar/proactive.py`
  - registers calendar-derived patterns with Block 4
  - default trigger windows: 60 min before, 15 min before, 5 min before
  - configurable per event (e.g. travel-time aware)
- `tests/newton/calendar/test_proactive.py`

**Pattern examples auto-generated:**

```
pattern: "10 min before any meeting in calendar_events"
→ proactive notification via VoiceDeliveryChannel
   "Sir, meeting '{title}' starts in 10 minutes."
```

**Conflict detection:**

```
2 events overlap?
→ proactive notification: "Sir, conflict detected. Meeting A at 14:00 overlaps with Meeting B at 14:30."
```

**Travel-time warning:**

```
event has location set + sir's current location (from ambient awareness or geo)?
→ proactive notification 30 min before: "Sir, leave in 15 min to reach Meeting at <location>."
```

**Verification:**

```bash
# With a meeting at 14:00 in the cache:
# At 13:50, proactive notification fires via voice channel
```

**Commit:** `feat(calendar): proactive alerts wired to Block 4`

---

### Step 9.10 — Home Assistant integration (1.5 days)

**Goal:** Connect to sir's Home Assistant instance. Read device states,
control devices.

**Outputs:**

- `newton/home/hass.py` — Home Assistant REST API + WebSocket client
- Tools:
  - `home_devices_list` — risk 1
  - `home_device_state` — risk 1
  - `home_device_set` — risk 2 (WRITE_LOCAL, physical action) — default require_approval
  - `home_scene_activate` — risk 2
- `newton/cli.py` — `newton home devices list`, `newton home set <entity> <state>`
- `tests/newton/home/test_hass.py`

**Dependencies:**

```bash
uv add httpx websocket-client
```

**Config:**

```yaml
home_assistant:
  url: "http://192.168.1.100:8123"
  token: "${HASS_LONG_LIVED_TOKEN}"
```

**Per-device always-allow (sir can set):**

```bash
uv run newton tools policy set home_device_set \
    --user sir --persona jarvis \
    --filter '{"entity":"light.living_room"}' \
    --decision auto_allow
# living room light: no approval prompt
```

**Verification:**

```bash
uv run newton home devices list
# all entities + states

uv run newton tools run home_device_set --args \
    '{"entity":"light.living_room","state":"on","brightness":60}' \
    --user sir --persona jarvis
# approval (unless always-allow set)
# light changes
```

**Risk:** Home Assistant URL exposes home network. **Mitigation:**
local-network only; LAN-only API; if VPN, tunneled.

**Commit:** `feat(home): Home Assistant integration`

---

### Step 9.11 — Smart home routines via Block 4 patterns (1.5 days)

**Goal:** Automated routines triggered by Block 4 context patterns,
gated by quiet hours.

**Outputs:**

- `newton/home/routines.py`
  - `morning_routine`: sir wake detected → lights 50% warm
  - `evening_routine`: 19:00 (configurable) → warm lighting + dim
  - `away_mode`: sir absence > 2h → energy save (turn off non-essential)
  - `bedtime_routine`: quiet_hours start → all lights off
- Block 4 pattern definitions for above
- `newton/cli.py` — `newton home routines list/enable/disable`
- `tests/newton/home/test_routines.py`

**Routine engine:**

```
each routine has:
  - trigger: pattern reference (block 4)
  - condition: optional (e.g. only if mode != off)
  - actions: list of (tool, args) pairs
    each action goes through Block 2 dispatch + approval hook
    (auto_allow if device on always-allow list)
```

**Verification:**

```bash
uv run newton home routines enable morning_routine
# routine wired

# Simulate sir wake (face detection + time > 06:00)
# routine fires:
# - light.bedroom → on, brightness 30
# - light.living_room → on, brightness 50
# (with approvals or auto_allow per device)
```

**Commit:** `feat(home): proactive routines via Block 4 patterns`

---

### Step 9.12 — Cross-channel notification consolidation (1 day)

**Goal:** When the same event triggers notifications across calendar +
email + Slack, deliver one consolidated message instead of three.

**Outputs:**

- `newton/comms/consolidation.py` — dedup logic
- Time-window: events within 5 minutes considered "same context"
- `tests/newton/comms/test_consolidation.py`

**Example:**

```
3 events fire within 2 minutes:
- calendar: "meeting in 10 minutes"
- email: "agenda from organizer"
- slack: "@here, meeting starting soon"
    ↓
consolidator picks the highest-information one:
    "Sir, your meeting starts in 10 minutes. Email from organizer with
     agenda has arrived. Slack channel is gathering."
```

**Verification:**

```bash
# Synthetic test
uv run newton comms test-consolidation --simulate-burst
# 3 notifications consolidated into 1
```

**Commit:** `feat(comms): cross-channel notification consolidation`

---

### Step 9.13 — Block 9 summary + tag (half-day)

**Goal:** Lock the block.

**Outputs:**

- `docs/newton/block-9-summary.md`
- `docs/newton/cli.md` — final pass
- `README.md` — Block 9 marked complete
- Git tag: `v0.9.0-block9`

**Block 10 entry conditions (provisional):**

- Gmail, Outlook, Slack, Discord, Telegram work (read + send with approval)
- KakaoTalk Yellow ID + read-only modes documented and working (or stubbed if not yet usable)
- Calendar from Google + Outlook + CalDAV
- Home Assistant device control
- Proactive calendar alerts via Block 4
- Smart home routines automated
- Cross-channel consolidation prevents notification storms
- All pytest cases pass (~708 total)
- Preflight 9/9 still ✓
- OpenJarvis: still 0 files modified

**Commit + tag:** `chore: block 9 complete`

---

## 2. Deliberately not in Block 9

- ❌ **Personal Kakao account automation** — explicitly out of scope per
  KakaoTalk TOS
- ❌ **WhatsApp** — Meta API restrictions; defer until business case
- ❌ **iMessage / RCS** — Apple does not expose APIs
- ❌ **Custom CRM integrations** — out of scope for personal use
- ❌ **Calendar sharing with other users** — out of scope
- ❌ **Smart home automation building** — Newton consumes Home Assistant
  automations; doesn't replace HA's automation engine
- ❌ **Voice control of smart home from outside the network** — local LAN only

---

## 3. Risk matrix

| Risk | Impact | Mitigation |
|------|--------|-----------|
| OAuth token leak (Gmail / Outlook / Slack) | High | File perms 0600; gitignore config/credentials/; documented |
| Accidental email send | High | risk 4 default + voice approval; per-recipient policies sir-managed |
| KakaoTalk policy change kills Yellow ID | Med | Documented constraint; read-only mode unaffected |
| Home Assistant URL exposes home network | High | LAN-only API; documented setup |
| Smart home unwanted action (e.g. lights at 03:00) | Med | quiet_hours enforced on routines |
| Calendar sync conflicts (event modified in two places) | Med | Source of truth = remote API; cache invalidated on conflict |
| Cross-channel consolidation drops important notifications | Med | "highest-information" picker; sir can disable consolidation |
| Bot tokens (Slack/Discord/Telegram) leaked into git | High | gitignored credentials directory; documented |
| Approval prompt fatigue ("too many email sends") | Med | per-recipient always-allow policies sir can configure |
| Provider deprecations (Google API changes) | Med | Pin SDK versions; integration tests catch breakage |
| 18–25 day estimate optimistic | Med | Each provider takes 1-2 days; cumulative drift possible |

---

## 4. After Block 9 — opening message for the next chat

```markdown
# Newton v4 — Block 10 start (LoRA per Persona, conditional)

## Context
- Newton: multi-persona AI OS, OpenJarvis fork
- Environment: RTX 5090 + WSL2 Ubuntu + systemd
- Location: ~/newton-v4/

## Design docs
[newton-v4-master.md]
[newton-v4-tech-stack.md]
[newton-v4-voice.md]      # block 10 STT LoRA section
[newton-v4-block-9.md]    # complete
[newton-v4-block-10.md]   # this block (conditional)
[TERMINOLOGY.md]

## Blocks 1–9 result
- v0.9.0-block9: communication + calendar + smart home
  - 5 messenger providers (Gmail, Outlook, Slack, Discord, Telegram, KakaoTalk constrained)
  - Calendar from 3 sources
  - Home Assistant control
  - Proactive calendar alerts
  - Smart home routines via Block 4 patterns
  - Cross-channel consolidation

## Note: Block 10 is CONDITIONAL
- Triggered only when sir's vault > 500 notes per persona
- Or when sir's STT corpus accumulates > 1 hour
- Otherwise skip directly to Block 11

## Next
Block 10 step 10.1 — vault size + corpus assessment, or skip to Block 11.
```

---

## 5. Honest reality check

**Time estimate:** **18–25 days at sir's pace.** Wide surface area
(many integrations), each shallow.

**Riskiest steps:**

- **Step 9.5** (KakaoTalk) — policy ambiguity; could be unusable
- **Step 9.10** (Home Assistant) — depends on sir having HA already
  set up; if not, this step extends to "set up HA" too
- **Step 9.2 + 9.4** (send capabilities) — wrong recipient = social
  cost. Voice approval channel critical.

**Simplest steps:**

- 9.1, 9.3, 9.8 — standard OAuth + API integration

**Most important step:**

- **Step 9.9** (calendar proactive alerts). This is the most
  user-visible behavior from this block — Newton speaking up before
  meetings.

**Behavioural shift:**

After Block 9, Newton becomes a *household member*. Sir's home responds
to sir. Sir's inbox is curated. Sir's day is structured around proactive
calendar awareness. This is when Newton's value compounds — every block
before this was infrastructure for *this*.

**Assets carried over:**

- Block 1 `calendar_events` table — finally populated
- Block 2 ToolRegistry → many new high-risk tools
- Block 4 scheduler + DeliveryChannel → calendar alerts + routines
- Block 5 VoiceApprovalChannel → preferred channel for send approvals
- Block 5 STT/TTS → voice approval flow
- ~593 pytest cases must still pass

---

## 6. Starting checklist

Before Block 9 begins:

- [ ] Block 8 tagged `v0.8.0-block8`, `newton status` green
- [ ] Pytest ~593 passing
- [ ] Google account ready for OAuth (Gmail + Calendar)
- [ ] Outlook account (optional)
- [ ] Slack workspace + bot token plan (optional)
- [ ] Discord / Telegram bot setup (optional)
- [ ] Decide on KakaoTalk strategy: Yellow ID, read-only via phone, or skip
- [ ] Home Assistant instance running on local network (or skip step 9.10–9.11)
- [ ] Long-lived HASS token if using HA
- [ ] sir has 3–4 weeks of focused work

---

Ready when sir is. Step 9.1 is the entry point.
