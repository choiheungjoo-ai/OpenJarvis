-- Newton v4 — tts_fallback_log table (block 5 step 5.13).
--
-- One row per fallback event so block 4's monitoring can spot a TTS
-- engine that's quietly degrading. The chain itself (primary →
-- secondary → text-only) lives in newton/voice/tts/fallback.py and
-- writes here on every transition.

BEGIN;

CREATE TABLE IF NOT EXISTS tts_fallback_log (
    log_id           INTEGER  PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT     NOT NULL,
    persona_id       TEXT     NOT NULL,
    language         TEXT     NOT NULL,
    primary_engine   TEXT     NOT NULL,
    fallback_engine  TEXT     NOT NULL,
    failure_reason   TEXT     NOT NULL,
    text_length      INTEGER,
    occurred_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (persona_id) REFERENCES personas(persona_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_tts_fallback_log_session_time
    ON tts_fallback_log(session_id, occurred_at);

CREATE INDEX IF NOT EXISTS idx_tts_fallback_log_engine
    ON tts_fallback_log(primary_engine, occurred_at);

INSERT OR IGNORE INTO _migrations(version) VALUES (11);

COMMIT;
