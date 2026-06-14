-- Newton v4 — proactive mode column on users (block 4 step 4.8).
--
-- Adds two columns:
--   proactive_mode           — one of off/minimal/smart/aggressive,
--                              default 'smart' (per master.md §1.7).
--   proactive_mode_revert_at — NULL for permanent modes; a UTC timestamp
--                              for time-bounded modes ("off for 1 hour"),
--                              at which point the scheduler reverts to
--                              the default.
--
-- ALTER TABLE ADD COLUMN ... CHECK is supported in SQLite ≥3.37; we keep
-- the constraint named so a future ALTER ... DROP CONSTRAINT is possible
-- without surprises.

BEGIN;

ALTER TABLE users
    ADD COLUMN proactive_mode TEXT NOT NULL DEFAULT 'smart'
        CHECK (proactive_mode IN ('off','minimal','smart','aggressive'));

ALTER TABLE users
    ADD COLUMN proactive_mode_revert_at TIMESTAMP;

INSERT OR IGNORE INTO _migrations(version) VALUES (10);

COMMIT;
