# Newton v4 — Engines & Capabilities

> Modular design for every functional engine.
> **Core principle: hot-swappable provider system** — runtime replacement
> without restart.
>
> This document is the *capability matrix*. Step-level detail lives in
> `newton-v4-block-2.md` (registry infrastructure), `newton-v4-block-7.md`
> (search / OS / translation / autoresearch), and `newton-v4-block-9.md`
> (communication / calendar / smart home).

---

## 0. Core architecture — Hot-swappable Provider pattern

### Why this pattern matters

Sir's decision: *"Modularize so providers can be replaced by command
without restart. Default to free; pay only when the free tier falls short."*

This is not merely "add a feature." It is **one of Newton's most
important design patterns.** Once built, it pays off forever.

### Pattern structure

```
[Newton Capability Layer]
        ↓
[Provider Registry] ← runtime add/swap
   ├ web.search.searxng      (default, free)
   ├ web.search.brave        (registered, dormant)
   ├ web.search.tavily       (registered, dormant)
   └ web.search.firecrawl    (registered, dormant)
        ↓
[Active provider selection]
   - default: lowest cost priority
   - command: "JARVIS, search with brave" → one-shot swap
   - command: "JARVIS, change default search to firecrawl" → permanent
   - command: "JARVIS, back to free search" → searxng again
        ↓
[Tool call]
        ↓
[Result + usage / cost telemetry]
```

### Command examples (sir's voice)

```
"JARVIS, show me search providers"
→ active: searxng (free, unlimited)
  registered: brave ($5/month, 0/1000 used)
              tavily (1000/month free, 0/1000 used)
              firecrawl (1000/month free, 0/1000 used)

"JARVIS, use firecrawl just for this search. JS-rendered page."
→ one-shot swap. Next search returns to searxng.

"JARVIS, change default search to tavily."
→ permanent change. Saved to provider_state table.

"JARVIS, I've used up the free quota. Suggestions?"
→ tavily quota at 999/1000. Recommend fallback to SearXNG. Proceed?
```

### Implementation core

```python
# newton/providers/base.py
class Provider(ABC):
    name: str
    capability: str
    cost_model: str        # "free", "free_tier", "paid"
    free_quota: int | None
    used_this_month: int

    @abstractmethod
    async def execute(self, request) -> Result: ...

    @abstractmethod
    async def health_check(self) -> bool: ...


# newton/providers/registry.py
class ProviderRegistry:
    def register(self, capability, provider): ...
    def get_active(self, capability) -> Provider: ...
    def swap(self, capability, provider_name, scope='session'): ...
    def list_providers(self, capability) -> list[Provider]: ...
    def telemetry(self) -> dict: ...
```

Block 2 ships the registry; blocks 7 and 9 fill it with real providers.

---

## 1. Capability matrix (overview)

Each row defines a capability with its default + registered alternates.
Detailed implementation lives in the listed block.

| Capability | Default | Alternates | Block |
|------------|---------|------------|-------|
| `tool.calling` (registry itself) | newton-internal | — | 2 |
| `embedding.encode` | BGE-M3 | (future: e5-mistral, multilingual-e5) | 3 |
| `vault.search` | newton-internal (Qdrant) | — | 3 |
| `vision.llm` | Qwen 2.5 VL 7B | Qwen 2.5 VL 32B | 6 |
| `web.search` | SearXNG (self-host) | Brave, Tavily, Firecrawl | 7 |
| `doc.parse` | MarkItDown | (future: unstructured) | 7 |
| `video.download` | yt-dlp | (none — yt-dlp covers 1500+ sites) | 7 |
| `os.command` | pyautogui | — | 7 |
| `translate.text` | Qwen 2.5 32B | (future: NLLB-200) | 7 |
| `research.loop` | newton-internal (autoresearch) | — | 7 |
| `email.read` | Gmail / Outlook / IMAP | (per provider) | 9 |
| `email.send` | Gmail / Outlook / SMTP | (per provider) | 9 |
| `messenger.send` | Slack / Discord / Telegram | Kakao Yellow ID (constrained) | 9 |
| `calendar.read` | Google / Outlook / CalDAV | (per provider) | 9 |
| `calendar.write` | Google / Outlook / CalDAV | (per provider) | 9 |
| `home.control` | Home Assistant | — | 9 |

---

## 2. Web search

### Provider matrix

| Provider | License | Cost | Free quota | Notes |
|----------|---------|------|------------|-------|
| **SearXNG** | AGPL-3.0 (self-host fine) | free | unlimited | Default; aggregates Google, Bing, etc. |
| **Brave Search** | proprietary API | $5/mo | included | Higher quality, privacy-focused |
| **Tavily** | proprietary API | free tier | 1000/month | LLM-optimized; AI-friendly snippets |
| **Firecrawl** | proprietary API | free tier | 1000/month | JS rendering for SPA sites |

### Setup snippets

```bash
# SearXNG (Docker)
docker run -d --name searxng -p 8080:8080 \
  -v searxng-data:/etc/searxng searxng/searxng

# .env (gitignored)
BRAVE_API_KEY=...
TAVILY_API_KEY=...
FIRECRAWL_API_KEY=...
```

Block 7 details: 4 providers registered, SearXNG default, sir can
hot-swap by voice or CLI.

---

## 3. Document analysis

**Choice: MarkItDown (Microsoft, MIT).** Converts PDF / Word / Excel /
PowerPoint / HTML / EPUB to markdown. Output feeds the main LLM.

```python
from markitdown import MarkItDown
md = MarkItDown()
result = md.convert("document.pdf")
print(result.text_content)
```

Limitation: scanned (image-based) PDFs require OCR (out of scope).

Block 7 ships `doc_parse` tool wrapping this provider.

---

## 4. Image analysis (Vision LLM)

**Choice: Qwen 2.5 VL family.** 7B default, 32B for high-detail dynamic
swap. Block 6 wires the provider; block 7 exposes it as a tool.

```yaml
vision.llm:
  default: qwen-2.5-vl-7b
  registered:
    - { name: qwen-2.5-vl-7b,  vram_gb:  6, model: qwen2.5-vl:7b  }
    - { name: qwen-2.5-vl-32b, vram_gb: 18, model: qwen2.5-vl:32b }

  routing_rules:
    - if: "image.size < 1MB and simple_question"
      prefer: qwen-2.5-vl-7b
    - if: "complex analysis or detail required"
      prefer: qwen-2.5-vl-32b
    - default: qwen-2.5-vl-7b
```

VRAM management: never load both. Main LLM evicted during 32B swap.

---

## 5. Video analysis pipeline

Three-stage pipeline (Block 7 step 7.5):

```
1. yt-dlp downloads video (or just subtitles)
2. Whisper transcribes audio (if no subtitles)
3. (optional) Vision LLM analyzes key frames
4. Main LLM summarizes
```

Pipeline shape (configurable):

```yaml
video.summarize:
  default: whisper-then-llm
  pipelines:
    - name: whisper-then-llm       # fast
      steps: [download_subtitle_or_whisper, llm_summarize]
    - name: full-frame-analysis    # accurate, slow
      steps: [download_video, extract_keyframes, vision_llm, llm_summarize]
```

---

## 6. SNS access — honest reality check

Sir wanted **KakaoTalk + Instagram + YouTube**. Each has serious
constraints. The matrix below is honest about what's feasible.

### YouTube ✅ (easy)

| Item | Value |
|------|-------|
| API | YouTube Data API v3 (official, free) |
| Quota | 10,000 units / day |
| Capability | search, channel info, captions |
| Download | yt-dlp |

Use cases: search, channel inspection, trending feeds, caption
extraction. Newton priority: 🥇

### Instagram ⚠ (limited)

| Item | Value |
|------|-------|
| Official API | Instagram Graph API |
| Access | **own account only** (business account required) |
| Not possible | search others, hashtag search (removed post-2020) |
| Unofficial scraping | violates TOS, account-ban risk |

Reality: "search Instagram" is essentially impossible. **Only own
account management.** Newton priority: 🥉

### KakaoTalk ⚠⚠ (most constrained)

Personal-account automation = **account ban risk**. Kakao's 2026
multi-device login policy actively flags automation patterns.

| Option | Feasible? | Notes |
|--------|-----------|-------|
| Yellow ID (Plus Friend) business account | ✅ | Service-provider ID. Subscribed friends can receive auto-responses. Business registration required. |
| Personal account direct automation | ❌ | TOS violation; account bans enforced |
| IRIS unofficial bot | ⚠ | Python bot via KakaoTalk DB access; needs Android root + emulator; high ban risk |
| Sendbird KakaoTalk API | 💰 paid | For business AlimTalk |

**Newton path (proposed):**

- **Read-only first** — Newton monitors KakaoTalk push notifications
- **Yellow ID for sending** — only if sir registers a business account
- **Personal-account automation: not recommended.** Ban risk too high

Block 9 step 9.5 implements the proposed two-mode approach.

### Other SNS (helpful, sir didn't ask)

- **Reddit** — best information-search SNS; free API; 🥈
- **Mastodon** — Twitter alternative, completely free; 🥈
- **Bluesky** — newer, free API; 🥈

---

## 7. Messengers

| Platform | MCP / API | License | Korea environment |
|----------|-----------|---------|-------------------|
| Slack | official first-party | free | corporate |
| Discord | community + official | free | dev / gaming communities |
| Telegram | community + Bot API | free | some users |
| KakaoTalk | unofficial MCP (see §6) | — | sir's main personal env |
| WhatsApp | Business API | paid | global |
| LINE | Bot API | free tier | Japan-centric |
| MS Teams | official | M365 subscription | corporate |

**Newton ships (Block 9):** Gmail (+ Outlook for backup) + Slack +
Discord + Telegram + KakaoTalk (Yellow ID + read-only).

---

## 8. Email

| Provider | API | License | Notes |
|----------|-----|---------|-------|
| Gmail | Google API (OAuth) | free for Newton's use | per-user OAuth refresh token |
| Outlook | Microsoft Graph | free | per-user OAuth |
| Naver Mail | IMAP / SMTP | free | use IMAP fallback |
| Generic IMAP | IMAP/SMTP | free | fallback |

Block 9 ships Gmail + Outlook + IMAP fallback.

---

## 9. Calendar

| Provider | Protocol | License | Notes |
|----------|----------|---------|-------|
| Google Calendar | Google API (OAuth) | free | dominant |
| Outlook | Microsoft Graph | free | corporate |
| Naver Calendar | CalDAV | free | Korean users |
| Apple Calendar | CalDAV | free | iPhone users |
| Generic CalDAV | CalDAV | free | fallback |

Block 9 ships all three plus the generic CalDAV adapter.

---

## 10. Smart home

**Choice: Home Assistant (Apache 2.0).**

- Local hub; LAN-only API
- Long-lived access token
- WebSocket + REST APIs
- Vast device ecosystem (Philips Hue, Nest, Aqara, etc.)

Block 9 ships `home_devices_list`, `home_device_set`, `home_scene_activate`
tools. Routines wire into Block 4 patterns.

---

## 11. Autoresearch (block 7)

**Capability: `research.loop`.** Karpathy-style agentic loop:

- Editable asset (single file Newton may modify)
- Single scalar metric (defined per job)
- Time-boxed cycles (e.g. 30 s per iteration)
- Iteration cap (e.g. 100 cycles overnight)

Use cases:

- Email tone tuning: "improve this email's friendliness for 100 cycles"
- Code optimization: "make this function faster, scored by benchmark"
- Document polishing: "tighten this draft against a rubric"

Block 7 steps 7.9–7.11 ship the foundation, scheduler integration with
Block 4, and the LLM-driven `autoresearch_propose` tool.

---

## 12. Provider Registry — file layout

```
newton/providers/
├── base.py                # ABC
├── registry.py            # central registry + telemetry
├── builtin/
│   ├── echo_loud.py       # demo (block 2)
│   ├── echo_quiet.py      # demo (block 2)
│   ├── searxng.py         # web.search default (block 7)
│   ├── brave.py           # web.search alternate (block 7)
│   ├── tavily.py
│   ├── firecrawl.py
│   ├── markitdown.py      # doc.parse (block 7)
│   ├── yt_dlp.py          # video.download (block 7)
│   ├── qwen_vl_7b.py      # vision.llm default (block 6)
│   ├── qwen_vl_32b.py     # vision.llm swap (block 6)
│   └── (more in blocks 9, 10)
├── cli/
│   └── providers.py       # newton providers list/swap/test
└── api/
    └── providers.py       # HTTP endpoints for runtime swap
```

### CLI cheatsheet

```bash
# Full listing
newton providers list

# Per capability
newton providers list --capability web.search

# Active swap (permanent)
newton providers swap web.search brave --permanent

# One-shot swap (next call only)
newton providers swap web.search firecrawl --once

# Register only (don't activate)
newton providers register web.search tavily --api-key=$TAVILY_API_KEY

# Usage telemetry
newton providers usage

# Health check
newton providers health
```

### Runtime swap (via LLM tool call)

```python
# Tool JARVIS can call
async def swap_provider(capability: str, provider_name: str, scope: str = "session"):
    """
    Replace active provider at runtime.
    scope: "once" (next call) | "session" (process) | "permanent" (DB-backed)
    """
    registry.swap(capability, provider_name, scope=scope)
    return {"status": "swapped", "active": provider_name}
```

---

## 13. Block distribution

| Capability area | Block |
|-----------------|-------|
| Provider Registry infrastructure | 2 |
| Embedding | 3 |
| Vault search (Qdrant + RAG) | 3 |
| Web search providers | 7 |
| Document analysis | 7 |
| Image analysis | 7 (provider in 6) |
| Video summarization | 7 |
| OS commands | 7 |
| Translation | 7 |
| Autoresearch | 7 |
| Email | 9 |
| Messengers (Slack/Discord/Telegram) | 9 |
| KakaoTalk (Yellow ID + read-only) | 9 |
| Calendar (Google/Outlook/CalDAV) | 9 |
| Smart home (Home Assistant) | 9 |

---

## 14. Reality check

**Strengths:**

- Hot-swap pattern pays off forever. Every new capability follows the
  same pattern.
- Free default + paid fallback policy controls cost ceiling.
- Most capabilities have free options (keeps Newton's local-first soul).
- MCP servers already exist for many providers.

**Watch-outs:**

- **SNS automation reality** — sir's expectations may need calibration.
  "Search all SNS" is not feasible.
- **KakaoTalk constraint** — central to Korean environment but most
  restrictive.
- **Provider Registry design upfront cost** — Block 2 has to do this
  right because every subsequent block depends on it.
- **Paid API temptation** — sir's "free first, paid when needed" policy
  must be honoured.

**Critical link:**

Provider Registry is deeply coupled with Block 2 (Tool Calling +
Approval Hook). Block 2 ships both at once. The "tool result → save? →
share?" flow and the "swap provider" flow must be consistent.

---

## 15. Wrap-up

This is Newton's capability engine reference.

Core principles recap:

1. **Hot-swappable** — runtime replacement, no restart
2. **Free first** — base is forever $0
3. **Paid opt-in** — activate explicitly when needed
4. **Honest about limits** — SNS automation reality
5. **Korean environment respected** — KakaoTalk, Naver Mail, CalDAV

Reference this document during Blocks 2 (registry), 6 (vision), 7
(search / OS / translation / autoresearch), and 9 (comms / calendar /
home).

Good work, sir.
