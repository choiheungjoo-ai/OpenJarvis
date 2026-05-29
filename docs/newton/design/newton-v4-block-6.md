# Newton v4 — Block 6: Vision Layer (Face / Expression / Screen / Ambient)

> Master plan: `newton-v4-master.md`
> Tech stack: `newton-v4-tech-stack.md`
> JARVIS gap analysis (vision capabilities): `newton-v4-jarvis-gap.md` §3.2, §3.3, §3.11
> Terminology: `TERMINOLOGY.md`
> Prerequisite: Block 5 complete (`v0.5.0-block5`, `docs/newton/block-5-summary.md`)
>
> **Goal:** Give Newton eyes. Face recognition for Path B of 2-stage
> activation, expression awareness for tone modulation, screen awareness
> for context, ambient awareness for room state.

---

## 0. Block 6 — overall goals

Four awareness subsystems wired together:

1. **Face detection + recognition** — MediaPipe Face for fast bounding
   boxes + InsightFace for identity matching. Closes the Path B half of
   2-stage activation (face binding → user's default persona).
2. **Expression recognition** — DeepFace 7-emotion classifier. Output
   weakly biases response tone (informational, not deterministic).
3. **Screen awareness** — periodic screenshot + Vision LLM (Qwen 2.5 VL)
   analysis. Privacy-masked. Hooks into Block 4 scheduler for
   "you've been on the same screen for 5 min" type alerts.
4. **Ambient awareness** — periodic camera + microphone background
   analysis. Detects sir present / alone / with someone, lighting level,
   ambient noise. Used by Block 4 for context-aware proactive logic.

Plus the bridge work:

- `FaceBindingSignal` produced here is consumed by Block 3's persona
  engine for Path B activation
- Screen + ambient observations feed Block 4's `Context` assembler
- Vision LLM provider plugs into Block 2's provider registry

### Locked decisions (entering Block 6)

| Item | Decision | Source |
|------|----------|--------|
| **Face detection** | MediaPipe Face (Apache 2.0) | tech-stack.md |
| **Face recognition** | InsightFace (Apache 2.0 library; ArcFace model) — commercial weight licensing checked here | tech-stack.md note |
| **Expression** | DeepFace (MIT), 7 emotions | tech-stack.md |
| **Vision LLM** | Qwen 2.5 VL 7B default; 32B dynamic swap | master.md §4 |
| **Screen capture** | mss (MIT) | tech-stack.md |
| **Camera source** | USB webcam (sir's existing desk camera) | master.md §10 |
| **Screen awareness default** | enabled with privacy masks; sir can disable anytime | jarvis-gap.md §3.2 |
| **Ambient awareness default** | 5-minute camera analysis interval; can be disabled | jarvis-gap.md §3.3 |
| **Privacy masks** | password fields blurred; configurable app exclusion list (`1password`, `banking`, etc.); paused during video calls | jarvis-gap.md §3.2 |
| **Screen capture retention** | 24 hours then auto-delete (extracted summary text retained longer) | this block |
| **InsightFace weight license** | personal use only confirmed by sir; commercial deployment requires re-check | tech-stack.md §5 |
| **Face binding scope** | both sir and gf can be bound; Butler activates if neither face recognized | master.md §1.3 |
| **Vision LLM provider** | registered as `vision.llm` capability; default 7B; sir can swap to 32B via `newton providers swap` | block 2 pattern |

### Completion criteria (block as a whole)

```bash
# Face recognition end-to-end
$ uv run newton vision face enroll sir
[camera shows sir, capture 5s of frames]
face embedding stored in users.face_embedding

$ uv run newton vision face identify
[camera frame analyzed]
match: sir (confidence 0.91)

# Path B of 2-stage activation
$ uv run newton persona route --user sir --face-stage2
persona: jarvis (sir's default)
[block 3 persona engine returns activation]

# Expression
$ uv run newton vision emotion
[camera frame]
emotion: focused (confidence 0.78)

# Screen awareness
$ uv run newton vision screen capture --analyze
saved: data/screen/2026-07-10-T1430.png (masked)
analysis: "VS Code editor open with Python file. Terminal showing pytest output."

# Ambient
$ uv run newton vision ambient
people_present: 1 (sir)
lighting: dim (40 lux estimated)
ambient_sound: quiet

# Screen awareness scheduled (Block 4 integration)
$ uv run newton proactive patterns list | grep screen
context: "same_screen_5min" (3 occurrences) → suggests break

# Provider hot-swap demo
$ uv run newton providers list | grep vision
capability=vision.llm
  * active   qwen-2.5-vl-7b (free, local)
            qwen-2.5-vl-32b (free, local; ~18GB VRAM)

$ uv run newton providers swap vision.llm qwen-2.5-vl-32b --once
# next vision call uses 32B for high-detail analysis

# Tests
$ uv run pytest tests/newton/ -v
# Blocks 1-5: ~318 + Block 6: ~70 = ~388 passed
```

Block 6 makes Newton *see*. Combined with Block 5's *talk*, Newton is
now sensing + responding through both channels.

---

## 1. Block 6 — 10 steps

Each step: one focused change, one verification, one commit.
`ruff check` + `ruff format` clean before commit.

Estimated total: **12–18 days at sir's pace.** Lighter than block 5
because most components are off-the-shelf models with thin wrappers.

---

### Step 6.1 — Camera source + MediaPipe Face detection (1 day)

**Goal:** Capture frames from the USB webcam, detect face bounding boxes
in each frame.

**Outputs:**

- `newton/vision/camera.py` — USB webcam wrapper (opencv-python)
- `newton/vision/face_detector.py` — MediaPipe Face wrapper
- `tests/newton/vision/test_camera.py`
- `tests/newton/vision/test_face_detector.py`

**Dependencies:**

```bash
uv add opencv-python mediapipe
```

**Verification:**

```bash
uv run python -m newton.vision.camera --preview 5
# opens preview window (or saves frames to /tmp/) for 5s

uv run python -m newton.vision.face_detector --frames 30
# detects faces in 30 frames, prints bounding boxes

uv run pytest tests/newton/vision/test_face_detector.py -v
```

**Risk:** USB webcam on WSL2 needs USBIPD-WIN passthrough.
**Mitigation:** `scripts/newton/setup-camera.md` documents the setup.

**Commit:** `feat(vision): camera source + MediaPipe Face detection`

---

### Step 6.2 — InsightFace face embeddings + identity store (1 day)

**Goal:** Generate face embeddings via InsightFace (ArcFace). Store
enrolled faces in `users.face_embedding`.

**Outputs:**

- `newton/vision/face_id.py`
  - `enroll(user_id, frames)` — captures ~5 s, computes mean embedding
  - `identify(frame, threshold)` — matches against enrolled users
- `newton/cli.py` — `newton vision face enroll <user_id>`, `newton vision face identify`
- `tests/newton/vision/test_face_id.py`

**Dependencies:**

```bash
uv add insightface onnxruntime-gpu
```

**Verification:**

```bash
# Enrollment (sir sits in front of camera)
uv run newton vision face enroll sir
# 5 seconds of frames captured, mean embedding stored
# users.face_embedding populated

# Identification
uv run newton vision face identify
# match: sir (confidence 0.91)

# Stranger
# (someone else sits in front)
uv run newton vision face identify
# no match (top confidence: 0.42)

uv run pytest tests/newton/vision/test_face_id.py -v
```

**Risk:** InsightFace model weights have commercial-use restriction
clauses on some checkpoints. **Mitigation:** sir confirmed personal use
only. If Newton ever leaves personal use, swap to `face_recognition`
library (dlib, MIT) — note in tech-stack.md §5 already covers this.

**Commit:** `feat(vision): InsightFace identity enrollment and matching`

---

### Step 6.3 — Path B of 2-stage activation: FaceBindingSignal (half-day)

**Goal:** Wire face identification into Block 3's persona engine. When
sir's face is recognized, the system activates sir's default persona
without requiring a wake word.

**Outputs:**

- `newton/vision/face_binding.py`
  - watches camera continuously (or on-demand)
  - on confident face match (>= active retry profile threshold) →
    emits `FaceBindingSignal(user_id, confidence)`
- Integration with `newton.persona.engine.route()` (block 3)
- `tests/newton/vision/test_face_binding.py`

**Flow recap (master.md §1.3):**

```
Stage 1: clap or "Newton" wake word
    ↓
Stage 2 Path A: voice naming + Voice ID (block 5)
Stage 2 Path B: face recognition (this step) ← NEW
    ↓
Persona activated for that user
```

**Implementation:**

```python
class FaceBindingWatcher:
    """Background camera loop. Emits FaceBindingSignal when sir or gf appears."""
    async def run(self):
        while not stopped:
            frame = camera.capture()
            user_id, conf = face_id.identify(frame)
            if user_id and conf >= active_threshold():
                signal = FaceBindingSignal(user_id=user_id, confidence=conf)
                persona_activation = persona_engine.route(user_id, signal)
                await emit_activation(persona_activation)
            await asyncio.sleep(camera_interval)
```

`active_threshold()` reads from `users.retry_profile` (strict 0.85,
normal 0.7, relaxed 0.6 — from master.md §3.5).

**Verification:**

```bash
# Start watcher
uv run newton vision face watch &

# sir sits in front of camera
# expect: JARVIS persona activates (via stage 1 was clap or just face if test mode)
sqlite3 data/newton.db "SELECT persona_id, user_id, started_at FROM sessions ORDER BY started_at DESC LIMIT 1"
# jarvis | sir | <recent timestamp>

uv run pytest tests/newton/vision/test_face_binding.py -v
```

**Commit:** `feat(vision): Path B activation — face binding signal`

---

### Step 6.4 — DeepFace expression recognition (1 day)

**Goal:** Detect sir's expression (happy / sad / angry / surprised /
focused / neutral / disgusted). Feed weakly into response tone.

**Outputs:**

- `newton/vision/emotion.py` — DeepFace wrapper, 7-emotion output
- Schema row in `emotion_log` (table exists from block 1)
- `newton/cli.py` — `newton vision emotion [--continuous]`
- `tests/newton/vision/test_emotion.py`

**Dependencies:**

```bash
uv add deepface
```

**Behaviour:**

- Per frame: emotion + confidence
- Smoothing: report dominant emotion over a 3-second window
- `emotion_log` row written every 30 s (downsampled — full-rate is too noisy)

**Persona integration (informational, not deterministic):**

When JARVIS / Friday generate a response, they may consult the latest
`emotion_log` row:

```
sir's emotion (last 30s): focused (0.78)
→ persona prepends to system prompt:
  "Context: the user is focused. Be concise. Avoid pleasantries."

sir's emotion (last 30s): tired (0.65)
→ persona prepends:
  "Context: the user appears tired. Be warm. Suggest break if appropriate."
```

This is *advisory*. Persona may ignore if topic demands it.

**Privacy:** emotion data is per-user ACL'd; gf cannot see sir's
emotion log and vice versa.

**Verification:**

```bash
uv run newton vision emotion
# emotion: focused, confidence: 0.78

uv run newton vision emotion --continuous --duration 30
# emotion stream every 3s

sqlite3 data/newton.db "SELECT emotion, COUNT(*) FROM emotion_log GROUP BY emotion"
# distribution of emotions logged
```

**Commit:** `feat(vision): DeepFace expression recognition with emotion_log`

---

### Step 6.5 — Vision LLM provider (Qwen 2.5 VL 7B / 32B) (1 day)

**Goal:** Wrap Qwen 2.5 VL as a Block 2 provider for the `vision.llm`
capability.

**Outputs:**

- `newton/providers/builtin/qwen_vl_7b.py` — default
- `newton/providers/builtin/qwen_vl_32b.py` — dynamic swap option
- Both registered against capability `vision.llm`
- `tests/newton/providers/test_vision_llm.py`

**Provider implementations:**

```python
class QwenVL7B(Provider):
    name = "qwen-2.5-vl-7b"
    capability = "vision.llm"
    cost_model = "free"
    vram_gb = 6

    async def execute(self, request: VisionRequest) -> VisionResponse:
        # Sends image + prompt to local Ollama with qwen2.5-vl:7b
        ...

class QwenVL32B(Provider):
    name = "qwen-2.5-vl-32b"
    capability = "vision.llm"
    cost_model = "free"
    vram_gb = 18  # requires main LLM swap-out
```

**Hot-swap demo:**

```bash
uv run newton providers list | grep vision
# capability=vision.llm
#   * active   qwen-2.5-vl-7b (free, local, 6GB)
#              qwen-2.5-vl-32b (free, local, 18GB - swap)

uv run newton providers swap vision.llm qwen-2.5-vl-32b --once
# next vision query uses 32B; main LLM evicted to make room; reloaded after
```

**Verification:**

```bash
uv run newton tools run vision_describe --args '{"image_path":"/tmp/test.png"}'
# {"description": "A desk with a laptop showing VS Code..."}

uv run pytest tests/newton/providers/test_vision_llm.py -v
```

**Commit:** `feat(vision): Qwen 2.5 VL providers (7B default, 32B swap)`

---

### Step 6.6 — Screen capture + privacy masking (1.5 days)

**Goal:** Periodic screenshot of the active display, with sensitive
content masked before any analysis.

**Outputs:**

- `newton/vision/screen/capture.py` — mss wrapper
- `newton/vision/screen/privacy.py` — masking rules
- `migrations/010_screen_capture_extension.sql` — extends `screen_captures` if needed (block 1 schema may need fields)
- `newton/cli.py` — `newton vision screen capture [--analyze]`
- `tests/newton/vision/test_screen.py`

**Dependencies:**

```bash
uv add mss
```

**Privacy masking rules (jarvis-gap.md §3.2):**

```yaml
screen_privacy:
  always_mask:
    - password_field          # detect via heuristic + Vision LLM hints
    - credit_card_pattern     # 4-4-4-4 regex on OCR pass
    - ssn_pattern             # 6-digit-7 pattern (Korean RRN)
  excluded_apps:              # never capture these windows
    - 1password
    - banking_apps            # configurable list
  paused_during:
    - video_call_active       # detect via process list
  user_can_disable: anytime   # newton vision screen off
```

**Retention:**

- Raw screenshot images: 24 hours then auto-delete (`purge_after` in
  `screen_captures` row)
- Extracted text summary (Vision LLM output): retained per ACL (default:
  sir-only, 30 days)

**Flow:**

```
mss captures active display
    ↓
detect excluded apps (process list)? → skip
detect video call active? → skip
    ↓
privacy mask:
    OCR pass identifies password fields → blur
    regex pass identifies card numbers → blur
    ↓
save masked image to data/screen/<timestamp>.png (24h TTL)
    ↓
[if --analyze flag] Vision LLM → text summary
    ↓
INSERT screen_captures (analysis_summary, is_sensitive, purge_after)
```

**Verification:**

```bash
uv run newton vision screen capture --analyze
# masked screenshot saved; summary printed:
# "VS Code editor with Python file. Terminal shows test output."

# Try while a banking app is foreground
# → skipped, no row written
```

**Commit:** `feat(vision): screen capture with privacy masking`

---

### Step 6.7 — Screen awareness scheduler (Block 4 integration) (1 day)

**Goal:** Periodic screen captures feed Block 4's pattern learner and
trigger proactive notifications.

**Outputs:**

- `newton/vision/screen/scheduler.py` — adds a periodic task to Block 4's daemon
- Triggers from jarvis-gap.md §3.2:
  - `on_error_dialog`: detect via Vision LLM → "Sir, I see an error dialog. Help?"
  - `on_long_idle`: 5 minutes same screen content → "Sir, stuck? Want me to look?"
  - `on_request`: sir says "JARVIS, what's on my screen" → analyze + describe
- `tests/newton/vision/test_screen_scheduler.py`

**Pattern feeds into Block 4:**

Screen activity becomes a context source. Block 4 pattern learner can
detect things like:

```
context: "VS Code + pytest fail message for >2 min" + sir gestures suggest frustration
→ pattern action: "suggest reading the error message together"
```

**Verification:**

```bash
# With Block 4 daemon running
uv run newton vision screen on  # enables screen scheduler

# Simulate "stuck on same screen" pattern by holding a static screen
# After 5 min:
# proactive notification fires (via VoiceDeliveryChannel if voice up,
# else CLI / desktop)

uv run pytest tests/newton/vision/test_screen_scheduler.py -v
```

**Commit:** `feat(vision): screen awareness scheduler tied to Block 4`

---

### Step 6.8 — Ambient awareness: camera + microphone background (1 day)

**Goal:** Lower-frequency room-state monitoring. "Is sir in the room?
Alone or with someone? Is the room well-lit? Is there background noise?"

**Outputs:**

- `newton/vision/ambient/__init__.py`
- `newton/vision/ambient/visual.py` — camera-based room analysis
  (people count, lighting estimation)
- `newton/vision/ambient/audio.py` — microphone background level + music
  detection (re-uses Block 5's audio source)
- `newton/cli.py` — `newton vision ambient`
- `tests/newton/vision/test_ambient.py`

**Visual analysis (every 5 minutes):**

- MediaPipe Face count → "0 people / 1 person (sir) / 2+ people"
- Brightness histogram → lighting level estimate
- Time-of-day correlation → "lights on" / "lights off" classification

**Audio analysis (every 5 minutes):**

- 10-second sample
- RMS level → quiet / normal / loud
- Optional Vision LLM analysis of audio mood / music presence (advanced)

**Stored as:**

Block 1's `system_metrics` table is repurposed for ambient signals:

```sql
-- existing system_metrics table
INSERT INTO system_metrics (metric_type, value, captured_at)
VALUES ('ambient.people_count', 1, now),
       ('ambient.lighting_level', 40, now),     -- lux estimate
       ('ambient.audio_rms', 0.05, now);        -- 0-1 scale
```

**Block 4 integration:** these metrics become available for context-based
patterns:

```
context: "sir alone + dim lighting + 21:00+"
→ pattern action: "winding down — soften proactive notification cadence"
```

**Verification:**

```bash
uv run newton vision ambient
# people_present: 1 (sir)
# lighting: dim (estimated 40 lux)
# ambient_sound: quiet (rms 0.04)

uv run newton vision ambient --continuous --duration 60
# samples every 5s for 60s (test mode; production is 5 min)

uv run pytest tests/newton/vision/test_ambient.py -v
```

**Commit:** `feat(vision): ambient awareness (camera + microphone)`

---

### Step 6.9 — Security monitoring hooks (1 day)

**Goal:** From jarvis-gap.md §3.11 — Newton flags unknown faces,
multiple unknown faces, sir's prolonged absence, etc.

**Outputs:**

- `newton/vision/security.py`
  - `on_unknown_face_detected()` → proactive notification
  - `on_multiple_unknown_users()` → higher-priority notification
  - `on_sir_absence_long(threshold_hours)` → wellness check
- Tied into block 4 alerts
- `tests/newton/vision/test_security.py`

**Default settings:**

```yaml
security:
  unknown_face_alert: true
  multiple_unknown_threshold: 2
  sir_absence_alert_hours: 12     # only notify on activation, not as proactive
  failed_auth_attempts_alert: 3   # from block 1 auth_attempts
```

**Verification:**

```bash
# Simulate unknown person in front of camera
# After 30s of repeated unknown matches:
# notification logged:
# "Sir, unknown person detected at camera (5 frames, last 30s)"

uv run pytest tests/newton/vision/test_security.py -v
```

**Commit:** `feat(vision): security monitoring hooks`

---

### Step 6.10 — Block 6 summary + tag (1–2 hours)

**Goal:** Lock the block; define Block 7 entry conditions.

**Outputs:**

- `docs/newton/block-6-summary.md`
- `docs/newton/cli.md` — final pass
- `README.md` — Block 6 marked complete
- Git tag: `v0.6.0-block6`

**Block 7 entry conditions (provisional):**

- `newton vision face enroll/identify` works
- Path B of 2-stage activation operational (face → persona)
- Expression recognition logs to `emotion_log`
- Vision LLM provider works (7B default, 32B swap)
- Screen capture with privacy masking
- Ambient awareness logs to system_metrics
- Security hooks fire on unknown face
- Block 4 daemon can read screen + ambient signals
- All pytest cases pass (~388 total)
- Preflight 9/9 still ✓
- OpenJarvis: still 0 files modified

**Commit + tag:** `chore: block 6 complete`

---

## 2. Deliberately not in Block 6

- ❌ **Gesture recognition** — block 8 (uses MediaPipe Hand, separate from Face)
- ❌ **3D Brain visualization** — block 11
- ❌ **Real-time translation overlay** — block 7 (uses Vision LLM but for OCR not for awareness)
- ❌ **OCR for document scanning** — block 7
- ❌ **Specific app integrations** (Slack bot listening, etc.) — block 9
- ❌ **Long-term face memory of guests** — guests are guests; their faces are quarantined per master.md §3.3 design

---

## 3. Risk matrix

| Risk | Impact | Mitigation |
|------|--------|-----------|
| USB webcam on WSL2 not passthrough | High | USBIPD-WIN setup documented; smoke test in step 6.1 |
| InsightFace weight licensing for future commercial use | Med | Personal use confirmed; switch to face_recognition lib if needed |
| Privacy mask false negatives (passwords leaked into screenshots) | High | Multi-pass detection; sir can audit captures; 24h TTL on raw images |
| Expression recognition wrong → wrong tone | Low | Advisory only; persona may ignore |
| Continuous camera = battery drain on laptop | Med | Reduce interval on battery; pause when face away >5 min |
| Vision LLM swap takes time (memory eviction) | Med | Async; one-shot swap returns after vision call completes |
| Ambient noise classification false positives (TV = "loud music") | Low | Advisory; no critical decisions depend on this |
| Security alerts annoying after time | Med | Reaction learning (block 4) suppresses repeat false alarms |
| Face binding fires when sir glances at camera mid-task | Med | Requires sustained match (>= 3 s) before signal emits |
| 12–18 day estimate uncertain | Med | Most steps are wrapper code over known models; estimate is realistic |

---

## 4. After Block 6 — opening message for the next chat

```markdown
# Newton v4 — Block 7 start (Search + OS + Translation + Autoresearch)

## Context
- Newton: multi-persona AI OS, OpenJarvis fork
- Environment: RTX 5090 + WSL2 Ubuntu + systemd
- Location: ~/newton-v4/

## Design docs
[newton-v4-master.md]
[newton-v4-tech-stack.md]
[newton-v4-engines.md]    # block 7 capability matrix
[newton-v4-block-6.md]    # complete
[newton-v4-block-7.md]    # this block
[TERMINOLOGY.md]

## Blocks 1–6 result
- v0.6.0-block6: vision layer
  - Face recognition + Path B activation
  - Expression + ambient awareness
  - Screen awareness with privacy masking
  - Security monitoring hooks
  - Vision LLM provider (7B/32B)

## Next
Block 7 step 7.1 — SearXNG provider.
```

---

## 5. Honest reality check

**Time estimate:** **12–18 days at sir's pace.** Lighter than block 5
because more of the work is wrapping existing models.

**Riskiest steps:**

- **Step 6.6** (privacy masking) — false negatives leak passwords. Test
  paranoidly.
- **Step 6.2** (InsightFace) — licensing footnote needs sir's confirmation
  if Newton ever leaves personal use.

**Simplest steps:**

- 6.1, 6.4, 6.5, 6.9 — wrapper code

**Most important step:**

- **Step 6.3** (Path B activation). This is the second half of how sir
  interacts with Newton. Mistakes here are user-visible immediately.

**Behavioural shift:**

After block 6, sir can sit at the desk and Newton activates the right
persona automatically. Combined with block 5, the system feels closer
to JARVIS: ambient, attentive, considerate of sir's expressions.

**Assets carried over:**

- `users.face_embedding` (column exists from block 1)
- `emotion_log` (table from block 1)
- `screen_captures`, `system_metrics` (tables from block 1)
- Block 2 ProviderRegistry → `vision.llm` capability
- Block 3 persona engine → consumes `FaceBindingSignal`
- Block 4 scheduler → consumes screen + ambient signals
- Block 5 audio source → reused by ambient audio analysis
- ~318 pytest cases must still pass

---

## 6. Starting checklist

Before Block 6 begins:

- [ ] Block 5 tagged `v0.5.0-block5`, `newton status` green
- [ ] Pytest ~318 passing
- [ ] USB webcam connected and visible to WSL2 (USBIPD-WIN configured)
- [ ] InsightFace model files can be downloaded (~500 MB)
- [ ] Qwen 2.5 VL 7B downloaded (~6 GB)
- [ ] Qwen 2.5 VL 32B downloaded (~18 GB; optional, can defer)
- [ ] DeepFace dependency footprint understood (~1 GB)
- [ ] `mss` and `opencv-python` install successfully on this Python
- [ ] sir willing to enroll face (1 minute of frames)
- [ ] Personal-use license footnote acknowledged

---

Ready when sir is. Step 6.1 is the entry point.
