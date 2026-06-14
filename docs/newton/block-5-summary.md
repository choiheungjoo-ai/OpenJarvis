# Block 5 — Voice Layer (partial: TTS routing + cloning ready, end-to-end deferred)

Tag: `v0.5.0-block5`
Branch: `newton-main`

## What this block delivers

The stack that lets Newton talk and listen — minus the three pieces
that need real audio sir hasn't recorded yet. After block 5, every
seam from microphone → wake word → STT → persona routing → LLM → TTS
exists, is configuration-driven, lazy-loads its model on first use,
and is unit-tested without a working mic or any model download. The
two ABC bridges into earlier blocks are wired: voice approval
implements block 2's `ApprovalChannel`, voice delivery implements
block 4's `DeliveryChannel`.

Concretely:

- An `AudioSource` ABC with a stdlib-only WAV file source and an
  in-memory list source for tests, plus a `MicSource` that
  lazy-imports `sounddevice` so the core remains importable on a
  GPU-less, mic-less host. WSL2 PulseAudio setup is documented but
  no test touches it.
- A `VAD` ABC with `SileroVAD` (lazy torch + silero_vad) and a
  deterministic `RmsVAD` for tests. A `SpeechSegmenter` on top of
  per-chunk decisions emits discrete `speech_start` / `speech_end`
  events with hysteresis from `VADConfig.min_speech_chunks` /
  `min_silence_chunks`.
- A Stage-1 detector that combines two first-class triggers:
  `OpenWakeWordDetector` (lazy `openwakeword.model.Model`, scripted
  buddy for tests) and `ClapDetector` (energy-peak 2-clap pattern,
  no model). Wake-wins-ties when both could fire on the same chunk.
- A `TTS` ABC + `TTSResult` + `save_wav` helper, with three concrete
  engines: `Qwen3TTS` (0.6B / 1.7B, lazy `qwen-tts`), `ChatterboxTTS`
  (lazy `chatterbox.tts`), and a sub-module `_TextOnlyTTS` used as
  the chain's terminal sink. Every adapter ships an injectable
  `loader` callable so tests pass stubs and never touch the real
  packages.
- A `TTSRouter` that maps `(persona, language)` to engine + voice
  reference from `config/voice.yaml`. Engines are cached per
  `engine_name`; one `qwen3_tts_1.7b` instance serves both jarvis-ko
  and friday-ko. `find_route(...)` is the no-construct lookup the
  `voice tts` CLI uses to fail loudly *before* any heavy model load
  when a sample is missing.
- A `FallbackChain` that runs the language-specific ladder from
  voice.md §2.6.1, with documented failure triggers (`OSError`,
  `RuntimeError`, `MemoryError`, timeout, empty / too-short /
  silence-ratio > 95%), writes `tts_fallback_log` rows on every
  transition (migration 011), and announces at most once per chain
  instance.
- An `STT` ABC + `Transcription` dataclass, with `WhisperSTT`
  wrapping `faster-whisper` (lazy CTranslate2, not PyTorch).
  Language pin or auto-detect; the `initial_prompt` kwarg is the
  step-5.8 biasing handle. Multi-dimensional audio is rejected;
  non-16k input is logged but not fatal.
- Three-tier contextual biasing for Whisper. The prompt is built from
  `config/biasing_system.txt` (always-on technical vocab), the user's
  `stt_bias_dict_json` (the column block 3.9 already populates from
  the vault), and the last few session messages run through the
  block-3 NER helper. De-duped case-insensitively, joined into
  `"Domain context: …"`, fed to Whisper via `initial_prompt`. The
  NER extractor is injectable so unit tests don't load spaCy.
- A `SessionLock` enforcing multi-speaker policy. After Stage 1
  identifies a speaker, the lock holds for `voice.session_lock.
  timeout_seconds` seconds of locked-user silence; other speakers'
  audio is dropped. Heal-on-read everywhere so callers don't run a
  separate tick. The lock's `can_approve()` gates the voice approval
  channel: only the locked user may approve a tool.
- An `AuthHasher` ABC with a `BcryptAuthHasher` (lazy `bcrypt`) and a
  test stub. `set_pin` / `set_passphrase` / `verify_pin` /
  `verify_passphrase` write and read the block-1 `users.pin_hash` /
  `users.passphrase_hash` columns. The cascade itself
  (Voice ID → PIN → passphrase) belongs to the runtime in a later
  step; this block ships the primitives.
- `VoiceApprovalChannel(ApprovalChannel)` (block 2 plug) — session-
  lock-gated; speaks the prompt and listens via injected callables;
  `parse_yes_no` covers ko + en vocab and treats ambiguity as denied.
- `VoiceDeliveryChannel(DeliveryChannel)` (block 4 plug) — strips the
  `[kind]` and `[recall:N]` storage markers via the block-4
  `display_text` helper so sir hears the same prose the CLI prints.
- A persona sample directory + consent record system. The protocol
  (`docs/newton/voice-sampler-protocol.md`) pins the three-way split:
  donor recordings for TTS cloning, sir/gf's own voice for Voice ID,
  sir's wake-after-wake utterances for the STT corpus. The JARVIS
  consent record (`docs/newton/voice-samples/jarvis.md`) ships in git;
  the audio (`data/voices/jarvis/samples/{ko,en}/`) stays gitignored.
- A zero-shot cloning verification CLI: `newton voice tts --persona
  X --lang Y --text Z`. Four-phase pipeline that surfaces the right
  error before the wrong work runs: route → sample existence → engine
  construction → synthesis. `docs/newton/voice-cloning-verification.md`
  walks sir through the install + run flow.
- Migration 011 — `tts_fallback_log` (`session_id`, `persona_id`,
  `language`, `primary_engine`, `fallback_engine`, `failure_reason`,
  `text_length`, `occurred_at`) with indexes on
  `(session_id, occurred_at)` and `(primary_engine, occurred_at)`.

## Steps and commits

| Step | Outcome | Commit |
|------|---------|--------|
| 5.1  | Silero VAD wrapper + audio source ABC (Mic lazy / File / List) | `0c7aa32` |
| 5.2  | Stage 1: openWakeWord (lazy) + 2-clap energy detector + unified Stage1 | `9eb77be` |
| 5.3  | Qwen3-TTS adapter scaffolding + TTS ABC + save_wav | `dfcdd02` |
| 5.5  | TTS router (config-driven persona+lang → engine+sample, cached engines) | `28fc212` |
| 5.6  | Chatterbox adapter for JARVIS-English; factory wires it | `f2793b1` |
| 5.7  | Whisper Large v3 via faster-whisper | `264594b` |
| 5.8  | 3-tier contextual biasing (system + user + session-NER context) | `0b97f86` |
| 5.10 | Session lock with multi-speaker policy + can_approve | `00cae37` |
| 5.11 | PIN / passphrase fallback (AuthHasher ABC + bcrypt + stub) | `e7a24f1` |
| 5.13 | FallbackChain + tts_fallback_log + voice approval/delivery channels | `8ba40c5` |
| 5.4  | JARVIS sample directory + consent record + inspection CLI | `66c65f4` |
| 5.5* | `newton voice tts` verification CLI + cloning doc | `744a2e5` |
| —    | This summary + tag `v0.5.0-block5` | (this tag) |

*5.5 split: routing landed first in the original sequence; the
verification CLI followed once JARVIS samples + consent were on disk.*

## Key design decisions (locked)

These shape every following block.

**Strategy D, voice variant.** Heavy model libs (torch, silero_vad,
sounddevice, openwakeword, qwen_tts, chatterbox, faster_whisper,
bcrypt) are *only ever* imported inside a method body, not at module
load. Every adapter that wraps a model exposes an injectable `loader`
callable so tests pass a stub and never touch the real package or
weights. The contract is asserted in tests: each adapter has a
`test_<engine>_does_not_import_*_at_construction` that pops the
module from `sys.modules` before constructing and asserts it stays
gone.

**Models load. Audio doesn't.** There is no audio hardware path in
the test suite. `MicSource.start()` is the only place that would
touch `sounddevice`, and no test calls it. Everything else uses
`ListSource` or `FileSource` (stdlib `wave` only).

**Routing is config-driven; the factory is the one place engines are
named.** `TTSRouter` is string-keyed over the YAML; the
`default_engine_factory` translates names → concrete classes.
Adding a new TTS engine is "drop a class, add one elif branch."
The router never grows special cases.

**Storage markers are one helper's job.** Block 4's `display_text`
strips both the alert `[kind]` prefix and the recall `[recall:N]`
marker before *any* user-facing surface — including the new
`VoiceDeliveryChannel`. Tests assert the absence on every render
path.

**Session lock is the auth seam.** `VoiceApprovalChannel.request()`
asks `SessionLock.can_approve(user_id, now)` *first*; if the lock
isn't held by the caller, the channel never speaks the prompt. PIN /
passphrase fallback is a separate path the runtime invokes on Voice
ID failure — that orchestration is not this block's job.

**The TTS fallback chain logs but doesn't loop forever.** Every
failure triggers a `tts_fallback_log` row; the chain advances to the
next engine; the terminal `_TextOnlyTTS` always succeeds. Tests
cover OSError / RuntimeError / MemoryError + timeout + silence
ratio + empty-list fast path.

**Single-reference cloning for v1.** The router takes one voice
reference per `(persona, language)`. Multi-sample averaging is
deferred. If quality forces a change, the YAML entry becomes a
directory and the adapter picks; tests for that path land alongside
the change.

**Three voice uses, three storage paths, never mixed.** Persona TTS
samples (donor) under `data/voices/<persona>/samples/`. Voice ID
enrollment (sir / gf) in `users.voice_embedding`. STT corpus
(sir's wake-after-wake utterances) under `data/stt-corpus/`. The
protocol doc enforces this in writing; the consent record per
persona keeps the paper trail.

## What you can do after this block

```bash
# Voice samples
uv run newton voice samples list jarvis        # WAV inventory
uv run newton voice samples show jarvis        # consent + counts

# Biasing (vault-driven; existed since 3.9 — now also feeds STT)
uv run newton voice biasing show --user sir

# Zero-shot cloning verification
uv run newton voice tts --persona jarvis --lang ko \
    --text "안녕하십니까, sir."
# Prints a clear error path when the models / weights / samples
# aren't yet in place. With the installs from
# docs/newton/voice-cloning-verification.md, produces a WAV at
# /tmp/newton-voice-<timestamp>.wav.
```

## Verification

Block-5 acceptance criteria, as far as no-audio testing can take them:

- `uv run newton init` applies migrations 001 through 011; idempotent.
- Every voice adapter constructs without its heavy backend installed
  and tests assert the import stays absent until the lazy path runs.
- The TTS router correctly resolves jarvis-ko, jarvis-en, butler-any,
  friday-ko, friday-en against the shipped `config/voice.yaml`; the
  `voice tts` smoke produces a clear, actionable error for each
  missing piece (no route / missing sample / missing model package /
  missing weights).
- `tts_fallback_log` writes one row per transition; announcement
  fires at most once per chain instance.
- `parse_yes_no` covers the documented ko + en vocab and treats
  ambiguous input as denied.
- `SessionLock` enforces 30 s timeout, first-call-wins on
  simultaneous wake-ups, and `can_approve` only when caller matches
  the locked user.
- `verify_pin` / `verify_passphrase` round-trip with the bcrypt
  hasher (when bcrypt is installed — tests skip cleanly otherwise).
- The JARVIS consent record is committed and parses; the audio
  itself is gitignored, with 15 English + 16 Korean takes confirmed
  on disk by the `samples show` CLI.
- `uv run pytest tests/newton/` reports **623 passed**, 4 skipped
  (2 spaCy NER models, 2 bcrypt), 39 deselected (`qdrant` /
  `embedding` marker tests; Docker required).
- OpenJarvis files: still zero modifications.

## Known limits (resolved in later steps / blocks)

- **No real LLM produces conversation responses yet.** The TTS path
  takes text and synthesizes; the text itself comes from the LLM
  orchestrator that lives in a later block. The path is wired —
  the orchestrator just isn't.
- **The 3-tier auth cascade isn't a state machine.** `verify_pin` /
  `verify_passphrase` exist; the runtime that drives Voice ID →
  PIN → passphrase belongs to a future step alongside session
  startup.
- **The TTS fallback chain has no HUD output.** Text-only fallback
  emits a `TTSResult` tagged via `engine_used == "text_only"`; the
  HUD wiring lands in block 11.
- **`voice tts` doesn't play audio.** It writes the WAV;
  CLI-side playback is `aplay` / `paplay` on sir's box (documented
  in the verification doc).

## Deferred — pending human input

The three steps that need recordings or real-time audio sir doesn't
have yet are explicitly out of this tag:

- **5.9 — Voice ID enrollment + recognition.** Needs sir's *own*
  voice (separate from the donor recordings used here). The
  Resemblyzer adapter is not yet scaffolded; happy to ship it
  with the same lazy-loader pattern when sir is ready to record.
- **5.12 — Custom wake-word training.** Optional per the doc; only
  if pretrained openWakeWord patterns sound poor against sir's
  voice. Defer until sir has a chance to A/B the pretrained
  patterns.
- **Meeting mode (diarization + realtime transcription + action
  items).** Code can be scaffolded the same way as TTS — pyannote
  adapter with injectable loader, action-item LLM seam — but
  verification needs a real recorded meeting. Defer.

When sir is ready for any of those, the existing adapters' lazy +
injectable-loader pattern is the template; the integration is
one PR-sized change away.

## Entry conditions for block 6

Block 6 (Vision Layer) can assume:

- The voice stack's TTS + STT routes are configuration-driven and
  testable without audio hardware.
- Block 2's `ApprovalChannel` has a voice implementation; block 4's
  `DeliveryChannel` has a voice implementation; both are gated by
  the session lock.
- Migration 011 (`tts_fallback_log`) is applied; block 4's
  proactive monitoring can read fallback frequency if it needs to
  spot a degrading engine.
- The donor-recording / voice-ID / STT-corpus three-way storage
  split is documented and enforced by the protocol doc.

If `newton status` reports everything green and
`uv run pytest tests/newton/` shows 623 unit passes (plus 39 marker
tests with Docker up), block 6 is good to start.
