# Newton v4 — Block 8: Motion + Gesture + UI Control

> Master plan: `newton-v4-master.md`
> Tech stack: `newton-v4-tech-stack.md`
> Gesture details: `newton-v4-gestures.md`
> Terminology: `TERMINOLOGY.md`
> Prerequisite: Block 7 complete (`v0.7.0-block7`, `docs/newton/block-7-summary.md`)
>
> **Goal:** Give sir hand control over Newton. Static gestures (wave,
> OK, fist), dynamic gestures (swipe, grab), UI control via pyautogui,
> mode-activation defense, visual feedback.

---

## 0. Block 8 — overall goals

Six concerns wired together:

1. **Static gestures** — single-frame hand shapes (fist, OK sign, V sign).
   MediaPipe Gesture Recognizer + Model Maker for custom training.
2. **Dynamic gestures** — multi-frame sequences (wave, swipe, grab).
   PyTorch LSTM, Newton-built.
3. **CRUD + permissions** — sir registers / modifies / deletes gestures.
   Scope = `shared` (everyone) or `personal` (owner only).
4. **UI control** — gestures map to pyautogui actions (zoom, click,
   window switch).
5. **B+C+D mode activation** — multi-layered defense against accidental
   triggers (explicit command + trigger + context-aware auto).
6. **Visual feedback** — overlay shows gesture mode state, recognized
   gestures, confidence.

3D Brain gestures (brain_rotate, brain_zoom, node grab) are deferred
to Block 11 because Block 11 builds the 3D Brain itself.

### Locked decisions (entering Block 8)

| Item | Decision | Source |
|------|----------|--------|
| **Hand tracker** | MediaPipe Hand (Apache 2.0) — 21 landmarks | tech-stack.md |
| **Static classifier** | MediaPipe Gesture Recognizer + Model Maker | tech-stack.md |
| **Dynamic classifier** | PyTorch LSTM, Newton-built | tech-stack.md |
| **OS command bridge** | pyautogui (BSD) — already used in Block 7 | tech-stack.md |
| **Permission scope** | `shared` vs `personal` (TERMINOLOGY decision) | TERMINOLOGY |
| **Activation policy** | B+C+D layered defense (explicit + trigger + context auto) | master.md §1.6 |
| **Clap trigger handled in** | Block 5 (audio side) — vision-based clap could be added here but defer | master.md §1.3 |
| **Number of gestures** | unlimited; sir registers as needed | master.md §1.6 |
| **3D Brain gestures** | deferred to Block 11 (depends on Brain existing first) | gestures.md note |

### Completion criteria (block as a whole)

```bash
# Hand tracking
$ uv run newton gesture track --duration 5
21 landmarks per detected hand for 5s

# Static gesture registration
$ uv run newton gesture register thumbs_up --static --scope shared
[40 sample frames captured]
[training... done in 90s]
gesture 'thumbs_up' (id=1) registered, scope=shared

$ uv run newton gesture list
1. thumbs_up    (static, shared)   action: none yet
2. fist         (static, personal owner=sir)  action: pause_music
3. wave         (dynamic, shared)  action: stop_music
4. swipe_right  (dynamic, shared)  action: next_song

# Bind action
$ uv run newton gesture bind thumbs_up --action 'os_focus_app --args {"app":"VS Code"}'
gesture 1 bound: thumbs_up -> os_focus_app

# Runtime
$ uv run newton gesture watch &
# sir does thumbs_up
[recognized: thumbs_up (0.92)]
[action: os_focus_app({"app":"VS Code"})]
[approval] os_focus_app (risk: 1) -> auto_allow
[VS Code focused]

# Mode activation
$ uv run newton gesture mode auto         # B+C+D context-aware
$ uv run newton gesture mode manual_on     # always listening
$ uv run newton gesture mode manual_off    # ignore all

# Visual feedback overlay
$ uv run newton gesture overlay
[floating window: mode=auto, last_gesture=thumbs_up]

# Tests
$ uv run pytest tests/newton/ -v
# Blocks 1-7: ~498 + Block 8: ~95 = ~593 passed
```

After Block 8, sir can control Newton with hands — gesture-driven
voiceless commands, especially useful in meetings or while music plays.

---

## 1. Block 8 — 17 steps

Each step: one focused change, one verification, one commit.
`ruff check` + `ruff format` clean before commit.

Estimated total: **25–35 days at sir's pace (5–8 weeks).** The widest
block in step count.

These steps are adapted from `gestures.md` §9, renumbered for the new
block mapping (7.x → 8.x).

---

### Step 8.1 — MediaPipe Hand integration + 21 landmark verification (half-day)

**Goal:** Track hands in camera frames, output 21 landmarks per hand.

**Outputs:**

- `newton/gesture/hand_tracker.py` — MediaPipe Hand wrapper
- Reuses block 6's camera source
- `tests/newton/gesture/test_hand_tracker.py`

**Verification:**

```bash
uv run newton gesture track --duration 5 --preview
# preview window shows hand landmarks; 21 dots per detected hand
uv run pytest tests/newton/gesture/test_hand_tracker.py -v
```

**Commit:** `feat(gesture): MediaPipe Hand integration with 21 landmarks`

---

### Step 8.2 — Static gesture Model Maker setup (half-day)

**Goal:** Install MediaPipe Model Maker and train a baseline static
classifier with the 4 canned gestures (open_palm, closed_fist,
thumbs_up, victory).

**Outputs:**

- `newton/gesture/static/trainer.py` — Model Maker wrapper
- `newton/gesture/static/classifier.py` — inference wrapper
- `tests/newton/gesture/test_static_baseline.py`

**Dependencies:**

```bash
pip install mediapipe-model-maker
```

**Verification:**

```bash
uv run python -m newton.gesture.static.classifier --image /tmp/thumbs_up.jpg
# classification: thumbs_up (0.94)
```

**Commit:** `feat(gesture): static classifier baseline (Model Maker)`

---

### Step 8.3 — Static gesture registration flow (CLI) (1 day)

**Goal:** sir registers a new static gesture by capturing samples
through the CLI.

**Outputs:**

- `migrations/012_gestures_extended.sql` — extends block 1's `gestures` table with samples / action / scope fields
- `newton/models/gesture.py` — ORM
- `newton/gesture/registration.py` — capture sample frames, write to disk
- `newton/cli.py` — `newton gesture register <name> --static --scope shared|personal --samples 40`
- `tests/newton/gesture/test_registration.py`

**Extended schema:**

```sql
ALTER TABLE gestures ADD COLUMN scope TEXT NOT NULL DEFAULT 'personal';   -- 'shared' | 'personal'
ALTER TABLE gestures ADD COLUMN gesture_kind TEXT NOT NULL DEFAULT 'static'; -- 'static' | 'dynamic'
ALTER TABLE gestures ADD COLUMN owner_user_id TEXT;                       -- NULL = system-owned for shared canon
ALTER TABLE gestures ADD COLUMN action_json TEXT;                         -- bound tool call args
ALTER TABLE gestures ADD COLUMN samples_dir TEXT;                         -- relative path to sample frames
ALTER TABLE gestures ADD COLUMN trained_at TIMESTAMP;
ALTER TABLE gestures ADD COLUMN confidence_threshold REAL DEFAULT 0.7;
```

**Capture flow:**

```
sir runs: newton gesture register thumbs_up --static --scope shared --samples 40

countdown 3..2..1
    ↓
40 frames captured at 5 fps over 8 seconds
    ↓
sir holds the gesture, rotates hand slightly for diversity
    ↓
samples saved to data/gestures/<gesture_id>/samples/<n>.npy (landmarks only, no images)
    ↓
gesture row created with status='pending_training'
    ↓
[step 8.4 will pick it up for training]
```

**Verification:**

```bash
uv run newton gesture register thumbs_up --static --scope shared
# 40 sample sets saved
sqlite3 data/newton.db "SELECT name, gesture_kind, scope FROM gestures ORDER BY gesture_id DESC LIMIT 1"
# thumbs_up | static | shared
```

**Commit:** `feat(gesture): static registration flow + migration 012`

---

### Step 8.4 — Static training pipeline + hot-reload (1 day)

**Goal:** Train the Model Maker classifier on all pending static
gestures, swap in the new model without restart.

**Outputs:**

- `newton/gesture/static/training_pipeline.py`
- `newton/gesture/static/hot_swap.py` — atomic model file swap
- `newton/cli.py` — `newton gesture train static`
- `tests/newton/gesture/test_static_training.py`

**Pipeline:**

```
collect all rows where gesture_kind='static' AND samples_dir EXISTS
    ↓
write Model Maker training spec
    ↓
train (1-5 min depending on count)
    ↓
save to data/models/gestures/static-v<timestamp>.task
    ↓
atomic symlink update: data/models/gestures/static-active.task
    ↓
runtime classifier reloads the file (file watcher)
    ↓
gestures.trained_at = now
```

**Verification:**

```bash
uv run newton gesture train static
# trains on all pending static gestures
# new model active

uv run newton gesture track --classify
# runtime now recognizes the new gestures
```

**Risk:** Hot-reload races. **Mitigation:** atomic symlink swap; reader
side double-checks file mtime.

**Commit:** `feat(gesture): static training + hot-reload`

---

### Step 8.5 — Static gesture CRUD (1 day)

**Goal:** List / show / modify / delete gestures.

**Outputs:**

- `newton/cli.py` — gesture subcommands
  - `newton gesture list [--scope X] [--kind X]`
  - `newton gesture show <id>`
  - `newton gesture rename <id> <new_name>`
  - `newton gesture delete <id>`
  - `newton gesture retrain <id> --samples 40`  (re-capture sir's samples)
- `tests/newton/gesture/test_crud.py`

**Verification:**

```bash
uv run newton gesture list
# 4 gestures shown

uv run newton gesture rename 1 thumbs_up_focus
uv run newton gesture delete 2
uv run newton gesture train static    # rebuild after deletion
```

**Commit:** `feat(gesture): static CRUD operations`

---

### Step 8.6 — Permission scope enforcement (half-day)

**Goal:** Distinguish `shared` and `personal` gestures. Personal ones
only fire when the owner is recognized (via Voice ID or Face ID).

**Outputs:**

- `newton/gesture/scope.py`
- Runtime check: gesture recognized → if scope=personal, verify owner_user_id matches the currently identified user → otherwise ignore
- `tests/newton/gesture/test_scope.py`

**Behaviour:**

```
gesture 'wake' (shared)   → fires for anyone
gesture 'unlock' (personal owner=sir) → fires only when sir is identified
                                       → if gf shows the same gesture, ignored
```

**Verification:**

```bash
# Register a personal gesture
uv run newton gesture register secret_handshake --static --scope personal --owner sir

# Simulate: gf identified, does secret_handshake
# → no action fires

# Simulate: sir identified, does secret_handshake
# → action fires
```

**Commit:** `feat(gesture): shared/personal scope enforcement`

---

### Step 8.7 — Static gesture runtime + action dispatch (1 day)

**Goal:** Gesture recognition during continuous camera feed → dispatch
bound tool call via Block 2 ToolRegistry.

**Outputs:**

- `newton/gesture/runtime.py` — main loop
- `newton/cli.py` — `newton gesture watch` (background)
- `newton/cli.py` — `newton gesture bind <gesture_id> --action <tool>:<args>`
- `tests/newton/gesture/test_runtime.py`

**Action binding format:**

```bash
# Bind gesture to a tool call
newton gesture bind 1 --action 'os_focus_app:{"app":"VS Code"}'
# stores in gestures.action_json
```

**Dispatch flow:**

```
gesture recognized with confidence >= threshold
    ↓
read action_json
    ↓
parse: tool_name + args
    ↓
ToolRegistry.dispatch(tool_name, args, context=GestureContext(user_id))
    ↓
[Block 2 approval hook fires per tool risk]
```

**Verification:**

```bash
uv run newton gesture bind 1 --action 'os_focus_app:{"app":"VS Code"}'
uv run newton gesture watch &

# sir shows gesture 1
# expect: VS Code focused
```

**Commit:** `feat(gesture): static runtime + tool dispatch`

---

### Step 8.8 — Dynamic gesture LSTM design (1 day)

**Goal:** Design the sequence model. No training yet — just architecture
and synthetic data tests.

**Outputs:**

- `newton/gesture/dynamic/model.py` — PyTorch LSTM
- `newton/gesture/dynamic/sequence_format.py` — how a sequence is represented (T frames × 21 landmarks × 3 coords)
- `tests/newton/gesture/test_dynamic_model.py`

**Architecture sketch:**

```python
class DynamicGestureLSTM(nn.Module):
    def __init__(self, num_landmarks=21, coords=3, hidden=128, num_classes=10):
        super().__init__()
        self.input_size = num_landmarks * coords  # 63
        self.lstm = nn.LSTM(self.input_size, hidden, num_layers=2, batch_first=True)
        self.fc = nn.Linear(hidden, num_classes)

    def forward(self, x):                          # x: (B, T, 63)
        out, _ = self.lstm(x)                       # (B, T, 128)
        logits = self.fc(out[:, -1, :])             # (B, num_classes)
        return logits
```

**Sequence length:**

- Fixed 30 frames (≈1 second at 30 fps)
- Pad shorter sequences with last frame; truncate longer ones

**Verification:**

```bash
uv run pytest tests/newton/gesture/test_dynamic_model.py -v
# model instantiates; forward pass shapes correct; trains on synthetic data
```

**Commit:** `feat(gesture): dynamic LSTM model design`

---

### Step 8.9 — Dynamic gesture sequence capture infrastructure (1.5 days)

**Goal:** Sample collection for dynamic gestures. Includes "demo start"
and "demo end" detection (analogous to VAD but for motion).

**Outputs:**

- `newton/gesture/dynamic/capture.py` — motion-activity-detection wrapping the camera feed
- `newton/gesture/dynamic/registration.py` — sir performs gesture N times, system captures each performance
- `tests/newton/gesture/test_dynamic_capture.py`

**Motion-activity-detection:**

```
landmarks per frame
    ↓
compute frame-to-frame landmark velocity
    ↓
velocity > start_threshold → demo starting
velocity < stop_threshold for >0.3s → demo ending
    ↓
extract sequence (start frame ... end frame)
    ↓
normalize length to 30 frames (interpolate / resample)
```

**Sample protocol:**

```
sir runs: newton gesture register wave --dynamic --scope shared --samples 20

instruction shown: "Perform the gesture starting after the beep. 20 takes."

beep → sir waves → silence → sample 1 captured → beep → sample 2 ...
```

**Verification:**

```bash
uv run newton gesture register wave --dynamic --scope shared --samples 20
# 20 sequences captured
sqlite3 data/newton.db "SELECT name, gesture_kind FROM gestures WHERE name='wave'"
# wave | dynamic
ls data/gestures/<gesture_id>/sequences/
# 20 .npy files
```

**Commit:** `feat(gesture): dynamic capture with motion-activity-detection`

---

### Step 8.10 — Dynamic gesture training pipeline (1.5 days)

**Goal:** Train the LSTM on captured sequences. Adding a new dynamic
gesture requires retraining the whole model.

**Outputs:**

- `newton/gesture/dynamic/training_pipeline.py`
- `newton/gesture/dynamic/hot_swap.py` — atomic .pt file swap
- `newton/cli.py` — `newton gesture train dynamic`
- `tests/newton/gesture/test_dynamic_training.py`

**Pipeline:**

```
collect all rows where gesture_kind='dynamic' with sequences
    ↓
build dataset: (sequence, class_label) pairs
    ↓
80/20 train/val split
    ↓
train LSTM for 100 epochs with early stopping
    ↓
save to data/models/gestures/dynamic-v<timestamp>.pt
    ↓
hot-swap symlink
    ↓
gestures.trained_at = now
```

**Training time:** 1–5 minutes for 5–10 dynamic gestures on RTX 5090.
Linear with gesture count.

**Verification:**

```bash
uv run newton gesture train dynamic
# trains, val accuracy printed (target >= 0.9)
```

**Risk:** Similar gestures confuse the model (e.g. wave vs swipe_left).
**Mitigation:** confusion matrix in training output; sir warned if a
gesture's val accuracy < 0.85.

**Commit:** `feat(gesture): dynamic training pipeline`

---

### Step 8.11 — Dynamic gesture runtime + integration (1.5 days)

**Goal:** Continuous camera feed → motion-activity-detection → sequence
extraction → LSTM inference → action dispatch.

**Outputs:**

- `newton/gesture/dynamic/runtime.py`
- Unified runtime: static + dynamic in one loop
- `tests/newton/gesture/test_dynamic_runtime.py`

**Unified runtime:**

```
camera frame → MediaPipe Hand → landmarks
    ↓
[fork]
    static classifier (every frame)
    sequence buffer (every frame appended; runs LSTM when motion ends)
    ↓
[fastest match wins]
    static fires immediately on per-frame match (no delay)
    dynamic fires at end of motion (300 ms tail)
    ↓
action dispatch via Block 2
```

**Verification:**

```bash
uv run newton gesture watch &
# sir does fist (static) → action fires immediately
# sir does wave (dynamic) → action fires at end of wave
```

**Commit:** `feat(gesture): dynamic runtime + unified static/dynamic loop`

---

### Step 8.12 — Dynamic CRUD consistency (1 day)

**Goal:** CRUD operations from step 8.5 work for dynamic gestures too.
Retrain triggered automatically when needed.

**Outputs:**

- Extends `newton/cli.py` gesture subcommands to handle dynamic kind
- Hooks: deleting a dynamic gesture triggers retrain on next `newton gesture train dynamic`
- `tests/newton/gesture/test_dynamic_crud.py`

**Verification:**

```bash
uv run newton gesture list --kind dynamic
# 4 dynamic gestures shown

uv run newton gesture delete <dynamic_gesture_id>
uv run newton gesture train dynamic    # rebuild with one fewer
```

**Commit:** `feat(gesture): dynamic CRUD with retrain hooks`

---

### Step 8.13 — UI control gesture integration (pyautogui) (1.5 days)

**Goal:** Bind gestures to common UI actions: zoom, click, window
switch, scroll, brightness.

**Outputs:**

- `newton/gesture/ui_actions.py` — pyautogui-backed actions library
- Tools wired to Block 2:
  - `ui_zoom_in` / `ui_zoom_out` — risk 1
  - `ui_click_active` — risk 2
  - `ui_window_switch` — risk 1
  - `ui_scroll_up` / `ui_scroll_down` — risk 1
  - `ui_brightness_up` / `ui_brightness_down` — risk 1
- Sample bindings sir might add:
  - pinch_out → ui_zoom_in
  - pinch_in → ui_zoom_out
  - swipe_left → ui_window_switch (alt-tab)
  - point_up → ui_brightness_up
- `tests/newton/gesture/test_ui_actions.py`

**Verification:**

```bash
uv run newton gesture bind <pinch_out_id> --action 'ui_zoom_in:{}'
uv run newton gesture watch &
# sir does pinch_out gesture
# expect: active window zooms in (ctrl-+)
```

**Risk:** Wrong-window race. **Mitigation:** small focus-stabilization
delay (100 ms) before sending pyautogui event.

**Commit:** `feat(gesture): UI control bindings via pyautogui`

---

### Step 8.14 — B+C+D mode activation policy (1.5 days)

**Goal:** Multi-layered defense against accidental gesture triggers.

**Outputs:**

- `newton/gesture/mode_policy.py` — implements B+C+D
- `newton/cli.py` — `newton gesture mode <auto|manual_on|manual_off>`
- `tests/newton/gesture/test_mode_policy.py`

**B+C+D defense (master.md §1.6 + gestures.md):**

```
B = explicit command   → sir says "JARVIS, gesture mode on/off"
C = trigger gesture    → an "armed" gesture (e.g. raise palm)
                          starts a 30s window where other gestures count
D = context-aware auto → block 4 context: "sir is at desk, mid-coding,
                          no video call" → gestures enabled
```

**Modes:**

```
manual_on:  always listen. risk: accidental fires.
manual_off: ignore all gestures. risk: useless.
auto:       use D + C. recommended default.
```

**Auto mode behavior:**

```
context allows? (block 4 context check)
    ↓
yes → wait for armed gesture (palm raise, 0.5s hold)
    ↓
armed → 30 s active window
    ↓
within window → process gestures
30 s no gesture → re-arm needed
```

**Verification:**

```bash
uv run newton gesture mode auto
# armed gesture (palm raise) required before others fire

uv run newton gesture mode manual_on
# every gesture fires immediately
```

**Commit:** `feat(gesture): B+C+D mode activation policy`

---

### Step 8.15 — Visual feedback overlay (1 day)

**Goal:** Floating window shows mode state, last recognized gesture,
confidence.

**Outputs:**

- `newton/gesture/overlay.py` — Tauri-light or tkinter overlay window
- `newton/cli.py` — `newton gesture overlay start/stop`
- `tests/newton/gesture/test_overlay.py`

**Overlay displays:**

```
┌─────────────────────────┐
│ gesture mode: auto      │
│ armed: ✓ (28s left)     │
│ last: pinch_out (0.91)  │
└─────────────────────────┘
```

**Verification:**

```bash
uv run newton gesture overlay start
# floating window appears top-right
# sir does a gesture → overlay updates
```

**Commit:** `feat(gesture): visual feedback overlay`

---

### Step 8.16 — Voice-driven gesture registration (1 day)

**Goal:** sir can register new gestures by voice command, not just CLI.

**Outputs:**

- `newton/tools/builtin/gesture_register.py` — risk 2 (creates files + DB rows)
- Tool description guides LLM to use it when sir says "JARVIS, register new gesture called X"
- `tests/newton/tools/test_gesture_register_tool.py`

**Flow:**

```
sir: "JARVIS, register a new gesture called 'pause_music', static, personal"
    ↓
JARVIS picks tool gesture_register with args:
  name: pause_music
  kind: static
  scope: personal
    ↓
[approval — risk 2]
sir: yes
    ↓
JARVIS speaks: "Show me the gesture. I'll capture 40 samples starting after the beep."
    ↓
[capture flow from step 8.3 runs]
    ↓
[training auto-triggered]
    ↓
JARVIS: "Done. 'pause_music' is recognized. Want to bind it to an action?"
```

**Verification:**

Manual flow with full block 1-8 stack. Unit test the tool's args parsing.

**Commit:** `feat(gesture): voice-driven registration tool`

---

### Step 8.17 — Block 8 summary + tag (half-day)

**Goal:** Lock the block.

**Outputs:**

- `docs/newton/block-8-summary.md`
- `docs/newton/cli.md` — final pass
- `README.md` — Block 8 marked complete
- Git tag: `v0.8.0-block8`

**Block 9 entry conditions (provisional):**

- Static + dynamic gestures both work
- CRUD operations functional
- Shared / personal scope enforced
- UI control bindings via pyautogui
- B+C+D mode activation works
- Visual feedback overlay
- Voice-driven registration via tool
- All pytest cases pass (~593 total)
- Preflight 9/9 still ✓
- OpenJarvis: still 0 files modified

**Commit + tag:** `chore: block 8 complete`

---

## 2. Deliberately not in Block 8

- ❌ **3D Brain gesture manipulation** — Block 11 (depends on Brain existing first)
- ❌ **Gesture-driven autoresearch shortcuts** — out of scope
- ❌ **Multi-hand coordinated gestures** — out of scope (single hand only)
- ❌ **Mid-air typing / drawing** — out of scope
- ❌ **VR / AR controllers** — out of scope
- ❌ **Foot pedal / external input** — out of scope

---

## 3. Risk matrix

| Risk | Impact | Mitigation |
|------|--------|-----------|
| MediaPipe Model Maker compatibility on RTX 5090 / Python 3.12 | Med | Pin version; fallback to manual feature extraction + custom classifier if blocked |
| Dynamic gesture similarity confusion (wave vs swipe) | Med | Confusion matrix output during training; sir warned per gesture; advise renaming |
| Hot-reload race during gesture train + watch | Low | Atomic symlink swap; reader rechecks mtime |
| pyautogui sends to wrong window | Med | Focus-stabilization delay (100ms) |
| Accidental gesture fires UI command | High | B+C+D defense (step 8.14) addresses |
| Overlay window resource hog | Low | Single Tauri-light instance; throttled updates |
| 100+ gestures overwhelm sir's memory | Low | `newton gesture list` is the source of truth |
| Personal gesture leak (gf sees sir's secret_handshake action) | Med | Scope enforcement (step 8.6); test coverage |
| Camera busy (Block 6 face binding running) | Med | Both subsystems share camera source via mediator pattern in block 6 |
| 25–35 day estimate optimistic | Med | Step 8.10 (dynamic training tuning) can stretch; mid-block re-estimate at 8.11 |

---

## 4. After Block 8 — opening message for the next chat

```markdown
# Newton v4 — Block 9 start (Communication + Calendar + Smart Home)

## Context
- Newton: multi-persona AI OS, OpenJarvis fork
- Environment: RTX 5090 + WSL2 Ubuntu + systemd
- Location: ~/newton-v4/

## Design docs
[newton-v4-master.md]
[newton-v4-tech-stack.md]
[newton-v4-engines.md]    # block 9 capability matrix
[newton-v4-block-8.md]    # complete
[newton-v4-block-9.md]    # this block
[TERMINOLOGY.md]

## Blocks 1–8 result
- v0.8.0-block8: motion + gesture + UI control
  - Static + dynamic gestures
  - Shared / personal scope
  - UI control via pyautogui
  - B+C+D activation defense
  - Visual feedback overlay
  - Voice-driven registration

## Next
Block 9 step 9.1 — Gmail OAuth + read-only.
```

---

## 5. Honest reality check

**Time estimate:** **25–35 days at sir's pace (5–8 weeks).** Block 8 is
the widest block by step count (17). Each step is small but adds up.

**Riskiest steps:**

- **Step 8.10** (dynamic training tuning) — LSTM hyperparameter sensitivity
- **Step 8.14** (B+C+D policy) — getting "feels right" balance vs annoying
- **Step 8.13** (UI control) — pyautogui wrong-window risk

**Simplest steps:**

- 8.1, 8.2, 8.5, 8.6, 8.17 — wrapper / CRUD code

**Most important step:**

- **Step 8.14** (mode activation). Without this, gesture detection
  fires constantly, sir gets frustrated, turns gestures off entirely.

**Behavioural shift:**

After Block 8, sir's interaction with Newton has three input channels:
voice (Block 5), face (Block 6), hand gestures (Block 8). Voiceless
operation possible in meetings, music playing, etc.

**Assets carried over:**

- Block 1 `gestures` table — extended here
- Block 2 ToolRegistry → gesture actions dispatch through it
- Block 4 context → feeds D layer of activation policy
- Block 5 voice → enables voice-driven gesture registration
- Block 6 camera + Voice ID → identifies who's gesturing (personal scope)
- ~498 pytest cases must still pass

---

## 6. Starting checklist

Before Block 8 begins:

- [ ] Block 7 tagged `v0.7.0-block7`, `newton status` green
- [ ] Pytest ~498 passing
- [ ] USB webcam working (block 6 already requires this)
- [ ] `mediapipe-model-maker` installable on Python 3.12
- [ ] PyTorch with CUDA support installed (Block 1 baseline; verify)
- [ ] Display server (X11 or WSLg) available for overlay window
- [ ] pyautogui works (Block 7 already requires this)
- [ ] sir has 5–8 weeks of focused work
- [ ] At least 10 GB free disk (model files + gesture sample storage)

---

Ready when sir is. Step 8.1 is the entry point.
