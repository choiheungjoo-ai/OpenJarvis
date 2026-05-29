# Newton v4 — Terminology

Canonical English vocabulary for all Newton v4 documentation, code, schema,
configuration, comments, and commit messages.

This file is the authority. When a translation choice arises, check here
first. When a new term is coined, add it here.

User-facing strings (TTS announcements, voice prompts, UI labels seen by
sir / Stella) may be Korean or English depending on persona language —
see voice.md for routing. But the *names of things* in the system are
always English.

---

## 1. People and personas

| Term | Meaning |
|---|---|
| `sir` | The primary owner of Newton. Addressed by JARVIS in British butler tone. Internal user id: `sir`. Display name (`Alex`) lives in `users.display_name`, never in committed config. |
| `Stella` | The partner. Internal user id: `gf`. Display name (`Stella`) lives in `users.display_name`, never in committed config. Documents use `${PARTNER_DISPLAY_NAME}` placeholder where the name would otherwise appear. |
| `guest` | An unrecognized user. May get limited access if `guest_mode_enabled = true`. Activity goes through the quarantine + JARVIS-briefing flow. |
| `persona` | One of the AI identities Newton presents — Butler, JARVIS, Friday. Each has its own voice, system prompt, and color. Owned by zero or one user. Stored in the `personas` table. |
| `Butler` | The default public persona. Welcomes unrecognized visitors. Engine: Qwen3-TTS 0.6B. No owner. |
| `JARVIS` | sir's personal persona. British butler tone. Engine: Qwen3-TTS 1.7B (Korean) / Chatterbox (English). Owner: `sir`. |
| `Friday` | Stella's personal persona. Warm, empathetic tone, Korean-first. Engine: Qwen3-TTS 1.7B. Owner: `gf`. |
| `voice sampler` | A person who records voice samples used to clone a persona's voice via Qwen3-TTS CustomVoice. Never sir or Stella themselves. Consent is recorded in `consent.md` per sample directory. |

---

## 2. Activation and identity

| Term | Meaning |
|---|---|
| `activate` | The verb for bringing a persona online for a session. `activate_persona(persona_id, user_id, session_id)`. Used in code, logs, and prompts. Preferred over invoke / summon / wake / call. |
| `wake word` | A spoken keyword that wakes the system. Examples: "Newton" (system-only), "JARVIS", "Friday" (persona-binding). Distinct from `clap trigger`. |
| `clap trigger` | A clap sound (or two-handed clap gesture) that wakes the system without speech. Equivalent to a wake word in terms of Stage 1 activation. Permission and detection channel decided per block 5/8. |
| `2-stage activation` | Newton's activation model. **Stage 1 (system wake):** clap trigger or "Newton" wake word — wakes the system but does not bind a persona. **Stage 2 (persona binding):** Path A — voice names a persona ("JARVIS"/"Friday") + Voice ID identifies user. Path B — Face ID identifies user, system activates that user's default persona. |
| `Voice ID` | Speaker recognition via Resemblyzer. Matches incoming audio against `users.voice_embedding`. Identifies who is speaking. |
| `Face ID` | Face recognition via InsightFace. Identifies who is in front of the camera. |
| `voice authentication` | Identity verification using Voice ID alone. Threshold-driven (strict/normal/relaxed profiles). |
| `face authentication` | Identity verification using Face ID alone. Same profile system. |
| `session lock` | After Stage 2 completes, Newton locks the session to one user. Other voices are filtered out for 30 seconds of inactivity. |
| `session` | A bounded conversation between one user and one persona. Stored in the `sessions` table (Python class `ChatSession` to avoid shadowing SQLAlchemy's `Session`). |

---

## 3. Data and storage

| Term | Meaning |
|---|---|
| `vault` | sir's markdown note repository. Lives under `data/vault/notes/`. Indexed for RAG. ACL-controlled per note. |
| `quarantine` | Isolation directory for guest-contributed content. Lives under `data/vault/_guest_quarantine/`. JARVIS auto-briefs sir on guest activity; sir decides accept / reject / promote / shared. |
| `ACL` | Access Control List. Per-note metadata stored in front-matter. Controls which users and personas may read or write a note. |
| `vault → biasing hook` | Block 3 feature. When a note is saved, named entities are extracted (Korean NER via spaCy) and added to the user's Contextual Biasing dictionary. STT accuracy improves automatically as the vault grows. |
| `long-term memory` | Auto-summarized conversation history saved into `vault/_auto/conversations/`. Enables proactive recall in block 4. |
| `STT corpus` | sir's accumulated speech, recorded automatically after wake word, used as training data for optional Whisper LoRA fine-tune in block 10. Stored under `data/voices/sir/stt_corpus/`. |
| `TTS sample` | Audio recorded by a voice sampler for a specific persona. Used as zero-shot clone reference at every TTS call. Stored under `data/voices/<persona>/samples/`. Multiple samples allowed per persona — same voice sampler, different sentences, for clone stability. One tone per persona (fixed accent / gender / age band). |
| `Voice ID sample` | A separate 10–15s recording of the actual user (sir or Stella), used only to generate the identity embedding stored in `users.voice_embedding`. Never reused for TTS. |
| `consent.md` | Per-sample-directory document recording the voice sampler's agreement to use their audio for a specific persona. Required for every TTS sample. Withdrawal triggers immediate sample deletion. |

---

## 4. Tools, providers, and capabilities

| Term | Meaning |
|---|---|
| `tool` | A Python function callable by an LLM. Has a name, args schema, returns schema, risk level, and an `execute(args, context) -> ToolResult` method. Registered in the `ToolRegistry`. Subject to approval policy. Defined in block 2. |
| `ToolResult` | The wrapper returned by every tool call. Carries `status` (ok / error / needs_approval / denied), `data`, `error`, `metadata`. |
| `risk level` | A tool's exposure rating. 0 = safe, 1 = read_local, 2 = write_local, 3 = read_network, 4 = write_network. Drives default approval policy. May be revised after block 2 step 2.1 investigation. |
| `approval policy` | The matrix that decides whether a tool call needs sir's approval. Keyed by (tool_name, persona_id, user_id) with cascading defaults. Stored in `tool_policies`. |
| `approval hook` | The dispatch-time check that consults the policy, optionally prompts sir, and logs every decision to `tool_approvals`. Defined in block 2 step 2.6. |
| `capability` | An abstract ability that may have multiple competing implementations. Examples: `web.search`, `vision.llm`, `email.send`. Hot-swappable. |
| `provider` | One implementation of a capability. Examples: SearXNG and Brave both provide `web.search`. Registered in `ProviderRegistry`. |
| `hot-swap` | Replacing the active provider for a capability without restarting Newton. Three scopes: `once` (next call only), `session` (process lifetime), `permanent` (DB-backed, survives restart). |
| `dry-run` | A tool dispatch mode that returns the would-have-been action without executing. Used for previews and tests that should not hit external systems. |

---

## 5. Permissions and scope

| Term | Meaning |
|---|---|
| `shared` | Resource scope: usable by any registered user. Applies to gestures, tools, and provider defaults. Replaces the Korean "공용" everywhere. Avoids confusion with `personas.is_public`. |
| `personal` | Resource scope: usable only by the owner. Applies to gestures and per-user policy overrides. The owner is identified at runtime via Voice ID / Face ID. |
| `public` (persona) | Persona attribute (`personas.is_public`). A public persona has no owner and is offered to unrecognized visitors. Distinct from `shared`. Currently only Butler is public. |
| `owner` | The user a persona belongs to. JARVIS owner = sir, Friday owner = gf, Butler owner = null. |

---

## 6. Proactive engine

| Term | Meaning |
|---|---|
| `proactive` | The mode of operation where Newton initiates rather than only responding. Modeled on movie JARVIS. Implemented in block 4. |
| `reactive` | The opposite: respond only when called. Newton can be put in this mode via `proactive_mode = off`. |
| `proactive mode` | One of `off` / `minimal` / `smart` (default) / `aggressive`. Sir can change at any time by voice. |
| `monitoring` | Block 4 sub-system. Watches CPU, GPU, memory, battery, temperature, network, screen content, calendar, room ambience. |
| `pattern recognition` | Block 4 sub-system. Learns sir's weekly / daily / contextual routines. Stored in `user_patterns`. |
| `anticipation` | Block 4 sub-system. Predicts likely next actions from patterns + current context. Drives proactive notifications. |
| `proactive recall` | Surfacing prior conversation or vault content unprompted when the current context matches a past one. |
| `quiet hours` | Configurable window during which proactive notifications are suppressed. Default: 23:00–07:00. |
| `nag prevention` | Throttling logic that limits how often Newton speaks up. Includes "rejected suggestions" learning. |

---

## 7. Voice subsystem

| Term | Meaning |
|---|---|
| `VAD` | Voice Activity Detection. Silero VAD. Filters silence from continuous mic input. |
| `STT` | Speech-to-text. Whisper Large v3 via faster-whisper. |
| `TTS` | Text-to-speech. Qwen3-TTS CustomVoice family + Chatterbox. |
| `Contextual Biasing` | Whisper's `initial_prompt` parameter, populated with three tiers: system terms, user terms, recent conversation entities. |
| `voice cloning` | Zero-shot reproduction of a persona's voice using a TTS sample as reference at every call. No fine-tuning required for the persona voice itself. |
| `voice donor` | (Synonym for `voice sampler`. Prefer `voice sampler` in new writing.) |
| `meeting mode` | A voice subsystem mode for multi-speaker meetings. Enables pyannote.audio diarization, real-time transcription, action-item extraction. Implemented in block 5. |
| `TTS fallback chain` | The three-step graceful degradation when the primary TTS engine fails. See voice.md §2.6.1. Korean: 1.7B → 0.6B → text-only. English: Chatterbox → Qwen3-TTS 1.7B → text-only. |
| `TTS fallback announcement` | A brief per-persona message (in the persona's language) spoken via the fallback engine to warn sir that voice tone may differ. Throttled to one announcement per session. |

---

## 8. Vision and gesture subsystems

| Term | Meaning |
|---|---|
| `screen awareness` | Periodic screenshot + Vision LLM analysis. Privacy-masked. Implemented in block 6. |
| `ambient awareness` | Periodic camera analysis + microphone background analysis. Room-level context (lighting, presence, ambient sound). Implemented in block 6. |
| `static gesture` | A hand shape recognizable in a single frame. Examples: fist, OK sign, V sign. Classifier: MediaPipe Gesture Recognizer + Model Maker. |
| `dynamic gesture` | A hand motion recognizable over a sequence of frames. Examples: wave, swipe, grab. Classifier: PyTorch LSTM, Newton-built. |
| `landmark` | A single hand keypoint from MediaPipe Hand. 21 landmarks per detected hand. |
| `UI control gesture` | A gesture that maps to an OS-level action (zoom, click, window switch) via pyautogui. Block 8. |
| `Brain gesture` | A gesture that controls the 3D Brain visualization (rotate, zoom, select node). Block 11. |
| `gesture mode` | The activation state of gesture recognition. Auto (idle context) / manual_on / manual_off. Block 8. |

---

## 9. Blocks and steps

| Term | Meaning |
|---|---|
| `block` | A self-contained phase of Newton construction. Newton has 11 blocks. Each block ends with a git tag like `v0.N.0-blockN`. |
| `step` | A subdivision of a block. Block 1 had 8 steps (1.1–1.8). Block 2 has 10 (2.1–2.10). One step = one focused change + one verification + one commit. |
| `entry conditions` | The acceptance criteria a previous block must meet before the next block can start. Listed at the end of each block summary. |
| `idempotency` | Property of a command that can be safely re-run with no side effects. Required of every mutating CLI command (`init`, `migrate`, `seed`). |
| `preflight` | The shell script under `scripts/newton/preflight.sh` that checks environment readiness. Currently 9 checks. |

---

## 10. Database conventions

| Term | Meaning |
|---|---|
| `ChatSession` | Python class for the `sessions` table. Named so it does not shadow SQLAlchemy's `Session`. |
| `naive UTC` | All `TIMESTAMP` columns are stored as naive UTC datetimes until block 4 introduces explicit `tzinfo` where needed. |
| `foreign keys enforced` | `PRAGMA foreign_keys = ON` is set on every SQLAlchemy connection via a `connect` event listener. Not optional. |
| `ON DELETE CASCADE` | Personal data (sessions, screen_captures, calendar) cascades when its user is deleted. |
| `ON DELETE SET NULL` | Audit / security records (auth_attempts, registration_requests) keep the trail but drop the personal pointer. |
| `ON DELETE RESTRICT` | Activity-blocking relations (sessions referencing a persona) prevent deletion of an in-use parent. |
| `${OWNER_DISPLAY_NAME}` | Placeholder in `personas.yaml` that is substituted at LLM-call time via `render_personality()`. Keeps real names out of git. |
| `${PARTNER_DISPLAY_NAME}` | Same idea, for Stella. Used wherever documents refer to the partner. |

---

## 11. Project conventions

| Term | Meaning |
|---|---|
| `OpenJarvis` | The upstream LLM-runtime project Newton forks. Newton never modifies OpenJarvis files. |
| `newton/` | Newton's Python package. Sibling to OpenJarvis code. |
| `--json` | A flag every data-printing CLI command supports. Stable contract for tooling. Human prose output is not a contract. |
| `thin CLI, thick library` | The architectural rule: CLI commands are short click wrappers; real logic lives in `newton.config`, `newton.db`, etc. so other surfaces (voice, web, MCP) reuse the same code. |
| `local-first` | Every component runs on sir's machine. Cloud APIs are opt-in only. Default monthly bill: zero. |

---

## 12. Deferred decisions

These terms or behaviors exist but the specific implementation is deferred:

- **Clap permission scope** — `shared` vs `sir-only`. Decided in block 5 or 8.
- **Clap detection channel** — audio (openWakeWord-trained clap pattern) vs vision (MediaPipe Hand two-hand convergence) vs both. Decided in block 5/8.
- **Risk level count** — currently 5 (0–4). May collapse to 4 or 3 after block 2 step 2.1 investigation.
- **Approval prompt channel** — block 2 uses blocking CLI input. Block 4+ may add voice / push / async.
- **InsightFace model weights commercial license** — decided in block 6 if Newton ever leaves personal use.

This section shrinks as decisions are made. Each resolved item moves into the relevant section above.
