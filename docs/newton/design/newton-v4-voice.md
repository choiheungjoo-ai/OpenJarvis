# Newton v4 — Voice System Design

> Complete design for voice input and output.
> Main reference during Block 5 (Voice Layer).
> Master plan: `newton-v4-master.md`
> Step decomposition: `newton-v4-block-5.md`
> Terminology: `TERMINOLOGY.md`

---

## 0. Identity — three different audio data types

The most confusing part of Newton's voice system, clarified upfront:

```
┌──────────────────────────────────────────────────────────────┐
│  TTS Sample (for speaking)                                   │
│  - The persona's voice                                       │
│  - Recorded by a voice sampler (NOT sir or gf themselves)    │
│  - 10-15 s per recording, clean environment, with consent    │
│  - Used as zero-shot clone reference at every TTS call       │
│  - Stored: ~/newton-v4/data/voices/<persona>/samples/        │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  Voice ID Sample (for authentication)                        │
│  - sir's (or gf's) own voice                                 │
│  - 10-15 s of natural speech at registration                 │
│  - Generates embedding via Resemblyzer                       │
│  - Stored: users.voice_embedding (BLOB) in DB                │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  STT Corpus (for Block 10 training, optional)                │
│  - sir's daily utterances, auto-accumulated after wake word  │
│  - Training data for Whisper LoRA fine-tune                  │
│  - 1-5 hours accumulation triggers Block 10                  │
│  - Stored: ~/newton-v4/data/voices/sir/stt_corpus/           │
└──────────────────────────────────────────────────────────────┘
```

**Locked principle:** sir's voice is used for listening only (Voice ID +
STT). The persona's voice is used for speaking only (TTS).

---

## 1. End-to-end flow (after Block 5)

```
[USB mic always on]
   ↓
[Silero VAD] ← speech vs silence
   ↓ speech detected
[Stage 1 — system wake]
   ↓ clap trigger OR "Newton" wake word OR persona-name wake word
[openWakeWord matches]
   ↓
[Stage 2 — Path A: voice naming]
[Resemblyzer Voice ID] ← identifies first speaker
   ↓ user = sir (or gf, guest)
[🔒 SESSION LOCK to user]
   - other voices filtered for the duration
   - 30 s of no activity → unlock
   ↓
[Whisper Large v3 + Contextual Biasing] ← STT (uses block 3 biasing dict)
   ↓ text + language tag
[Persona Engine] ← from block 3; routes user → persona
   ↓
[LLM] ← Qwen 2.5 32B + tool calls (block 2 ToolRegistry)
   ↓ response text
[TTS Router] ← persona-aware engine selection
   ↓
[TTS Fallback Chain if primary fails — see §2.6.1]
   ↓
[Qwen3-TTS or Chatterbox produces audio]
   ↓
[Speaker output]
   ↓
[Background] post-wake-word sir audio → stt_corpus/ auto-accumulation
   ↓
[Block 10 trigger] after 1-5 hours → optional Whisper LoRA fine-tune
```

Stage 2 also has Path B (face binding) — added in Block 6 alongside Path A.

---

## 2. Components

### 2.1 VAD (Voice Activity Detection)

**Engine:** Silero VAD

| Item | Value |
|------|-------|
| License | MIT |
| Role | distinguish speech from silence |
| VRAM | ~50 MB (very light) |
| CPU-capable | ✅ (no GPU needed) |
| Latency | <10 ms |

Why needed: the mic is always on. VAD prevents wasteful STT calls during
silence and filters out background noise.

### 2.2 Wake word (Stage 1)

**Engine:** openWakeWord (Apache 2.0)

Two trigger types accepted by Stage 1:

1. **Clap trigger** — sequence-based clap pattern (2 claps in quick
   succession; avoids single-clap false positives from TV applause).
2. **Wake words** — "Newton" (system wake only), "JARVIS" / "Friday" /
   "Butler" (system wake + Stage 2 Path A persona hint).

Custom training of "제비스" (Korean pronunciation of JARVIS) supported
via openWakeWord training pipeline (Block 5 Step 5.12 if needed).

### 2.3 Voice ID (Stage 2 Path A — speaker identification)

**Engine:** Resemblyzer (Apache 2.0)

- Generates 256-dim embedding per utterance
- Cosine similarity match against `users.voice_embedding`
- Threshold-driven per authentication profile (strict / normal / relaxed
  from master.md §3.5)

### 2.4 STT (speech to text)

**Engine:** Whisper Large v3 via faster-whisper

| Item | Value |
|------|-------|
| Model | whisper-large-v3 (downloaded once, ~3 GB) |
| Library | faster-whisper (CTranslate2 backend) |
| Languages | 99 supported; Korean + English primary |
| Latency | ~1-3 s per utterance on RTX 5090 |

### 2.5 Contextual Biasing (3 tiers)

Whisper's `initial_prompt` parameter, populated from three tiers (Block 5
Step 5.8):

1. **System tier** — always-on technical terms (model names, common
   software). Hard-coded plus loaded from `config/biasing_system.txt`.
2. **User tier** — sir's `stt_bias_dict_json` populated by the **Block 3
   vault biasing hook** (every note save → spaCy NER → entities added to
   sir's dict).
3. **Context tier** — last 3-5 messages of the current session, NER'd
   on-the-fly.

Joined as `"Domain context: Newton, RTX 5090, BGE-M3, JARVIS, Stella, ..."`.

The Block 3 → Block 5 link is critical: STT accuracy on technical / personal
vocabulary improves automatically as sir's vault grows.

### 2.6 TTS engines (per persona)

| Persona | Language | Engine | Notes |
|---------|----------|--------|-------|
| Butler  | any      | Qwen3-TTS 0.6B | fast, multilingual |
| JARVIS  | ko       | Qwen3-TTS 1.7B | clone from `data/voices/jarvis/samples/` |
| JARVIS  | en       | Chatterbox     | British male tone, separate reference clip |
| Friday  | ko       | Qwen3-TTS 1.7B | clone from `data/voices/friday/samples/` |
| Friday  | en       | Qwen3-TTS 1.7B | cross-lingual clone (Qwen3-TTS handles) |

**TTS sample policy (sir confirmed):**

- One tone per persona (fixed accent / gender / age band)
- Multiple samples allowed *of the same tone* (improves clone stability)
- The voice sampler is **never sir or gf** — always an acquaintance with
  consent recorded in `consent.md`

### 2.6.1 TTS Fallback Chain (sir's locked decision — option 3)

Three-step graceful degradation with explicit announcement. Implemented
in Block 5 Step 5.13.

#### Chain definition

```
ko flow:
  primary:  Qwen3-TTS 1.7B (JARVIS-ko / Friday)
  fallback: Qwen3-TTS 0.6B (Butler engine, same sample reused)
  text-only: stdout + HUD (block 11), TTS skipped

en flow:
  primary:  Chatterbox (JARVIS-en, British tone)
  fallback: Qwen3-TTS 1.7B in English mode (loses British tone, still speaks)
  text-only: stdout + HUD

Butler flow (any language):
  primary:  Qwen3-TTS 0.6B
  fallback: Qwen3-TTS 1.7B
  text-only: stdout + HUD
```

#### Failure triggers (move to next fallback step)

- Exception (`OutOfMemoryError`, `FileNotFoundError`, `RuntimeError`)
- Timeout (>10 s no response)
- Output validation (wav length <0.1 s, or silence ratio >95 %)

#### Announcement strategy

Pre-recorded short messages per persona (separate from the system prompt):

```yaml
fallback_announcements:
  jarvis_ko_to_butler:
    ko: "잠시만요, sir. 톤이 다를 수 있습니다."
  jarvis_en_to_qwen:
    en: "One moment, sir. Voice may sound different."
  friday_ko_to_butler:
    ko: "잠깐만요. 목소리가 조금 다를 수 있어요."
  any_to_text_only:
    ko: "음성 출력이 어렵습니다. 텍스트로 응답드립니다."
    en: "Voice output unavailable. Responding in text."
```

The announcement is spoken via the fallback engine itself. Main response
follows immediately.

#### Throttling — preventing annoyance

- First fallback in a session → voice announcement
- Subsequent fallbacks → HUD indicator only (Block 11)
- 30 min of no utterances → session reset → next fallback announces again

#### Logging

Block 5 Step 5.13 adds the `tts_fallback_log` table. Every fallback
event logs: session, persona, language, primary engine, fallback engine,
failure reason, text length, timestamp.

Block 4 (proactive) can monitor this log: *"Recent fallbacks are
frequent — suggest a GPU health check."*

#### Notes on the chain (verified in Block 5 step 5.13)

1. **Whether 0.6B works as 1.7B's fallback** — same Qwen3-TTS family, so
   sample reference is likely portable. Real behaviour confirmed in step
   5.5.
2. **Text-only requires sir to see the text** — before Block 11 HUD,
   stdout is the only path. Block 11 integrates with HUD.
3. **English 1.7B is unverified.** Chatterbox is the JARVIS-English
   choice; Qwen3-TTS's English quality isn't promised. Whether the
   second fallback level is intelligible determines whether English's
   fallback step is "1.7B" or jumps directly to text-only.

### 2.7 STT auto-accumulation (for Block 10 LoRA training)

**Policy:** Only sir's post-wake-word utterances (Mode B).

```
sir says wake word → session locks to sir → STT runs
    ↓
[passive recording]
   timestamp = now()
   save audio + transcript to data/voices/sir/stt_corpus/<timestamp>.{wav,txt}
```

**Accumulation conditions:**

- ✅ sir's own voice only (Voice ID confirms)
- ✅ Post-wake-word (intentional invocation)
- ❌ No casual / private speech
- ❌ No other speakers (session lock filters)
- ❌ No guest utterances

**Management:**

```bash
newton stt corpus stats
# total: 234 utterances, 3h 12m, 1.2 GB

newton stt train-lora  # Block 10 trigger when >= 1h
```

**Privacy:**

- ACL: sir only
- Never leaves the machine
- `newton stt corpus clear` deletes anytime
- 30-day no-use auto-delete option

### 2.8 Multi-speaker policy — Voice ID lock

```
[wake word matched]
    ↓
[first speaker → Voice ID → user = sir]
    ↓
🔒 SESSION LOCK to "sir"
    ↓
subsequent STT only processes sir's voice:
    sir speaks → pass to STT
    other speakers → filtered (Resemblyzer mismatch)
    ↓
30 s no activity → unlock
    ↓
next wake word starts fresh
```

**Edge cases:**

| Case | Behaviour |
|------|-----------|
| sir speaks, gf interrupts | gf ignored; sir's lock preserved |
| sir + gf both wake word same window | earliest timestamp wins; ties → sir prior |
| sir asks Newton to invoke for gf | JARVIS refuses: "<partner> must invoke directly" |
| Session lock + sir moves to another room then calls again | new wake word → new session → re-identify |

### 2.9 PIN / passphrase fallback (3-tier auth)

Per master.md §3.4 (Block 1 schema already holds `pin_hash`, `passphrase_hash`).
Block 5 wires the actual voice prompt.

```
1st try: Voice ID at active profile threshold (e.g. 0.7)
   ↓ fail
2nd try: relaxed threshold (e.g. 0.6)
   ↓ fail
3rd try: per profile max_retries
   ↓ all fail
🔐 Voice prompt: "Voice authentication failed. Say your PIN or passphrase."
   ↓ match
session activated for this session only
   ↓ mismatch
Butler guest mode fallback
```

---

## 3. Meeting mode (Block 5 final step)

Optional mode for multi-speaker meetings:

- pyannote.audio diarization (who spoke when)
- Realtime transcription (streaming Whisper)
- Action-item extraction at meeting end (LLM rubric)
- Auto-save to `data/vault/_auto/meetings/<timestamp>.md`

Triggered:

- Manual: "JARVIS, meeting mode"
- Auto: when calendar has an event happening now (Block 9 integration)

---

## 4. VRAM budget for voice stack

Always-loaded (per tech-stack.md §2):

- Whisper Large v3: ~3 GB
- Qwen3-TTS 1.7B + 0.6B: ~5 GB
- Voice ID embeddings: tiny
- Silero VAD + openWakeWord: ~100 MB
- **Voice stack subtotal: ~8 GB**

Dynamic swap:

- Chatterbox: ~4 GB (loaded only for JARVIS-en responses)
- pyannote.audio: ~2 GB (loaded only during meeting mode)

Strategy: voice stack core stays resident. Big swaps (Chatterbox,
pyannote) load on demand, evict afterwards.

---

## 5. Block 10 — Whisper STT Fine-tune (conditional)

**Trigger:** `stt corpus >= 1 hour` of sir-only utterances.

**Training:**

1. Split corpus into train / val
2. Whisper Large v3 + LoRA (rank 16)
3. Learning rate: pretrain LR / 40
4. Linear decay to zero
5. 1-3 epochs
6. WER evaluation on held-out val set
7. If WER improves, hot-swap as production model

**Expected effect:** 23-36 % WER reduction on sir's vocabulary (based on
Nepali low-resource paper; Korean likely similar).

**Cost:**

- Disk: ~5 GB (corpus + training artifacts)
- GPU: RTX 5090, 2-6 hours
- sir intervention: minimal (automated)

**Conditional:** sir-activated only. Default: off.

---

## 6. Security and privacy

### Voice data protection

| Data | Location | Protection |
|------|----------|------------|
| TTS samples (voice samplers) | data/voices/<persona>/samples/ | gitignored; disk encryption recommended |
| Voice ID embedding | DB BLOB | DB access control |
| STT corpus (auto) | data/voices/sir/stt_corpus/ | gitignored; ACL: sir only |

### gitignore

```gitignore
data/voices/*/samples/*.wav
data/voices/*/samples/*.mp3
data/voices/*/stt_corpus/
data/voices/*/embeddings/
```

### Cloud absolutely not

- All voice processing local (RTX 5090)
- Whisper / Qwen3-TTS / Chatterbox all local
- Cloud STT/TTS APIs banned (security)

### Consent management

- TTS sample requires `consent.md` per directory
- Voice sampler can revoke consent → samples deleted within 24 hours
- 30-day no-use auto-delete option for STT corpus

---

## 7. All decisions in one table

| Item | Decision |
|------|----------|
| TTS engines | Qwen3-TTS-CustomVoice (1.7B + 0.6B) + Chatterbox (JARVIS-en) |
| TTS sample source | acquaintance recording per sir's request (consent required) |
| Term for the recorder | voice sampler |
| TTS multi-sample policy | one tone per persona; multiple samples of same tone for stability |
| TTS fallback chain | option 3 — full chain + one announcement per session (§2.6.1) |
| STT engine | Whisper Large v3 (faster-whisper) |
| STT personalization | Contextual Biasing immediately (Block 5) + optional fine-tune (Block 10) |
| STT auto-corpus | post-wake-word sir utterances only (Mode B) |
| Wake word | openWakeWord ("Newton" + persona names) |
| Clap trigger | sequence-based 2-clap pattern; Stage 1 alongside wake word |
| Voice ID | Resemblyzer (sir 10-15 s sample at enrollment) |
| VAD | Silero VAD |
| Multi-speaker | Voice ID lock (one at a time) |
| Fallback | PIN/passphrase (optional enrollment) → Butler guest |
| 2-stage activation | Stage 1 (clap OR wake word) + Stage 2 (Path A voice naming, Path B face binding from Block 6) |
| Public scope | sir personal use only (license safety) |

---

## 8. Wrap-up

This document is Newton's complete voice system reference.

**Key points:**

- TTS sample = voice sampler recording (persona's voice)
- Voice ID sample = sir's own voice (authentication)
- STT corpus = sir's accumulated daily utterances (Block 10 input)
- These are **three completely different datasets** with different uses

During Block 5 implementation, this is the main reference. Step-by-step
construction lives in `newton-v4-block-5.md`.

Good work, sir.
