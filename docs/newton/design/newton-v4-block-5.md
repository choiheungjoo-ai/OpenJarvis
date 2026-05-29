# Newton v4 — Block 5: Voice Layer + Meeting Mode

> Master plan: `newton-v4-master.md`
> Tech stack: `newton-v4-tech-stack.md`
> Voice details: `newton-v4-voice.md`
> Terminology: `TERMINOLOGY.md`
> Prerequisite: Block 4 complete (`v0.4.0-block4`, `docs/newton/block-4-summary.md`)
>
> **Goal:** Close the conversation loop. After this block, sir can talk
> to Newton naturally — wake word, voice-named persona, conversational
> turn-taking, persona-tone TTS reply, fallback if a model fails.

---

## 0. Block 5 — overall goals

Eight concerns wired together:

1. **VAD** — Silero VAD detects speech vs silence
2. **Wake word + clap trigger** — system wake (Stage 1)
3. **Voice ID** — Resemblyzer identifies sir / gf (Stage 2 Path A)
4. **STT** — Whisper Large v3 with 3-tier Contextual Biasing
5. **Persona naming** — "JARVIS" / "Friday" → persona activation (Stage 2 Path A continued)
6. **TTS** — Qwen3-TTS CustomVoice (ko + Butler) + Chatterbox (JARVIS-en)
7. **TTS fallback chain** — 3-step graceful degradation with announcement
8. **Meeting mode** — diarization + realtime transcription + action items

Plus the integrations:

- `VoiceApprovalChannel` — plugs into Block 2's `ApprovalChannel` ABC
- `VoiceDeliveryChannel` — plugs into Block 4's `DeliveryChannel` ABC
- Vault biasing dict (block 3) feeds Whisper Contextual Biasing here
- STT corpus auto-accumulation for the optional block 10 LoRA training

### Locked decisions (entering Block 5)

| Item | Decision | Source |
|------|----------|--------|
| **STT engine** | Whisper Large v3 via faster-whisper | voice.md §2 |
| **VAD** | Silero VAD | voice.md §2.1 |
| **Wake word** | openWakeWord ("Newton" + persona names) | voice.md §2.2 |
| **Clap trigger** | audio classifier (openWakeWord-trained) | this block + sir decision |
| **Voice ID** | Resemblyzer (Apache 2.0) | tech-stack.md |
| **TTS engines (per persona)** | Butler → Qwen3-TTS 0.6B; JARVIS-ko / Friday → Qwen3-TTS 1.7B; JARVIS-en → Chatterbox | tech-stack.md §3 |
| **TTS sample policy** | one fixed tone per persona; multiple samples of same tone for clone stability | sir decision |
| **TTS fallback chain** | Option 3 — full chain + announcement | sir decision, voice.md §2.6.1 |
| **2-stage activation** | Stage 1 = clap or "Newton"; Stage 2 = voice naming (Path A) or face binding (Path B, comes in block 6) | master.md §1.3 |
| **Voice donor** | term `voice sampler` — never sir or gf; consent.md required | TERMINOLOGY |
| **Multi-speaker policy** | Voice ID lock; 30 s timeout to unlock | voice.md §2.8 |
| **STT corpus** | post-wake-word, sir-only utterances auto-saved for block 10 | master.md §1.5 |
| **Contextual Biasing** | 3 tiers (system + user + recent context); user tier sourced from vault biasing dict | voice.md §2.5 |
| **PIN/passphrase fallback** | already enforced in block 1 schema; block 5 wires the actual prompt | block 1 |
| **VRAM budget** | ~30.5 GB always-on; Qwen3-TTS Butler engine sits in reserve for fallback | tech-stack.md §2 |
| **Clap permission scope** | deferred to step 5.12 — defaults to `shared` (anyone can wake) | sir's previous "deferred" |

### Completion criteria (block as a whole)

```bash
# Boot the voice stack
$ uv run newton voice start
voice stack up: VAD + wake word + Voice ID + STT + TTS router + 4 fallback paths

# Voice session walkthrough
[sir claps]                                          # Stage 1
[Newton: "Yes, sir?"]                                # Butler greeting
[sir: "JARVIS"]                                      # Stage 2 Path A
[Newton recognises sir + activates JARVIS]
[sir: "what's on my calendar tomorrow"]              # STT working
[JARVIS replies in cloned voice]                     # TTS working

# Force TTS fallback
$ uv run newton voice tts --persona jarvis --text "test" --simulate-failure 1.7b
[fallback] Qwen3-TTS 1.7B failed; using 0.6B
[announcement] "잠시만요, sir. 톤이 다를 수 있습니다."
[audio plays in 0.6B clone]

# Voice approval channel (calls back into block 2)
$ uv run newton tools run echo_to_file --args '{"text":"hi","path":"/tmp/t.txt"}' \
    --user sir --persona jarvis --channel voice
[JARVIS speaks]: "Sir, echo_to_file requires approval. Proceed?"
[sir: "yes"]
[ToolResult ok]

# Voice delivery channel (block 4 proactive)
$ uv run newton proactive test-notification "Sir, battery low" --channel voice
[JARVIS speaks the notification]

# Meeting mode
$ uv run newton voice meeting start
[diarization + transcription running; press Ctrl+C to stop]
$ # ... meeting happens ...
[meeting summary saved to data/vault/_auto/meetings/2026-06-15-T1429.md]

# STT corpus accumulation
$ uv run newton voice corpus stats
total: 47 utterances, 12 min, 4.2 MB
ready for block 10 LoRA fine-tune: not yet (need >= 1 hour)

# Tests
$ uv run pytest tests/newton/ -v
# Blocks 1-4: ~243 + Block 5: ~75 = ~318 passed
```

Block 5 makes Newton *talk*. End-to-end voice is the line where this
project stops being plumbing and starts being a living assistant.

---

## 1. Block 5 — 13 steps

Each step: one focused change, one verification, one commit.
`ruff check` + `ruff format` clean before commit.

Estimated total: **15–22 days at sir's pace.** Includes voice sampler
coordination time (step 5.4 needs an acquaintance to record).

This is the v1 voice.md step list (renumbered from 4.x → 5.x) plus
Step 5.13 (TTS fallback chain) and clap trigger work folded into 5.2.

---

### Step 5.1 — Silero VAD integration (half-day)

**Goal:** Filter silence from continuous mic input so downstream stages
only see speech.

**Outputs:**

- `newton/voice/vad.py` — Silero VAD wrapper, streaming-friendly
- `newton/voice/audio_source.py` — USB mic abstraction (sounddevice)
- `tests/newton/voice/test_vad.py`

**Dependencies:**

```bash
uv add sounddevice silero-vad
```

**Verification:**

```bash
uv run python -m newton.voice.audio_source --listen 10
# 10s of mic capture; prints "speech" / "silence" labels per chunk
uv run pytest tests/newton/voice/test_vad.py -v
```

**Risk:** Mic permissions on WSL2 are tricky. **Mitigation:** PulseAudio
bridge from Windows host; documented in `scripts/newton/setup-audio.md`.

**Commit:** `feat(voice): Silero VAD + USB mic source`

---

### Step 5.2 — openWakeWord + clap trigger (1 day)

**Goal:** Stage 1 activation — clap *or* "Newton" wake word.

Both are first-class triggers. Either wakes the system.

**Outputs:**

- `newton/voice/wake.py` — openWakeWord wrapper
- `newton/voice/clap_detector.py` — pretrained clap pattern (audio classifier)
- `newton/voice/stage1.py` — unified Stage 1 detector (clap OR wake word)
- `tests/newton/voice/test_wake.py`
- `tests/newton/voice/test_clap.py`

**Dependencies:**

```bash
uv add openwakeword
```

**Wake words shipped (pretrained or community-trained):**

- "Newton" — system wake
- "JARVIS" — system wake + Stage 2 Path A (persona = jarvis)
- "Friday" — system wake + Stage 2 Path A (persona = friday)
- "Butler" — system wake + Stage 2 Path A (persona = butler)

Custom training of "제비스" (Jarvis pronounced in Korean) lands in
step 5.12 if pretrained options sound poor.

**Clap detection:**

openWakeWord supports user-trained patterns. Train on a small dataset of
2-clap-in-sequence samples (clap-pause-clap, ~500 ms total). Single
spurious claps (TV, conversation laughter) are filtered by the 2-clap
rule.

**Verification:**

```bash
uv run python -m newton.voice.stage1 --listen 30
# prints "stage1: clap" / "stage1: wake[Newton]" / etc.
uv run pytest tests/newton/voice/test_wake.py tests/newton/voice/test_clap.py -v
```

**Commit:** `feat(voice): Stage 1 — wake word + clap trigger`

---

### Step 5.3 — Qwen3-TTS model download + hello world (half-day)

**Goal:** Get Qwen3-TTS-CustomVoice running locally. Synthesize one
sentence with a default voice.

**Outputs:**

- `newton/voice/tts/qwen3.py` — Qwen3-TTS adapter
- `scripts/newton/download-models.sh` — fetches Qwen3-TTS 0.6B + 1.7B
- `tests/newton/voice/test_tts_qwen3.py`

**Dependencies:**

```bash
pip install qwen-tts
```

**Verification:**

```bash
./scripts/newton/download-models.sh
uv run python -m newton.voice.tts.qwen3 --text "Hello, sir." --out /tmp/hello.wav
aplay /tmp/hello.wav    # or play via Windows-side audio
uv run pytest tests/newton/voice/test_tts_qwen3.py -v
```

**Risk:** Model download is large (~5 GB combined). Slow first run.
**Mitigation:** docs say to run setup on fast network; checksums in
`download-models.sh`.

**Commit:** `feat(voice): Qwen3-TTS adapter with hello-world synthesis`

---

### Step 5.4 — Persona TTS sample directory + consent (1–2 days)

**Goal:** Voice samplers record reference audio for JARVIS, Friday,
Butler. Consent recorded per directory.

**This step requires acquaintances.** sir needs to coordinate with
voice samplers before code can be written.

**Outputs:**

- `data/voices/jarvis/samples/` directory (gitignored)
- `data/voices/friday/samples/`
- `data/voices/butler/samples/`
- `data/voices/<persona>/samples/consent.md` template
- `data/voices/<persona>/samples/<n>.wav` + matching `<n>.txt`
- `docs/newton/voice-sampler-protocol.md` — what sentences to record, what consent says, retention policy
- `newton/cli.py` — `newton voice samples register <persona> <wav> <transcript>` (validates pair, copies in, updates consent ledger)

**Sample protocol:**

- 3–10 samples per persona
- Each 5–15 s, clean audio (low noise)
- Same voice sampler across samples for one persona
- Varied sentence content but consistent tone (calm / focused / warm /
  whatever fits the persona)
- Recordings stored as 16 kHz mono WAV with paired plain-text
  transcripts

**consent.md template:**

```markdown
# Voice sampler consent

I, _______________ ("the voice sampler"), consent to my voice recordings
being used by Newton (sir's personal AI system) for the purpose of
cloning the voice of the persona "{persona_name}".

Use is limited to:
- sir's personal use only
- offline / local inference (no cloud upload)
- no commercial use without my explicit further consent

I may withdraw consent at any time, at which point all recordings will
be deleted within 24 hours.

Signed: ___________________   Date: _______________
```

**Verification:**

```bash
ls data/voices/jarvis/samples/
# 001.wav, 001.txt, 002.wav, 002.txt, ..., consent.md
uv run newton voice samples list jarvis
# 5 samples, consent on file
```

**Commit:** `feat(voice): persona sample directories + consent protocol`

---

### Step 5.5 — Zero-shot voice cloning verification (half-day)

**Goal:** Confirm Qwen3-TTS uses persona samples to clone the tone.

**Outputs:**

- `newton/voice/tts/router.py` — picks engine + sample by persona + language
- `tests/newton/voice/test_tts_router.py`

**Routing table (from voice.md):**

| Persona | Language | Engine | Sample |
|---------|----------|--------|--------|
| Butler  | any      | Qwen3-TTS 0.6B | butler/ko-001 |
| JARVIS  | ko       | Qwen3-TTS 1.7B | jarvis/ko-001 |
| JARVIS  | en       | Chatterbox     | (chatterbox uses its own voice clip) |
| Friday  | ko       | Qwen3-TTS 1.7B | friday/ko-001 |
| Friday  | en       | Qwen3-TTS 1.7B | friday/en-001 (or fall back to ko sample with English text — Qwen3-TTS handles cross-lingual) |

**Verification:**

```bash
uv run newton voice tts --persona jarvis --lang ko --text "안녕하십니까, sir."
# produces /tmp/<timestamp>.wav using jarvis/ko-001 sample
# sir listens, confirms it sounds like the voice sampler

uv run pytest tests/newton/voice/test_tts_router.py -v
```

**Risk:** Cloning quality varies per voice sampler. **Mitigation:**
3–10 samples per persona; step 5.13 fallback chain catches catastrophic
failures.

**Commit:** `feat(voice): TTS routing + zero-shot cloning verified`

---

### Step 5.6 — Chatterbox integration for JARVIS English (half-day)

**Goal:** Wire Chatterbox for JARVIS-English's British butler tone.

**Outputs:**

- `newton/voice/tts/chatterbox.py` — Chatterbox adapter
- Routing updated: `(jarvis, en) → chatterbox`
- `data/voices/jarvis/chatterbox-reference.wav` (a 5 s British male voice clip)
- `tests/newton/voice/test_chatterbox.py`

**Dependencies:**

```bash
pip install chatterbox-tts
```

**Verification:**

```bash
uv run newton voice tts --persona jarvis --lang en --text "Right away, sir."
# produces a British-toned audio file
```

**Note on watermark:** Chatterbox embeds a PerTh audio watermark. Per
sir's earlier decision: personal use, watermark doesn't matter.

**Commit:** `feat(voice): Chatterbox for JARVIS English`

---

### Step 5.7 — Whisper Large v3 + faster-whisper (half-day)

**Goal:** STT working end-to-end. Korean + English in one model.

**Outputs:**

- `newton/voice/stt/whisper.py` — faster-whisper wrapper
- `newton/voice/stt/__init__.py` — STT facade with language auto-detection
- `tests/newton/voice/test_stt.py`

**Dependencies:**

```bash
uv add faster-whisper
```

**Verification:**

```bash
# Record 5 s of speech
uv run python -m newton.voice.audio_source --record 5 --out /tmp/test.wav
uv run python -m newton.voice.stt.whisper /tmp/test.wav
# prints transcription + detected language

uv run pytest tests/newton/voice/test_stt.py -v
```

**Commit:** `feat(voice): Whisper Large v3 STT with language detection`

---

### Step 5.8 — Contextual Biasing (3 tiers) (1 day)

**Goal:** Pull biasing terms from the vault biasing dict (block 3) and
inject into Whisper's `initial_prompt` per call.

**Outputs:**

- `newton/voice/stt/biasing.py`
  - `class BiasingDict`
  - 3 tiers: `system` (always), `user` (from `users.stt_bias_dict_json`), `context` (recent session terms)
  - `build_prompt(user_id, session_id) -> str` (Whisper's initial_prompt format)
- `newton/cli.py` — `newton voice biasing show --user X`, `newton voice biasing test --text "..." --user X`
- `tests/newton/voice/test_biasing.py`

**Tiers in order:**

1. **System** — always-on technical terms (model names, common
   software). Hard-coded plus loaded from `config/biasing_system.txt`.
2. **User** — sir's `stt_bias_dict_json` (populated by block 3 vault
   hook).
3. **Context** — terms from the current session's last 3–5 messages
   (extracted via spaCy NER on-the-fly).

Joined into a single prompt: `"Domain context: Newton, RTX 5090, BGE-M3,
JARVIS, Stella, ...".`

**Verification:**

```bash
# Without biasing
uv run newton voice stt /tmp/say-bge-m3.wav
# might transcribe "BG M3" or "BGM3"

# With biasing
uv run newton voice stt /tmp/say-bge-m3.wav --user sir
# transcribes "BGE-M3" correctly

uv run pytest tests/newton/voice/test_biasing.py -v
```

**Commit:** `feat(voice): 3-tier contextual biasing wired to vault dict`

---

### Step 5.9 — Voice ID registration + recognition (half-day)

**Goal:** Resemblyzer registers sir's voice; later utterances are
matched against registered users.

**Outputs:**

- `newton/voice/voice_id.py`
  - `register(user_id, audio_path)` — generates embedding, stores in `users.voice_embedding`
  - `identify(audio_segment) -> (user_id | None, confidence)`
- `newton/cli.py` — `newton voice id register <user_id> <wav>`, `newton voice id verify <wav>`
- `tests/newton/voice/test_voice_id.py`

**Dependencies:**

```bash
uv add resemblyzer
```

**Verification:**

```bash
# Enrollment
uv run newton voice id register sir data/voices/sir/voice_id.wav
# users.voice_embedding populated

# Verification
uv run newton voice id verify /tmp/some-utterance.wav
# user: sir, confidence: 0.87
```

**Commit:** `feat(voice): Resemblyzer Voice ID enrollment + verification`

---

### Step 5.10 — Session lock + multi-speaker policy (half-day)

**Goal:** First speaker after Stage 1 wakes locks the session. Other
speakers' audio is dropped until 30 s of silence elapses.

**Outputs:**

- `newton/voice/session_lock.py` — manages locked user + last activity
- Integration with stage1.py and stt facade
- `tests/newton/voice/test_session_lock.py`

**Behaviour (from voice.md §2.8):**

```
[clap or wake word]
    ↓
[first utterance] → Voice ID → user_id = sir
    ↓
🔒 SESSION LOCK to sir
    ↓
subsequent utterances: only sir's voice passes STT
    ↓
30 s of no sir-voice activity → unlock
    ↓
next Stage 1 starts fresh
```

**Edge cases (handled in tests):**

- sir talks, gf interrupts → gf's audio dropped
- sir + gf both say wake word in the same window → earliest timestamp wins
- sir leaves the room, gf takes over → must Stage 1 again
- session lock + voice approval channel → only locked user can approve

**Verification:**

```bash
uv run pytest tests/newton/voice/test_session_lock.py -v
```

**Commit:** `feat(voice): session lock with multi-speaker filtering`

---

### Step 5.11 — PIN / passphrase fallback (half-day)

**Goal:** When Voice ID fails the retry profile (block 1 schema already
holds `pin_hash`, `passphrase_hash`), prompt for PIN.

**Outputs:**

- `newton/voice/fallback.py` — implements the 3-tier flow from master.md §3.4
- bcrypt verification (Python stdlib via `passlib` or `bcrypt`)
- `newton/cli.py` — `newton voice id enroll-pin <user_id>`, `enroll-passphrase`
- `tests/newton/voice/test_fallback.py`

**Dependencies:**

```bash
uv add bcrypt
```

**Verification:**

Voice ID fails → system speaks "Voice authentication failed. Please say
your PIN or passphrase." → sir speaks "1879" → bcrypt match → session
authorized.

**Commit:** `feat(voice): PIN/passphrase fallback after Voice ID failure`

---

### Step 5.12 — Custom wake word training (1–2 days, optional)

**Goal:** If pretrained wake words don't work well for sir's voice or
for Korean pronunciation of "JARVIS" / "제비스", train custom ones.

**Outputs:**

- `scripts/newton/train-wake-word.sh` — orchestrates openWakeWord
  custom training pipeline
- `data/voices/wake_words/jarvis-ko/` — training samples + trained model
- Docs in `docs/newton/wake-word-training.md`

**This is the one optional step.** Skip if pretrained patterns work.
Estimated time depends on dataset size; openWakeWord can train on as
few as 50 utterances per word.

**Also resolves the deferred clap-permission decision:**

| Mode | Behaviour |
|------|----------|
| `clap_shared` (default) | any registered user can use clap to wake |
| `clap_sir_only` | clap only valid when face cam (or Voice ID on first utterance) confirms sir |
| `clap_off` | clap trigger disabled; wake word only |

Default ships as `clap_shared` — sir can switch by voice command.

**Verification:**

```bash
./scripts/newton/train-wake-word.sh jarvis-ko data/voices/wake_words/jarvis-ko/samples/
# trained model saved
uv run newton voice wake reload
# new model now active
```

**Commit:** `feat(voice): custom wake word training pipeline + clap permission modes`

---

### Step 5.13 — TTS fallback chain + Voice channels (1 day)

**Goal:** Three-step graceful TTS degradation + Voice approval + Voice
delivery channels for blocks 2 and 4.

**Outputs:**

- `newton/voice/tts/fallback.py`
  - implements voice.md §2.6.1 chain
  - per-language fallback table
  - one-announcement-per-session throttling
- `migrations/009_tts_fallback_log.sql` — `tts_fallback_log` table
- `newton/voice/approval_channel.py` — `VoiceApprovalChannel(ApprovalChannel)` for block 2 hook
- `newton/voice/delivery_channel.py` — `VoiceDeliveryChannel(DeliveryChannel)` for block 4 scheduler
- Channel registration: `ApprovalChannel.register(VoiceApprovalChannel)`,
  `DeliveryChannel.register(VoiceDeliveryChannel)`
- `tests/newton/voice/test_fallback.py`
- `tests/newton/voice/test_voice_channels.py`

**Fallback chain (from voice.md §2.6.1):**

```
ko flow:
  primary:  Qwen3-TTS 1.7B (JARVIS-ko / Friday)
  fallback: Qwen3-TTS 0.6B (uses same persona sample reference)
  text-only: stdout + HUD (block 11)

en flow:
  primary:  Chatterbox (JARVIS-en)
  fallback: Qwen3-TTS 1.7B in English mode
  text-only: stdout + HUD

Butler flow (any lang):
  primary:  Qwen3-TTS 0.6B
  fallback: Qwen3-TTS 1.7B
  text-only: stdout + HUD
```

**Failure triggers:**

- `OutOfMemoryError`, `FileNotFoundError`, `RuntimeError`
- timeout > 10 s
- output validation: wav < 0.1 s, or silence ratio > 95 %

**Announcement throttling:** one fallback announcement per session in
the relevant persona's voice. Subsequent fallbacks in the same session
go silent (HUD only, when HUD lands in block 11).

**Schema:**

```sql
CREATE TABLE tts_fallback_log (
    log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    persona_id      TEXT NOT NULL,
    language        TEXT NOT NULL,
    primary_engine  TEXT NOT NULL,
    fallback_engine TEXT NOT NULL,
    failure_reason  TEXT NOT NULL,
    text_length     INTEGER,
    occurred_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (persona_id) REFERENCES personas(persona_id) ON DELETE RESTRICT
);
```

**VoiceApprovalChannel (the block 2 abstraction pays off here):**

```python
class VoiceApprovalChannel(ApprovalChannel):
    name = "voice"

    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        prompt = self.persona_render(request)
        await speak(prompt, persona=request.persona_id)
        response = await listen(timeout=15, locked_user=request.user_id)
        allowed = self.parse_yes_no(response)
        return ApprovalDecision(allowed=allowed, decided_by=request.user_id, note=response)
```

**VoiceDeliveryChannel (the block 4 abstraction pays off here):**

```python
class VoiceDeliveryChannel(DeliveryChannel):
    name = "voice"

    async def deliver(self, notification: Notification) -> Reaction:
        await speak(notification.text, persona=notification.persona_id)
        # caller (scheduler) records the reaction separately when sir reacts
        return Reaction.delivered
```

**Verification:**

```bash
# TTS fallback
uv run newton voice tts --persona jarvis --lang ko --text "테스트" --simulate-failure primary
# logs fallback, plays 0.6B output, announces "tone may differ"

# Voice approval channel (calls back into block 2)
uv run newton tools run echo_to_file --args '{"text":"hi","path":"/tmp/x.txt"}' \
    --user sir --persona jarvis --channel voice
# JARVIS speaks the prompt; sir answers; result logged

# Voice delivery channel (calls back into block 4)
uv run newton proactive test-notification "Sir, test" --channel voice
# JARVIS speaks notification

uv run pytest tests/newton/voice/test_fallback.py tests/newton/voice/test_voice_channels.py -v
```

**Commit:** `feat(voice): TTS fallback chain + voice approval/delivery channels (migration 009)`

---

### (Bonus) Meeting mode + Block 5 summary + tag (1.5 days)

This combines two things into one final step to keep the count at 13.

**Goal:** Diarization + realtime transcription + action-item extraction
mode. Then ship Block 5.

**Outputs:**

- `newton/voice/meeting/mode.py` — orchestrator
- `newton/voice/meeting/diarization.py` — pyannote.audio wrapper
- `newton/voice/meeting/transcription.py` — streaming Whisper with rolling buffer
- `newton/voice/meeting/action_items.py` — LLM-based action-item extraction at meeting end
- Auto-save: `data/vault/_auto/meetings/<timestamp>.md` (ACL-tagged to sir)
- `newton/cli.py` — `newton voice meeting start/stop/summary`
- `tests/newton/voice/test_meeting.py`

**Dependencies:**

```bash
uv add pyannote.audio
```

**Meeting note format (saved on stop):**

```markdown
---
acl:
  owner: sir
  read_users: [sir]
  read_personas: [jarvis]
  status: canonical
tags: [meeting, auto, 2026-06-15]
duration_min: 47
speakers: ["sir", "speaker_B", "speaker_C"]
---

# Meeting 2026-06-15 14:29

## Transcript
[14:29:03] sir: Let's discuss block 5 status.
[14:29:18] speaker_B: ...
...

## Action items
- sir: review TTS fallback samples (due: 2026-06-20)
- speaker_B: collect voice sampler consent forms
- ...

## Topics
- Block 5 progress
- TTS quality concerns
- Voice sampler scheduling
```

**Final Block 5 summary:**

- `docs/newton/block-5-summary.md`
- `docs/newton/cli.md` — final audit
- `README.md` — Block 5 marked complete
- Git tag: `v0.5.0-block5`

**Block 6 entry conditions:**

- Voice stack operates end-to-end (clap → wake → ID → STT → LLM → TTS)
- VoiceApprovalChannel registered with block 2 ToolRegistry
- VoiceDeliveryChannel registered with block 4 scheduler
- Meeting mode tested with real recorded audio
- Whisper LoRA training pipeline scaffolded (data collection started)
- STT corpus accumulating
- TTS fallback chain working (tested with simulated failures)
- All pytest cases pass (~318 total)
- Preflight 9/9 still ✓
- OpenJarvis: still 0 files modified

**Commit + tag:** `chore: block 5 complete`

---

## 2. Deliberately not in Block 5

- ❌ **Face binding (Path B of Stage 2)** — block 6 (face recognition produces the signal)
- ❌ **Whisper LoRA fine-tune** — block 10 (corpus accumulates here, training runs later)
- ❌ **Real-time translation** — block 7 (uses voice stack from this block)
- ❌ **HUD visual notifications** — block 11
- ❌ **3D Brain voice control** — block 11
- ❌ **Multi-language TTS samples per persona** — out of scope (one tone per persona, sir confirmed)
- ❌ **Cloud TTS / STT options** — local-only principle holds

---

## 3. Risk matrix

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Mic permissions on WSL2 | Med | Setup doc; PulseAudio bridge |
| Voice sampler unavailable (step 5.4 blocked) | High | Block other steps; circle back when sampler available. Step 5.4 must complete before 5.5 |
| Qwen3-TTS clone quality varies per sampler | Med | TTS fallback (5.13) catches outright failures; bad-but-recognizable handled by re-recording |
| Whisper Korean accuracy on technical terms | Med | Biasing (5.8) addresses; LoRA (block 10) for further improvement |
| openWakeWord false positives | Med | Custom training (5.12) when needed |
| Clap false positives (TV applause, hand-clapping during conversation) | Med | 2-clap-in-sequence rule, not single clap |
| Session lock confuses sir / gf when both present | Low | 30 s timeout + explicit "JARVIS, my turn" override |
| VRAM exceeded during Chatterbox swap | Med | Dynamic unload + reload pattern; tech-stack §2 budget honoured |
| Voice approval channel + audio output collision | Med | Audio mutex: TTS pauses during STT capture and vice versa |
| Meeting diarization on Korean accents | Med | pyannote handles ko adequately; not critical for action-item extraction |
| TTS fallback announcement annoys sir | Low | One-per-session throttle; can disable via voice cmd |
| 15–22 day estimate optimistic | Med | Step 5.4 is the slowest (depends on humans). Re-estimate after 5.4 |

---

## 4. After Block 5 — opening message for the next chat

```markdown
# Newton v4 — Block 6 start (Vision Layer)

## Context
- Newton: multi-persona AI OS, OpenJarvis fork
- Environment: RTX 5090 + WSL2 Ubuntu + systemd
- Location: ~/newton-v4/

## Design docs
[newton-v4-master.md]
[newton-v4-tech-stack.md]
[newton-v4-engines.md]
[newton-v4-block-5.md]    # complete
[newton-v4-block-6.md]    # this block
[TERMINOLOGY.md]

## Blocks 1–5 result
- v0.1.0-block1: identity & data foundation
- v0.2.0-block2: tool calling + approval hook + provider registry
- v0.3.0-block3: persona engine + vault + ACL + RAG + memory
- v0.4.0-block4: proactive engine
- v0.5.0-block5: voice layer + meeting mode
  - 2-stage activation operational
  - Voice approval channel + voice delivery channel wired into blocks 2/4
  - TTS fallback chain
  - Meeting mode with action-item extraction

## Next
Block 6 step 6.1 — MediaPipe Face detection.
```

---

## 5. Honest reality check

**Time estimate:** **15–22 days at sir's pace.** Step 5.4 (voice sampler
coordination) is human-bottlenecked, not technical.

**Riskiest steps:**

- **Step 5.4** (voice samplers) — depends on people, not code
- **Step 5.5** (cloning quality) — first time we judge subjective audio
- **Step 5.13** (fallback + channels) — the most integration-heavy step

**Simplest steps:**

- 5.1 (VAD), 5.3 (Qwen3-TTS hello), 5.7 (Whisper) — all are wrapping libraries

**Most important step:**

- **Step 5.10** (session lock). Multi-speaker policy is correctness-critical
  for sir / gf shared use.

**Behavioural shift:**

After block 5, sir stops typing. The CLI exists but is operator-only.
Daily interaction with JARVIS becomes voice + voice. This is when
Newton starts feeling alive.

**Assets carried over:**

- `ApprovalChannel` from block 2 → `VoiceApprovalChannel` concrete
- `DeliveryChannel` from block 4 → `VoiceDeliveryChannel` concrete
- Vault biasing dict from block 3 → Whisper Contextual Biasing
- `tts_fallback_log` table for block 4 to monitor

---

## 6. Starting checklist

Before Block 5 begins:

- [ ] Block 4 tagged `v0.4.0-block4`, `newton status` green
- [ ] Pytest ~243 passing
- [ ] USB mic working and detected by sounddevice
- [ ] Speakers / headphones working from WSL2
- [ ] Voice samplers arranged (at least one acquaintance per persona)
- [ ] At least 1 hour of sir's recorded utterances reserved on disk
- [ ] Qwen3-TTS model files downloaded (~5 GB)
- [ ] Whisper Large v3 model downloaded (~3 GB)
- [ ] Chatterbox + pyannote pinned in pyproject.toml

---

Ready when sir is. Step 5.1 is the entry point.
