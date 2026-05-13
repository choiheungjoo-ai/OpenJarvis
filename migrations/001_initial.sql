-- Newton v4 — initial schema (migration 001).
--
-- 13 tables across 5 functional groups:
--   identity   — users, personas, user_persona_link, sessions, messages
--   auth       — registration_requests, auth_attempts
--   guest      — guest_activity
--   proactive  — system_metrics, user_patterns, proactive_notifications,
--                screen_captures, calendar_events
--   meta       — _migrations
--
-- FK policy: every relation declared explicitly.  PRAGMA foreign_keys=ON
-- is set by newton/db.py on every connection (SQLite default is OFF).
--
-- ON DELETE choices follow two principles:
--   * personal data (sessions, screen_captures, calendar)  → CASCADE
--     (deleting a user wipes their stuff — GDPR-friendly)
--   * audit / security records (auth_attempts, registrations) → SET NULL
--     (retain the trail, drop the personal pointer)
--
-- This migration is idempotent in spirit (CREATE TABLE IF NOT EXISTS) and
-- wrapped in a transaction by the runner.  Reapplying it is a no-op once
-- _migrations has version=1.

-- ─────────────────────────────────────────────────────────────────────────────
-- Group: identity
-- ─────────────────────────────────────────────────────────────────────────────

-- users — registered humans.  sir, gf, plus any later additions.
CREATE TABLE IF NOT EXISTS users (
    user_id              TEXT     PRIMARY KEY,
    display_name         TEXT     NOT NULL,
    voice_embedding      BLOB,                      -- block 4
    face_embedding       BLOB,                      -- block 5
    default_persona_id   TEXT,                      -- soft pointer; resolved at lookup
    pin_hash             TEXT,                      -- bcrypt, optional fallback
    passphrase_hash      TEXT,                      -- bcrypt, optional fallback
    retry_profile        TEXT     NOT NULL DEFAULT 'normal'
                                  CHECK (retry_profile IN ('strict','normal','relaxed')),
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- personas — Butler / JARVIS / Friday and any later additions.
-- owner_user_id NULL ⇒ public persona (e.g. butler).
CREATE TABLE IF NOT EXISTS personas (
    persona_id           TEXT     PRIMARY KEY,
    display_name         TEXT     NOT NULL,
    is_public            INTEGER  NOT NULL DEFAULT 0  CHECK (is_public IN (0,1)),
    is_default           INTEGER  NOT NULL DEFAULT 0  CHECK (is_default IN (0,1)),
    owner_user_id        TEXT,
    system_prompt        TEXT,                      -- may contain ${OWNER_DISPLAY_NAME}
    voice_config_json    TEXT,                      -- json: VoiceConfig or {ko,en}
    color                TEXT,
    lora_adapter_path    TEXT,                      -- block 9
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_user_id) REFERENCES users(user_id) ON DELETE SET NULL
);

-- user_persona_link — which users can use which personas, with a per-user default.
CREATE TABLE IF NOT EXISTS user_persona_link (
    user_id              TEXT     NOT NULL,
    persona_id           TEXT     NOT NULL,
    is_default           INTEGER  NOT NULL DEFAULT 0  CHECK (is_default IN (0,1)),
    PRIMARY KEY (user_id, persona_id),
    FOREIGN KEY (user_id)    REFERENCES users(user_id)        ON DELETE CASCADE,
    FOREIGN KEY (persona_id) REFERENCES personas(persona_id)  ON DELETE CASCADE
);

-- sessions — one continuous conversation with a single persona.
CREATE TABLE IF NOT EXISTS sessions (
    session_id           TEXT     PRIMARY KEY,
    user_id              TEXT     NOT NULL,
    persona_id           TEXT     NOT NULL,
    started_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at             TIMESTAMP,
    metadata_json        TEXT,                      -- channel, device, etc.
    FOREIGN KEY (user_id)    REFERENCES users(user_id)        ON DELETE CASCADE,
    FOREIGN KEY (persona_id) REFERENCES personas(persona_id)  ON DELETE RESTRICT
);

-- messages — ordered turns within a session.
CREATE TABLE IF NOT EXISTS messages (
    message_id           INTEGER  PRIMARY KEY AUTOINCREMENT,
    session_id           TEXT     NOT NULL,
    role                 TEXT     NOT NULL CHECK (role IN ('user','assistant','system','tool')),
    content              TEXT,
    tool_calls_json      TEXT,
    emotion_snapshot     TEXT,                      -- block 5: face-derived emotion
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Group: auth
-- ─────────────────────────────────────────────────────────────────────────────

-- registration_requests — new-user proposals awaiting sir's approval.
CREATE TABLE IF NOT EXISTS registration_requests (
    request_id           INTEGER  PRIMARY KEY AUTOINCREMENT,
    requested_name       TEXT     NOT NULL,
    requested_persona    TEXT,
    voice_sample_path    TEXT,
    face_sample_path     TEXT,
    status               TEXT     NOT NULL DEFAULT 'pending'
                                  CHECK (status IN ('pending','approved','rejected')),
    requested_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at           TIMESTAMP,
    decided_by_user_id   TEXT,
    FOREIGN KEY (decided_by_user_id) REFERENCES users(user_id) ON DELETE SET NULL
);

-- auth_attempts — every voice/face/pin/passphrase attempt, success or fail.
-- Retained for security audit even after user deletion (SET NULL on user).
CREATE TABLE IF NOT EXISTS auth_attempts (
    attempt_id           INTEGER  PRIMARY KEY AUTOINCREMENT,
    attempted_user_id    TEXT,                      -- best guess; NULL if unknown
    method               TEXT     NOT NULL CHECK (method IN ('voice','face','pin','passphrase')),
    success              INTEGER  NOT NULL CHECK (success IN (0,1)),
    confidence           REAL,                      -- for voice/face only
    attempted_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (attempted_user_id) REFERENCES users(user_id) ON DELETE SET NULL
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Group: guest
-- ─────────────────────────────────────────────────────────────────────────────

-- guest_activity — what an unregistered visitor did under Butler.
-- Quarantined until sir reviews; can be promoted to a registered user's vault.
CREATE TABLE IF NOT EXISTS guest_activity (
    activity_id          INTEGER  PRIMARY KEY AUTOINCREMENT,
    session_id           TEXT,
    activity_type        TEXT     CHECK (activity_type IN ('search','code','chat','learning')),
    summary              TEXT,                      -- short brief for sir
    raw_content_path     TEXT,                      -- file under _guest_quarantine/
    status               TEXT     NOT NULL DEFAULT 'pending_review'
                                  CHECK (status IN ('pending_review','accepted','rejected','promoted')),
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at          TIMESTAMP,
    reviewed_by_user_id  TEXT,
    FOREIGN KEY (session_id)          REFERENCES sessions(session_id) ON DELETE SET NULL,
    FOREIGN KEY (reviewed_by_user_id) REFERENCES users(user_id)       ON DELETE SET NULL
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Group: proactive  (block 8 fills these; block 1 only declares schema)
-- ─────────────────────────────────────────────────────────────────────────────

-- system_metrics — CPU / GPU / memory / battery / temp / network samples.
-- No FK: global system state, not per-user.
CREATE TABLE IF NOT EXISTS system_metrics (
    metric_id            INTEGER  PRIMARY KEY AUTOINCREMENT,
    metric_type          TEXT     NOT NULL CHECK (metric_type IN
                                  ('cpu','gpu','memory','battery','temperature','network')),
    value                REAL     NOT NULL,
    captured_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- user_patterns — learned behaviour signatures (time / sequence / context).
CREATE TABLE IF NOT EXISTS user_patterns (
    pattern_id           INTEGER  PRIMARY KEY AUTOINCREMENT,
    user_id              TEXT     NOT NULL,
    pattern_type         TEXT     NOT NULL CHECK (pattern_type IN ('time','sequence','context')),
    pattern_data_json    TEXT,
    confidence           REAL,
    occurrences          INTEGER  NOT NULL DEFAULT 1,
    last_seen            TIMESTAMP,
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- proactive_notifications — every proactive nudge Newton has issued.
CREATE TABLE IF NOT EXISTS proactive_notifications (
    notification_id      INTEGER  PRIMARY KEY AUTOINCREMENT,
    user_id              TEXT     NOT NULL,
    trigger_pattern_id   INTEGER,
    notification_text    TEXT     NOT NULL,
    sent_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_response        TEXT     CHECK (user_response IN ('accepted','rejected','ignored')),
    response_at          TIMESTAMP,
    FOREIGN KEY (user_id)            REFERENCES users(user_id)        ON DELETE CASCADE,
    FOREIGN KEY (trigger_pattern_id) REFERENCES user_patterns(pattern_id) ON DELETE SET NULL
);

-- screen_captures — periodic screen snapshots for context awareness.
-- purge_after enforces auto-deletion (block 8 sweeper).
CREATE TABLE IF NOT EXISTS screen_captures (
    capture_id           INTEGER  PRIMARY KEY AUTOINCREMENT,
    user_id              TEXT     NOT NULL,
    captured_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    analysis_summary     TEXT,
    is_sensitive         INTEGER  NOT NULL DEFAULT 0 CHECK (is_sensitive IN (0,1)),
    purge_after          TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- calendar_events — mirrored from Google / Outlook / CalDAV.
CREATE TABLE IF NOT EXISTS calendar_events (
    event_id             INTEGER  PRIMARY KEY AUTOINCREMENT,
    source               TEXT     NOT NULL CHECK (source IN ('google','outlook','caldav')),
    external_id          TEXT,
    user_id              TEXT     NOT NULL,
    title                TEXT,
    start_time           TIMESTAMP,
    end_time             TIMESTAMP,
    location             TEXT,
    notes                TEXT,
    last_synced          TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Group: meta
-- ─────────────────────────────────────────────────────────────────────────────

-- _migrations — applied schema versions.  Underscore prefix marks "internal".
CREATE TABLE IF NOT EXISTS _migrations (
    version              INTEGER  PRIMARY KEY,
    applied_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Indexes — declared after all tables exist.
--
-- Naming: idx_<table>_<columns>.  All indexes here cover concrete read
-- patterns Newton issues (see comment on each).
-- ─────────────────────────────────────────────────────────────────────────────

-- "How many failed attempts in the last 5 minutes for user X?"
CREATE INDEX IF NOT EXISTS idx_auth_attempts_user_time
    ON auth_attempts(attempted_user_id, attempted_at);

-- "Recent attempts across all users" (security dashboard)
CREATE INDEX IF NOT EXISTS idx_auth_attempts_time
    ON auth_attempts(attempted_at);

-- "Sessions for user X, newest first"
CREATE INDEX IF NOT EXISTS idx_sessions_user_time
    ON sessions(user_id, started_at);

-- "Messages of session X in order" (every chat turn)
CREATE INDEX IF NOT EXISTS idx_messages_session_time
    ON messages(session_id, created_at);

-- "CPU usage in the last 10 minutes" (proactive engine)
CREATE INDEX IF NOT EXISTS idx_system_metrics_type_time
    ON system_metrics(metric_type, captured_at);

-- "All time-based patterns for user X"
CREATE INDEX IF NOT EXISTS idx_user_patterns_user_type
    ON user_patterns(user_id, pattern_type);

-- "Notifications for user X, newest first"
CREATE INDEX IF NOT EXISTS idx_proactive_notifs_user_time
    ON proactive_notifications(user_id, sent_at);

-- "Next event after now for user X"
CREATE INDEX IF NOT EXISTS idx_calendar_events_user_start
    ON calendar_events(user_id, start_time);

-- "Captures awaiting purge" (sweeper)
CREATE INDEX IF NOT EXISTS idx_screen_captures_purge
    ON screen_captures(purge_after);

-- "Captures for user X, newest first"
CREATE INDEX IF NOT EXISTS idx_screen_captures_user_time
    ON screen_captures(user_id, captured_at);

-- "Pending guest activity to review"
CREATE INDEX IF NOT EXISTS idx_guest_activity_status_time
    ON guest_activity(status, created_at);

-- "Pending registration requests"
CREATE INDEX IF NOT EXISTS idx_registration_requests_status_time
    ON registration_requests(status, requested_at);

-- ─────────────────────────────────────────────────────────────────────────────
-- Mark this migration applied.
-- INSERT OR IGNORE keeps the file idempotent.
-- ─────────────────────────────────────────────────────────────────────────────

INSERT OR IGNORE INTO _migrations (version) VALUES (1);
