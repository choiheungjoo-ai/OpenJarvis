# Newton v4 — Gesture System Design

> Complete design for hand gesture recognition.
> Main reference during Block 8 (Motion + Gesture + UI control).
> Master plan: `newton-v4-master.md`
> Step decomposition: `newton-v4-block-8.md`
> Terminology: `TERMINOLOGY.md`

---

## 0. Identity

Newton's gesture system = **user-defined hand-command system.**

The Tony Stark feel: hand-driven manipulation of holographic UIs. This
is a **core Newton capability**, not a secondary helper.

### Locked decisions

| Item | Decision |
|------|----------|
| Gesture kinds | static + dynamic, both from Block 8 onward |
| Categories | persona activation + system control + **UI control** + **3D Brain manipulation** (Block 11) |
| Permission scope | **shared** (activation) + **personal** (control), mixed (TERMINOLOGY) |
| Count limit | generous, no hard cap |
| Restart needed | hot-reload (no restart required) |
| Training | sir demonstrates → 1-5 min training → immediately usable |
| Mode activation | B + C + D layered defense |

---

## 1. Static vs dynamic gestures

### Static gesture

Recognizable hand shape in a single frame.

**Examples:**

- ✊ Closed_Fist
- ✋ Open_Palm
- 👍 Thumb_Up
- 👎 Thumb_Down
- ✌️ Victory
- 👌 OK
- ☝️ Pointing_Up

**Stack:**

- MediaPipe Hand → 21 landmarks
- MediaPipe Gesture Recognizer + Model Maker → classification

**Training:**

- 30 image samples → landmark extraction → classifier retrain
- 1-2 min on RTX 5090

### Dynamic gesture

Continuous motion over time.

**Examples:**

- 👋 wave
- 🔄 circle drawn with finger
- ➡️ swipe (left→right)
- ✋ palm push toward camera
- 🖐️→✊ open hand → fist (grab)

**Stack:**

- MediaPipe Hand → 21 landmarks × N frames (sequence)
- LSTM (Newton-built, PyTorch)
- Sequence classification

**Training:**

- 30 sequence samples (1-2 s each, 30-60 frames)
- 5-10 min on RTX 5090

### Comparison

| Item | Static | Dynamic |
|------|--------|---------|
| Unit | 1 frame | 30-60 frames (1-2 s) |
| Training tool | MediaPipe Model Maker (official) | Newton-built LSTM |
| Model size | ~2 MB | ~20-50 MB |
| Inference latency | ~10 ms | ~50-100 ms |
| Accuracy | very high | trickier (start/end detection) |

---

## 2. Permission scope

Each gesture has a `scope`:

### Shared gestures (anyone can use)

For activation-style gestures (waking the system, summoning Butler).

```yaml
gestures:
  - name: wave_hello
    scope: shared
    binding: activate_butler
  - name: clap_pattern        # 2-clap audio pattern (Block 5)
    scope: shared
    binding: stage1_wake
```

### Personal gestures (owner only)

For control-style gestures (specific actions for sir's workflow).

```yaml
gestures:
  - name: secret_handshake
    scope: personal
    owner: sir
    binding: emergency_shutdown
  - name: pinch_zoom_in
    scope: personal
    owner: sir
    binding: ui_zoom_in
```

**Enforcement:** Block 8 step 8.6. At gesture-recognized time, Newton
checks the currently identified user (Voice ID from Block 5 or Face ID
from Block 6). If `scope=personal` and `owner != current_user`, the
gesture is ignored.

---

## 3. Gesture categories

### Persona activation (shared)

- wave_hello → Butler greets
- clap_pattern → Stage 1 wake (Block 5)
- pointing_up → Stage 2 face-binding hint (Block 6)

### System control (personal)

- thumbs_up → confirm
- thumbs_down → cancel
- v_sign → toggle proactive notification
- fist → emergency mute

### UI control (personal, Block 8 step 8.13)

via pyautogui (already used in Block 7):

- pinch_out → zoom in (Ctrl-+)
- pinch_in → zoom out (Ctrl–)
- swipe_left → alt-tab back
- swipe_right → alt-tab forward
- point_up → brightness up
- point_down → brightness down

### 3D Brain manipulation (Block 11 — deferred)

- palm_open → brain rotates with hand orientation
- pinch_close → zoom in
- pinch_open → zoom out
- point_hold (1 s) → select / inspect node
- two_hands_apart → expand cluster
- two_hands_together → collapse cluster

These ship in Block 11 step 11.8 because the 3D Brain itself doesn't
exist until that block.

---

## 4. Mode activation — B+C+D layered defense

The problem: gesture detection runs continuously while sir is at the
desk. Accidental gestures (scratching nose, drinking coffee) shouldn't
fire commands.

Solution: three layers of defense (master.md §1.6).

### B = Explicit command

```
"JARVIS, gesture mode on"
"JARVIS, gesture mode off"
```

Direct user statement. Highest priority. Lasts until next mode change.

### C = Trigger gesture

A specific "armed" gesture starts a short attention window:

```
[sir does the armed gesture: palm raised for 0.5 s]
   ↓
[30 s window opens]
   ↓
[other gestures within the window fire actions]
   ↓
[30 s no gesture → re-arm required]
```

The armed gesture acts like a "press to talk" button.

### D = Context-aware auto

Block 4's context says: "sir is at desk, mid-coding, no video call".
Gestures auto-enabled.

```
context allows? (block 4 context check)
   ↓
yes → wait for armed gesture (palm raise, 0.5 s hold)
   ↓
armed → 30 s active window
   ↓
within window → process gestures
30 s no gesture → re-arm needed
```

### Modes (CLI / voice toggle)

```
manual_on:    always listen          # high false-fire risk
manual_off:   ignore all             # gestures disabled
auto:         use D + C (default)    # recommended
```

Voice commands:

```
"JARVIS, gestures on" → manual_on
"JARVIS, gestures off" → manual_off
"JARVIS, gestures auto" → auto (default)
```

---

## 5. Registration flow

### Static gesture (Block 8 step 8.3)

```
sir runs: newton gesture register thumbs_up --static --scope shared --samples 40
   ↓
countdown 3..2..1
   ↓
40 frames captured @ 5 fps over 8 s
   ↓
sir holds the gesture, rotates hand slightly for diversity
   ↓
samples saved to data/gestures/<id>/samples/<n>.npy (landmarks, not images)
   ↓
gestures row created with status='pending_training'
   ↓
sir runs: newton gesture train static
   ↓
1-2 min training
   ↓
new model hot-loaded
   ↓
gesture immediately recognizable
```

### Dynamic gesture (Block 8 step 8.9)

```
sir runs: newton gesture register wave --dynamic --scope shared --samples 20
   ↓
instruction shown: "Perform the gesture starting after the beep. 20 takes."
   ↓
beep → sir waves → silence → sample captured
   ↓
20 sequences (each 30 frames after motion-activity-detection normalization)
   ↓
saved to data/gestures/<id>/sequences/<n>.npy
   ↓
sir runs: newton gesture train dynamic
   ↓
5-10 min LSTM training
   ↓
new model hot-loaded
   ↓
gesture immediately recognizable
```

### Voice-driven registration (Block 8 step 8.16)

```
sir: "JARVIS, register a new gesture called pause_music, static, personal"
   ↓
[approval — risk 2 because writes files + DB rows]
sir: yes
   ↓
JARVIS speaks: "Show me the gesture. I'll capture 40 samples starting after the beep."
   ↓
[capture flow above runs]
   ↓
[training auto-triggered]
   ↓
JARVIS: "Done. 'pause_music' is recognized. Want to bind it to an action?"
```

---

## 6. Action binding

After registration, sir binds the gesture to a tool call:

```bash
newton gesture bind <gesture_id> --action 'os_focus_app:{"app":"VS Code"}'
newton gesture bind <gesture_id> --action 'ui_zoom_in:{}'
newton gesture bind <gesture_id> --action 'home_device_set:{"entity":"light.living_room","state":"off"}'
```

Stored in `gestures.action_json`.

At runtime: gesture recognized → action parsed → Block 2 ToolRegistry
dispatch → approval hook fires per tool risk → execute.

---

## 7. Runtime loop (Block 8 step 8.11)

Unified static + dynamic recognition in one camera-feed loop:

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
permission check (scope + current user)
   ↓
action dispatch via Block 2
```

---

## 8. Visual feedback (Block 8 step 8.15)

Floating overlay window showing:

```
┌─────────────────────────┐
│ gesture mode: auto      │
│ armed: ✓ (28s left)     │
│ last: pinch_out (0.91)  │
└─────────────────────────┘
```

Helps sir trust the system (knowing when gestures are listened to /
ignored).

---

## 9. Block 8 step decomposition

The complete 17-step decomposition lives in `newton-v4-block-8.md`.

Summary (from `newton-v4-block-8.md` §1):

| Step | Focus | Time |
|------|-------|------|
| 8.1 | MediaPipe Hand + 21 landmarks | 0.5 d |
| 8.2 | Static Model Maker setup | 0.5 d |
| 8.3 | Static registration flow (CLI) | 1 d |
| 8.4 | Static training + hot-reload | 1 d |
| 8.5 | Static CRUD | 1 d |
| 8.6 | Permission scope enforcement | 0.5 d |
| 8.7 | Static runtime + action dispatch | 1 d |
| 8.8 | Dynamic LSTM design | 1 d |
| 8.9 | Dynamic sequence capture | 1.5 d |
| 8.10 | Dynamic training pipeline | 1.5 d |
| 8.11 | Dynamic runtime + integration | 1.5 d |
| 8.12 | Dynamic CRUD consistency | 1 d |
| 8.13 | UI control gestures (pyautogui) | 1.5 d |
| 8.14 | B+C+D mode activation | 1.5 d |
| 8.15 | Visual feedback overlay | 1 d |
| 8.16 | Voice-driven registration | 1 d |
| 8.17 | Block 8 summary + tag | 0.5 d |

**Total: 5–8 weeks at sir's pace.**

3D Brain gestures (brain_rotate, brain_zoom, node operations) are in
**Block 11 step 11.8**, not Block 8, because the Brain visualization
itself ships in Block 11.

---

## 10. Honest reality check

**Strengths:**

- Static is stable, mature tech (MediaPipe Model Maker)
- Fast training (1-2 min for static)
- Clean CRUD
- Hot-reload supported
- All local, all free

**Watch-outs:**

- Dynamic is harder (Newton-built LSTM)
- Dynamic accuracy slightly lower than static (start/end detection)
- Adding a new dynamic gesture requires full LSTM retrain (1-5 min)
- Similar gestures confuse (open_palm vs stop_palm)
- 100+ gestures → sir's own memory becomes the bottleneck

**Highest risk:**

- Dynamic gesture start/end detection (when did the demo start? when
  did it end?)
- Solution: motion-activity-detection (analogous to VAD for audio)
- Implemented in Block 8 step 8.9

**Fastest value:**

- Even 5 static gestures (wave, stop_palm, ok, thumbs_down, fist) are
  immediately useful — silent commands during meetings, music control,
  etc.

---

## 11. Database schema

`gestures` table (Block 1 schema, extended in Block 8 step 8.3):

```sql
CREATE TABLE gestures (
    gesture_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL UNIQUE,
    gesture_kind      TEXT NOT NULL DEFAULT 'static',  -- 'static' | 'dynamic'
    scope             TEXT NOT NULL DEFAULT 'personal', -- 'shared' | 'personal'
    owner_user_id     TEXT,                             -- NULL for shared system canon
    action_json       TEXT,                             -- tool call args
    samples_dir       TEXT,                             -- relative path
    confidence_threshold REAL DEFAULT 0.7,
    trained_at        TIMESTAMP,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
```

Files (Block 8 layout):

```
data/gestures/<gesture_id>/
├── samples/             # static: 30+ landmark .npy files
│   ├── 001.npy
│   ├── 002.npy
│   └── ...
├── sequences/           # dynamic: 20+ sequence .npy files
│   ├── 001.npy
│   └── ...
└── consent.md           # if shared
```

Trained models (atomic symlinks for hot-swap):

```
data/models/gestures/
├── static-active.task     → symlink to current version
├── static-v<timestamp>.task
├── dynamic-active.pt      → symlink to current version
└── dynamic-v<timestamp>.pt
```

---

## 12. Wrap-up

This document is Newton's complete gesture system reference.

**Key points:**

- Static + dynamic from Block 8
- Shared / personal scope enforced via current-user check
- UI control via pyautogui
- B+C+D layered defense against accidental fires
- Visual feedback for trust
- 3D Brain gestures deferred to Block 11
- Voice-driven registration as the natural UX

During Block 8, this document is the main reference. Step decomposition
lives in `newton-v4-block-8.md`.

Good work, sir.
