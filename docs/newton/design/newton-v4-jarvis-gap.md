# Newton v4 — JARVIS Gap Analysis & Proactive Architecture

> Result of validating Newton against the movie Iron Man JARVIS / Friday baseline.
> 13 missing capabilities + Proactive philosophy integration.
> All items integrated into v4 (Option B — comprehensive).
>
> Block 4 step decomposition: `newton-v4-block-4.md`
> Master plan: `newton-v4-master.md`
> Terminology: `TERMINOLOGY.md`

---

## 0. Locked decisions

| Item | Decision |
|------|----------|
| **Newton personality** | **Proactive** (movie JARVIS — active butler) |
| **13 missing capabilities** | **All integrated** (Option B — ideal) |
| **Reactive fallback** | sir adjusts by command (off / minimal / smart / aggressive) |
| **Default mode** | smart (notify only on clear patterns) |

---

## 1. Reactive vs Proactive — core philosophy

### Two AI paradigms

```
Reactive AI                    Proactive AI
─────────────                  ─────────────
user command → AI responds     AI observes → patterns → acts
Siri / Alexa                   Movie JARVIS / Friday
```

### Newton's previous design limit

Newton's pre-jarvis-gap design was 100% Reactive:

- User calls → response
- Information requested → answer
- Command → execute
- = Siri / Alexa level

### What Proactive Newton looks like

```
[sir steps in front of camera — says nothing]
   ↓
JARVIS: "Good morning, sir. 3 events today.
        10:00 meeting, 14:00 lunch, 18:00 workout.
        Outside 8°C with rain forecast — umbrella recommended.
        Of 5 new emails, the one from manager Kim is marked urgent.
        Where would you like to begin?"

[sir coding, 2 hours elapsed]
   ↓
JARVIS: (softly) "Sir, you've been focused for 2 hours.
        A short break might help."

[Monday 8:50 — sir said nothing]
   ↓
JARVIS: "Sir, the weekly meeting starts in 10 minutes.
        Last week's notes and this week's agenda are pre-loaded."
```

Same information, same tools — **completely different experience.**

---

## 2. The 13 JARVIS capabilities vs Newton

### A. Already in Newton ✅

| JARVIS capability | Newton implementation | Block |
|-------------------|----------------------|-------|
| Natural language | Qwen 2.5 32B | 2-3 |
| Voice in + out | Whisper + Qwen3-TTS | 5 |
| British butler tone | Chatterbox + sample | 5 |
| User identification (voice) | Resemblyzer | 5 |
| Face recognition | InsightFace | 6 |
| Expression | DeepFace | 6 |
| Hand gestures | MediaPipe + LSTM | 8 |
| UI control via gesture | pyautogui | 8 |
| 3D hologram manipulation | R3F + gestures | 11 |
| Web search / analysis | SearXNG + Brave + Tavily | 7 |
| Document analysis | MarkItDown | 7 |
| Image analysis | Qwen 2.5 VL | 6 / 7 |
| Video analysis | yt-dlp + Whisper | 7 |
| Email | Gmail / SMTP | 9 |
| Messengers | Slack / Discord / Telegram | 9 |
| Learning adaptation | LoRA + Vault | 10 |
| Multi-persona | Butler / JARVIS / Friday | 1 |

### B. The 13 missing — all integrated

Each is now wired into the appropriate block, with the common Proactive
infrastructure shipped in Block 4.

---

## 3. Detail of the 13 missing capabilities

### 3.1 System monitoring + proactive alerts ⭐⭐⭐⭐⭐

**Movie examples:**

- "Sir, battery critically low"
- "Sir, incoming call from Pepper"
- "Sir, the temperature is 18 degrees"

**Newton design:**

```yaml
monitoring:
  system:
    cpu:         { alert_threshold: 90 }
    gpu:         { alert_threshold: 85, vram_threshold: 95 }
    memory:      { alert_threshold: 90 }
    disk:        { alert_threshold: 90 }
    battery:     { alert_threshold: 20, critical: 10 }
    temperature: { cpu_max: 80, gpu_max: 83 }

  network:
    speed_drop: 50%
    connection_lost: true

  notifications:
    style: proactive_tts
    visual: hud_overlay
    quiet_hours: [23:00 - 07:00]
```

**Implementation:** psutil + nvidia-ml-py + background daemon. Block 4
step 4.1 (monitoring foundation) + step 4.2 (threshold alerts).

### 3.2 Screen awareness ⭐⭐⭐⭐

**Movie examples:**

- "Sir, you're looking at the latest market data"
- Tony works while JARVIS reads the screen and helps

**Newton design:**

```yaml
screen_awareness:
  enabled: true
  capture_interval: 60s
  vision_model: qwen2.5-vl-7b

  triggers:
    on_error_dialog: notify
    on_long_idle: suggest
    on_request: analyze

  privacy:
    blur_passwords: true
    exclude_apps: [1password, banking]
    pause_during: video_call
    user_can_disable: anytime
```

**Implementation:** Block 6 (screen capture + Vision LLM + privacy
masking) + Block 4 scheduler integration.

**Critical note on privacy:** password / financial UI exposure must be
masked; sir can disable at any moment; screenshots never leave the
machine.

### 3.3 Ambient awareness ⭐⭐⭐

**Movie examples:**

- "Sir, room temperature 22 degrees"
- Aware of lighting, presence, mood

**Newton design:**

```yaml
ambient_awareness:
  visual:
    camera_analysis_interval: 5min
    detect:
      - sir_present
      - sir_alone_or_company
      - room_lighting
      - time_of_day_from_lighting

  audio:
    background_noise_level
    music_playing: detect_from_audio

  optional_iot:
    temperature_sensor
    humidity_sensor
    air_quality_sensor
```

**Implementation:** Block 6 step 6.8 (camera + microphone background).

### 3.4 Long-term memory + proactive recall ⭐⭐⭐⭐⭐

**Movie examples:**

- "Sir, last time you mentioned this, you said..."
- "Do you remember what manager Kim said in the previous meeting?"

**Newton design:**

```yaml
memory:
  long_term:
    auto_summarize_conversations: true
    save_to: "vault/_auto/conversations/"
    summarize_after: session_end

  proactive_recall:
    enabled: true
    triggers:
      anniversary: "Last year around this time, sir..."
      pattern_match: "In a similar situation before, sir did X"
      contradiction: "Sir, earlier you said differently"
      forgotten_task: "Sir mentioned doing X but hasn't yet"

  pattern_detection:
    weekly_routine
    monthly_routine
    user_preferences
```

**Implementation:** Block 3 (session auto-summarization, step 3.10) +
Block 4 step 4.9 (recall scheduling).

### 3.5 Calendar / schedule management ⭐⭐⭐⭐⭐

**Movie examples:**

- "Sir, you have a meeting in 30 minutes"
- "Sir, Pepper rescheduled lunch to 2 PM"

**Newton design:**

```yaml
calendar:
  providers:
    - google_calendar
    - outlook
    - caldav

  proactive:
    next_event_alert: [60min, 15min, 5min]
    conflict_detection: true
    travel_time_warning: true
    prep_reminder:
      meeting: 10min_before
      flight: 24h_before

  natural_commands:
    add: "schedule meeting tomorrow at 3"
    move: "push afternoon meeting back an hour"
    cancel: "cancel tomorrow's meeting"
    query: "what's on my schedule next week"
```

**Implementation:** Block 9 steps 9.7-9.9.

### 3.6 Smart home / IoT control ⭐⭐⭐

**Movie examples:**

- "Lights at 60%, JARVIS"
- Lights, music, garage door, etc.

**Newton design (Block 9):**

```yaml
smarthome:
  hub: home_assistant

  devices:
    - lights (philips_hue / aqara)
    - climate (nest / smart_thermostat)
    - security (cameras / locks)
    - media (spotify / sonos)

  proactive:
    morning_routine: "lights to 50% when sir wakes; no music"
    evening_routine: "warm lighting from 19:00"
    away_mode: "energy saver when sir is absent"
```

**Implementation:** Block 9 steps 9.10-9.11.

### 3.7 Predictive / anticipatory ⭐⭐⭐⭐⭐

**Biggest gap. The heart of JARVIS.**

**Movie examples:**

- System awakens before Tony arrives
- "Sir, I anticipated this might happen, so I prepared..."
- Predict intent → act preemptively

**Newton design:**

```yaml
anticipation_engine:
  pattern_learning:
    time_based: "every Monday 9 meeting → 8:50 prepare materials"
    sequence_based: "start coding → suggest music"
    context_based: "rainy day → umbrella reminder"

  prediction_horizons:
    immediate: 5min
    short: 1h
    medium: today
    long: this_week

  trigger_actions:
    prepare_resources: "pre-open meeting docs"
    suggest_action: "suggest a break"
    preemptive_query: "last time you did X you needed Y"

  user_feedback_loop:
    track_acceptance: "did the suggestion land?"
    learn_rejections: "what patterns to suppress"
    confidence_threshold: 0.7
```

**Implementation:** Block 4 steps 4.3 (pattern recognition) + 4.4
(anticipation engine) + 4.6 (reaction learning).

### 3.8 HUD (Heads-Up Display) ⭐⭐⭐⭐

**Movie examples:**

- System info always visible
- Notifications gracefully float in
- Movie-aesthetic interface

**Newton design:**

```yaml
hud:
  enabled: true
  position: top_right
  size: minimal

  displays:
    - current_time
    - persona_status
    - gesture_mode_indicator
    - system_health
    - next_calendar_event
    - notification_count

  notifications:
    style: floating_card
    duration: 5s
    sound: soft_chime
    priority_levels:
      info: visual_only
      warning: visual + sound
      urgent: visual + sound + tts
```

**Implementation:** Block 11 step 11.6 (HUD overlay window — Tauri
secondary window).

### 3.9 Real-time translation ⭐⭐⭐⭐

**Movie examples:**

- "Sir, he said in Russian: ..."
- Foreign language auto-translation

**Newton design:**

```yaml
translation:
  modes:
    realtime_meeting:
      input: microphone_or_system_audio
      output: hud_subtitle + tts_summary
      languages: auto_detect

    interactive:
      input: turn_taking
      output: tts_in_target_language

    document:
      input: text_or_url
      output: vault_note

  languages: [en, ja, zh, es, fr, de, ru, ...]
```

**Implementation:** Block 7 step 7.8. Qwen 2.5 32B handles multilingual
natively; only UI work needed.

### 3.10 OS commands by voice ⭐⭐⭐⭐⭐

**Movie examples:**

- "JARVIS, run diagnostics"
- "JARVIS, open the suit's blueprint"
- Every system task accessible by voice

**Newton design:**

```yaml
os_commands:
  file_operations:
    open: "open Chrome"
    search: "find PDFs created today"
    move: "move PDFs from Downloads to Documents"
    delete: "clean old cache"

  app_control:
    launch: "open VS Code"
    close: "close all Chrome windows"
    switch: "switch to VS Code"

  system:
    diagnostics: "show system status"
    cleanup: "clean temp files"
    update_check: "any updates"
    shutdown: "shut down in 30 minutes"

  desktop_automation:
    type_text: "dictate the email response"
    click: "click OK"
    scroll: "scroll down"
```

**Implementation:** Block 7 steps 7.6-7.7. pyautogui-driven.

### 3.11 Security monitoring ⭐⭐⭐

**Movie examples:**

- Detect suspicious access
- Intrusion alerts

**Newton design:**

```yaml
security:
  user_detection:
    unknown_face_alert: true
    multiple_users_detected: true
    sir_absence_long: 12h

  system_security:
    failed_auth_attempts: 3
    new_device_login: alert
    sensitive_file_access: log

  optional:
    home_security_camera: integrate
    door_sensor: notify
```

**Implementation:** Block 6 step 6.9 (vision-based security hooks).

### 3.12 Meeting assistant ⭐⭐⭐⭐

**Movie examples:**

- JARVIS provides info during meetings
- Summarizes key points

**Newton design:**

```yaml
meeting_assistant:
  mode_trigger:
    auto_detect: calendar_event_now
    manual: "JARVIS, meeting mode"

  during_meeting:
    record_audio: opt_in
    speaker_diarization: pyannote.audio
    realtime_transcription: whisper
    realtime_translation: optional

    proactive:
      info_lookup: "when speaker mentions X → pre-search related"
      action_item_detection: "auto-detect follow-ups"
      conflict_detection: "earlier decision contradicts this"

  after_meeting:
    auto_summary: vault_save
    action_items: task_list
    follow_up_email: draft_ready
```

**Implementation:** Block 5 (meeting mode at end of voice block).

### 3.13 Health / sleep monitoring ⭐⭐

**Movie examples (Friday):**

- "Sir, you should rest"

**Newton design (opt-in):**

```yaml
wellness:
  enabled: false                # default OFF

  tracking:
    work_duration_alert: 2h
    eye_strain_reminder: 20min
    posture_check: visual_analysis
    hydration: time_based

  proactive_messages:
    style: gentle
    frequency: minimal
```

**Implementation:** Block 9 or later, opt-in. Default off.

---

## 4. Proactive Engine — distributed or unified?

13 capabilities all benefit from a shared Proactive Engine.

### Chosen option — hybrid (option C)

**New Block 4 + capability-specific work in natural blocks:**

- **Block 4 (Proactive Engine)** — common infrastructure (monitoring,
  patterns, anticipation, notification, delivery)
- **Per-block enrichment** — calendar in Block 9, OS commands in Block 7,
  screen awareness in Block 6, etc.

This keeps common infra in one place while capabilities live where they
naturally belong.

---

## 5. Updated dependency pyramid (Proactive integrated)

```
                  [ 11. UI + 3D Brain + HUD ]
                  [ 10. LoRA per persona (conditional) ]
       [ 8. Gesture ] [ 9. Comm + Cal ] [ 7. Search + OS + Translation ]
              [ 6. Vision (face / expression / screen / ambient) ]
              [ 5. Voice (+ meeting mode) ]
                  [ 4. 🆕 Proactive Engine ]
                  [ 3. Persona + Vault + ACL + RAG + memory ]
                  [ 2. Tool Calling + Approval Hook + Provider Registry ]
                  [ 1. OpenJarvis fork + Foundation ]
```

**Block count: 10 → 11** (Proactive Engine added as new Block 4).

---

## 6. Proactive mode levels

Sir adjusts instantly by command:

```yaml
proactive_modes:
  off:
    # fully reactive
    use_case: "don't disturb; meeting; deep focus"

  minimal:
    # urgent only
    use_case: "focused work"
    triggers:
      - calendar_5min_before
      - critical_system_alert
      - urgent_message

  smart:                          # ⭐ default
    # clear patterns only
    use_case: "general use"
    confidence_threshold: 0.7
    learn_from_rejections: true

  aggressive:
    # full movie JARVIS
    use_case: "max help"
    confidence_threshold: 0.5
    proactive_suggestions: true
```

Voice commands:

```
"JARVIS, quiet down" → minimal
"JARVIS, more proactive" → aggressive
"JARVIS, mute for an hour" → off (auto-revert after 1h)
"JARVIS, normal mode" → smart
```

---

## 7. DB schema additions

These tables ship in Block 1's schema; the wiring (writing rows) happens
in Block 4 and the relevant capability blocks:

```sql
-- Background monitoring (Block 4 fills)
CREATE TABLE system_metrics (
    metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_type TEXT,
    value REAL,
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Pattern learning (Block 4)
CREATE TABLE user_patterns (
    pattern_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    pattern_type TEXT,             -- time/sequence/context
    pattern_data_json TEXT,
    confidence REAL,
    occurrences INTEGER DEFAULT 1,
    last_seen TIMESTAMP,
    created_at TIMESTAMP
);

-- Proactive notification history (Block 4)
CREATE TABLE proactive_notifications (
    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    trigger_pattern_id INTEGER,
    notification_text TEXT,
    sent_at TIMESTAMP,
    user_response TEXT,            -- accepted/rejected/ignored
    response_at TIMESTAMP,
    FOREIGN KEY (trigger_pattern_id) REFERENCES user_patterns(pattern_id)
);

-- Screen awareness (Block 6)
CREATE TABLE screen_captures (
    capture_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    captured_at TIMESTAMP,
    analysis_summary TEXT,
    is_sensitive BOOLEAN,
    purge_after TIMESTAMP
);

-- Calendar cache (Block 9)
CREATE TABLE calendar_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,                   -- google/outlook/caldav
    external_id TEXT,
    user_id TEXT,
    title TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    location TEXT,
    notes TEXT,
    last_synced TIMESTAMP
);
```

---

## 8. Newton voice patterns — proactive speech

Movie JARVIS's speech patterns:

### Pattern 1 — proactive report

```
"Sir, <observation>. <recommended action>."
e.g. "Sir, battery is at 15%. Charging is recommended."
```

### Pattern 2 — anticipation + preparation

```
"Sir, <prediction detected>. <action already taken>."
e.g. "Sir, meeting soon. Materials are pre-loaded on your screen."
```

### Pattern 3 — gentle nudge

```
"Sir, <info>. If needed, I can <help>."
e.g. "Sir, an email from manager Kim has arrived. Help draft a reply?"
```

### Pattern 4 — pattern recall

```
"Sir, in <similar past>, you did <that action>. Same this time?"
e.g. "Sir, after meetings like this you usually take a walk."
```

### Pattern 5 — the art of silence

```
Don't speak unless it matters.
Delay alerts when the user is focused.
```

These patterns belong in the JARVIS persona's system prompt (Block 3).

---

## 9. Honest reality check

**Strengths:**

- ✅ **Genuine movie-JARVIS feel**
- ✅ **Dramatically improved user experience**
- ✅ **Local, free, safe — unchanged**
- ✅ **Adjustable** (off / minimal / smart / aggressive)

**Watch-outs:**

⚠ **Development time growth**

- Integrating all 13 capabilities → 1.5-2× original timeline
- New Block 4 added → 4-8 months → 6-12 months overall

⚠ **Annoyance risk**

- Proactive done wrong = irritation
- "I didn't do that!" — wrong prediction
- → smart default + sir's feedback learning (Block 4 step 4.6)

⚠ **Privacy burden**

- Always-on monitoring = full activity record
- Screen / camera / microphone / system all tracked
- → strong ACL + instant disable + auto-purge

⚠ **Resource burden**

- Background always running
- RTX 5090 must be budgeted appropriately
- → idle priority lowered

⚠ **Wrong pattern learning**

- One-off events treated as patterns
- → confidence threshold + reaction learning

---

## 10. Wrap-up

This validation brings Newton **substantially closer to movie JARVIS.**

Core points:

- **Proactive philosophy** = the butler who anticipates
- **13 missing capabilities** = all integrated (Option B)
- **New Block 4** = common Proactive Engine
- **Mode adjustment** = off / minimal / smart / aggressive (instant)
- **Smart default** = notify only on clear patterns

During Block 4 implementation, this is the main reference. Step
decomposition lives in `newton-v4-block-4.md`.

Good work, sir.
