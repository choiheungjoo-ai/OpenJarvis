# Newton v4 — Tech Stack & License Reference

> All locked libraries / models / tools.
> Licenses and costs verified.
> Block numbers use the new 11-block mapping (see `newton-v4-master.md` §6).

---

## 0. Core principles

✅ **Every component:**

- Runs locally
- Free (zero licensing cost)
- Permissive license (Apache 2.0 or MIT)
- Commercial use allowed (Newton could be open-sourced or sold)

❌ **Forbidden:**

- Cloud API dependency (except opt-in)
- Usage-restricted models
- Non-commercial licenses

---

## 1. Full stack at a glance

| Area | Library / Model | License | Cost | Notes |
|------|----------------|---------|------|-------|
| **Foundation** | OpenJarvis | Apache 2.0 | free | Stanford SAIL |
| **LLM runtime** | Ollama | MIT | free | + vLLM option |
| **Main LLM** | Qwen 2.5 32B | Apache 2.0 | free | ~18 GB VRAM (4-bit) |
| **Code LLM** | Qwen 2.5 Coder 14B | Apache 2.0 | free | ~9 GB VRAM (dynamic swap) |
| **Fast LLM** | Qwen 2.5 7B | Apache 2.0 | free | ~5 GB VRAM (Butler, fast intent classifier) |
| **Embedding** | BGE-M3 | MIT | free | Korean-strong |
| **STT** | Whisper Large v3 (via faster-whisper) | MIT | free | + Contextual Biasing |
| **VAD** | Silero VAD | MIT | free | Voice activity detection |
| **Wake word** | openWakeWord | Apache 2.0 | free | Custom training supported |
| **TTS (Korean + multilingual)** | Qwen3-TTS-1.7B-CustomVoice + 0.6B | Apache 2.0 | free | Zero-shot voice cloning (3 s reference) |
| **TTS (British tone)** | Chatterbox | MIT | free | JARVIS-en only |
| **Voice ID** | Resemblyzer | Apache 2.0 | free | Speaker verification |
| **Face detection** | MediaPipe Face | Apache 2.0 | free | Google |
| **Face recognition** | InsightFace | Apache 2.0 (lib) | free | ArcFace SOTA; see §5 on model weights |
| **Expression** | DeepFace | MIT | free | 7 emotions |
| **Hand tracking** | MediaPipe Hand | Apache 2.0 | free | 21 landmarks |
| **Static gesture** | MediaPipe Gesture Recognizer | Apache 2.0 | free | Built-in + custom |
| **Static gesture training** | MediaPipe Model Maker | Apache 2.0 | free | Static classifier |
| **Dynamic gesture** | PyTorch LSTM (Newton-built) | — | free | Sequence classifier |
| **OS automation** | pyautogui | BSD | free | UI gestures → keyboard/mouse |
| **System monitoring** | psutil | BSD | free | CPU / memory / disk / battery |
| **GPU monitoring** | nvidia-ml-py | BSD | free | VRAM / temperature (RTX 5090) |
| **Screen capture** | mss | MIT | free | For screen awareness |
| **Vision LLM** | Qwen 2.5 VL 7B / 32B | Apache 2.0 | free | Image + screen + scene analysis |
| **Document analysis** | MarkItDown | MIT | free | PDF / Word / Excel / PPT → markdown |
| **Video downloader** | yt-dlp | Public domain | free | YouTube + many sites |
| **NER (Korean)** | spaCy + ko_core_news_sm | MIT | free | Vault → biasing dict |
| **Calendar** | Google Calendar API / Microsoft Graph / CalDAV | — | free (API) | MCP server pattern |
| **Diarization** | pyannote.audio | MIT | free | Meeting mode |
| **Smart home (optional)** | Home Assistant API | Apache 2.0 | free | IoT integration |
| **Vector DB** | Qdrant | Apache 2.0 | free | Local Docker |
| **Metadata DB** | SQLite | Public domain | free | Python built-in |
| **LoRA training (block 10)** | Unsloth | Apache 2.0 | free | RTX 5090 optimized |
| **Web search (default)** | SearXNG | AGPL-3.0 (self-host fine) | free | Self-hosted, no API key |
| **Web search (alternates)** | Brave / Tavily / Firecrawl | proprietary APIs | free tier / paid | Hot-swap providers |
| **Backend** | FastAPI | MIT | free | OpenJarvis baseline |
| **Frontend** | React + Vite | MIT | free | OpenJarvis baseline |
| **Desktop** | Tauri | MIT/Apache 2.0 | free | OpenJarvis baseline |
| **3D Brain** | React Three Fiber + drei | MIT | free | Block 11 |
| **Mobile** | Tauri Mobile | Apache 2.0 | free | Block 11 |
| **HUD overlay** | Tauri secondary window | MIT/Apache 2.0 | free | Block 11 |

**Total: 100 % free, 100 % local, commercial use viable.**

---

## 2. VRAM budget (RTX 5090, 32 GB)

### Always-loaded models

| Model | VRAM |
|-------|------|
| Qwen 2.5 32B (main) | ~18 GB |
| BGE-M3 embedding | ~2 GB |
| Whisper Large v3 | ~3 GB |
| Qwen3-TTS 1.7B + 0.6B | ~5 GB |
| Voice ID + Face ID + Expression models | ~1.5 GB |
| **Subtotal** | **~29.5 GB** |

### Dynamic swap (load on demand, evict when done)

| Model | VRAM | Use case |
|-------|------|----------|
| Qwen 2.5 Coder 14B | ~9 GB | code questions |
| Qwen 2.5 VL 32B | ~18 GB | high-detail vision queries |
| Chatterbox | ~4 GB | JARVIS English replies |

**Strategy:** keep ~29.5 GB always-resident; remaining ~2.5 GB is the
hot-swap window. For large swaps (Coder, VL-32B), main LLM is temporarily
unloaded or quantized further. Only one large swap active at a time.

---

## 3. STT / TTS routing policy

### STT — Whisper only

All voice input flows the same path:

```
USB mic → Silero VAD → openWakeWord (Stage 1)
       → Voice ID (Stage 2 Path A) → Whisper Large v3
       → text + language tag
```

### TTS router

```
response text + persona + language
        ↓
   [TTS router]
        ↓
├ Butler (any language)    → Qwen3-TTS 0.6B (fast)
├ Friday (ko / en)         → Qwen3-TTS 1.7B
├ JARVIS Korean            → Qwen3-TTS 1.7B
└ JARVIS English (British) → Chatterbox
```

**TTS fallback chain** (see `newton-v4-voice.md` §2.6.1): each engine
has a defined fallback path. If the primary fails, Newton announces
once per session and uses the fallback.

---

## 4. Core library install commands (reference)

Install incrementally per block — never all at once.

### Block 1 (foundation)

```bash
# OpenJarvis fork (already done)
git clone https://github.com/open-jarvis/OpenJarvis.git newton-v4
cd newton-v4
uv sync --extra dev
uv run pre-commit install

# Newton additions
uv add pydantic pyyaml sqlalchemy
```

### Block 2 (tools + approval + providers)

```bash
uv add psutil  # for system_info builtin tool
```

### Block 3 (vault + RAG + memory)

```bash
uv add qdrant-client
uv add sentence-transformers  # BGE-M3
uv add watchdog               # file watcher
uv add python-frontmatter     # markdown frontmatter
uv add spacy                  # NER for biasing hook
uv run python -m spacy download ko_core_news_sm
```

### Block 4 (proactive engine)

```bash
uv add psutil nvidia-ml-py   # GPU monitoring
# notify-send available on host (apt install libnotify-bin) for desktop delivery channel
```

### Block 5 (voice layer)

```bash
uv add sounddevice silero-vad openwakeword
uv add faster-whisper        # STT
uv add resemblyzer           # Voice ID
uv add bcrypt                # PIN/passphrase hash
uv add pyannote.audio        # meeting mode diarization
pip install qwen-tts         # TTS (Korean + multilingual)
pip install chatterbox-tts   # TTS (British tone)
```

### Block 6 (vision)

```bash
uv add opencv-python mediapipe
uv add insightface onnxruntime-gpu
uv add deepface
uv add mss                   # screen capture
```

### Block 7 (search + OS + translation + autoresearch)

```bash
uv add markitdown            # document analysis
uv add yt-dlp                # video downloader
uv add pyautogui             # OS commands
# SearXNG runs in Docker
```

### Block 8 (gesture)

```bash
pip install mediapipe-model-maker
```

### Block 9 (communication + calendar + smart home)

```bash
uv add google-auth-oauthlib google-api-python-client  # Gmail + Calendar
uv add msal                                            # Outlook + Microsoft Graph
uv add slack-sdk discord.py python-telegram-bot
uv add caldav                                          # CalDAV calendar
uv add httpx websocket-client                          # Home Assistant
```

### Block 10 (LoRA, conditional)

```bash
uv add unsloth bitsandbytes  # LLM LoRA training
```

### Block 11 (UI + 3D Brain + multi-client)

```bash
# Node side
cd newton-ui && npm install
# Tauri Mobile setup separately per platform
```

---

## 5. InsightFace model license note

The InsightFace **library code** is Apache 2.0, but some **pretrained
model weights** have non-commercial restriction clauses.

- Newton personal use → safe ✅
- Newton open-sourced on GitHub → safe ✅
- Newton as a commercial product → review weights individually ⚠

Alternative if commercialization matters: `face_recognition` (dlib-based,
MIT). Accuracy slightly lower, license fully permissive.

Decision point: **Block 6, Step 6.2.** Sir confirmed personal use for v1.0;
revisit if direction changes.

---

## 6. Chatterbox watermark note

Every Chatterbox audio output embeds a **PerTh watermark** (for
detection purposes).

- Newton personal use → no effect ✅
- Public content creation (YouTube, etc.) → detectable ⚠

Decision point: **Block 5, Step 5.6.** Sir confirmed personal use; not
a concern.

---

## 7. OpenJarvis integration notes

### Skills vs Persona separation

```
Persona (Newton)  = identity + permissions + voice
Skills (OpenJarvis) = how to use tools
```

One persona can call many skills. Skills are a shared pool.

Examples:

- JARVIS persona → code-assistant skill + vault-search skill + web-research skill
- Friday persona → vault-search skill + web-research skill (no code)

### Learning separation

```
OpenJarvis Learning (automatic) → improves "how to answer"
Newton self-learning (approved)  → grows "what to know" (vault write)
```

They don't conflict.

---

## 8. Voice command processing flow (reference)

```
1. USB mic            → 16 kHz WAV
2. VAD (Silero)       → speech / silence
3. Stage 1            → clap trigger OR "Newton" wake word OR persona-name wake word
4. Voice ID (Resemblyzer) → user_id
5. STT (Whisper Large v3) → text + language tag
6. Persona routing    → Stage 2 Path A (voice naming) or Path B (face binding from block 6)
7. Intent classification (Qwen 2.5 7B)
8. Main LLM (Qwen 2.5 32B) + tool calls (block 2 ToolRegistry)
9. Response text
10. TTS router        → Qwen3-TTS or Chatterbox (with fallback chain)
11. Speaker
```

**Korean vs English:** identical pipeline; only language metadata
differs per stage. No translation step.

---

## 9. License safety matrix

| Use case | Safe? |
|----------|-------|
| sir personal use | ✅ entirely safe |
| Family / acquaintance shared use | ✅ entirely safe |
| GitHub open source | ✅ entirely safe |
| Commercial product / SaaS | ⚠ review (InsightFace weights, Chatterbox watermark) |
| Cloud SaaS | ⚠ re-review every model's weights license |

Newton's initial target is **sir personal use** → **entirely safe**.

---

## 10. Backup and migration strategy

### Regular backup

```bash
# Backup to Windows side
mkdir -p /mnt/c/Users/USER/Documents/newton-v4-backup
rsync -a ~/newton-v4/ /mnt/c/Users/USER/Documents/newton-v4-backup/$(date +%Y%m%d)/
```

### Backup targets

- `~/newton-v4/data/` — vault, DB, voice embeddings (irreplaceable)
- `~/newton-v4/config/` — settings
- Git repo — code (also pushed to GitHub remote)

### Backup cadence

- Daily automated: `data/` directory
- Block completion: full snapshot + git tag

---

## 11. Block-specific dependency summary

| Block | Key new deps | Block estimate |
|-------|--------------|----------------|
| 1 | pydantic, sqlalchemy, pyyaml | done (1–2 weeks) |
| 2 | psutil | 8–12 days |
| 3 | qdrant-client, sentence-transformers, spacy | 15–25 days |
| 4 | psutil, nvidia-ml-py | 15–20 days |
| 5 | sounddevice, silero-vad, faster-whisper, qwen-tts, chatterbox-tts | 15–22 days |
| 6 | opencv-python, mediapipe, insightface, deepface | 12–18 days |
| 7 | markitdown, yt-dlp, pyautogui + SearXNG Docker | 20–28 days |
| 8 | mediapipe-model-maker | 25–35 days |
| 9 | google-auth, msal, slack-sdk, discord.py, python-telegram-bot, caldav | 18–25 days |
| 10 (conditional) | unsloth | 5–10 days or skipped |
| 11 | Tauri Mobile, R3F, drei | 20–30 days |

Total span: 6–12 months at sir's pace.

---

Good work, sir. This file is the reference. Other documents cite it.
