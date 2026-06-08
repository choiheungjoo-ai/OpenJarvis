-- Newton v4 — vault notes cache (migration 006).
--
-- Adds one table: vault_notes.
--
-- Part of block 3 (vault). A row caches the parsed ACL + metadata of each
-- markdown note under data/vault/, so ACL queries don't re-parse files.
-- The note files on disk remain the source of truth; this table is a cache
-- rebuilt by the scanner (newton/vault/scanner.py).
--
-- owner_user_id is nullable with ON DELETE SET NULL: deleting a user orphans
-- their notes (the scanner re-evaluates orphans on the next pass) rather than
-- blocking the delete or cascading file metadata away. NOTE: the block-3 doc
-- wrote "NOT NULL" alongside "SET NULL", which is contradictory in SQLite;
-- nullable + SET NULL is the consistent choice and matches block-1's audit
-- convention for user back-references.
--
-- ACL list fields are stored as JSON text arrays (read_users_json, etc.):
-- SQLite has no array type, and these are read/written as whole lists.
--
-- This is migration 006, not 005: the block-3 doc predates the block-2
-- 2.7+2.8 merge that consumed 005 (tool_policy_decision). 005 is taken.
--
-- Idempotent (CREATE TABLE IF NOT EXISTS) and transaction-wrapped by the
-- runner. Reapplying is a no-op once _migrations has version=6.

-- ─────────────────────────────────────────────────────────────────────────────
-- Group: vault
-- ─────────────────────────────────────────────────────────────────────────────

-- vault_notes — one row per markdown note, caching its ACL + metadata.
--   path is unique (relative to the vault root) and is the natural key on disk.
CREATE TABLE IF NOT EXISTS vault_notes (
    note_id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    path                 TEXT     NOT NULL UNIQUE,
    owner_user_id        TEXT,
    read_users_json      TEXT     NOT NULL DEFAULT '[]',
    read_personas_json   TEXT     NOT NULL DEFAULT '[]',
    write_users_json     TEXT     NOT NULL DEFAULT '[]',
    write_personas_json  TEXT     NOT NULL DEFAULT '[]',
    status               TEXT     NOT NULL DEFAULT 'pending_review'
                                  CHECK (status IN
                                  ('canonical','shared','pending_review')),
    tags_json            TEXT     NOT NULL DEFAULT '[]',
    content_hash         TEXT     NOT NULL,
    mtime                REAL     NOT NULL DEFAULT 0,
    indexed_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_user_id) REFERENCES users(user_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_vault_notes_owner
    ON vault_notes(owner_user_id);

CREATE INDEX IF NOT EXISTS idx_vault_notes_status
    ON vault_notes(status);

-- ─────────────────────────────────────────────────────────────────────────────
-- Mark this migration applied.
-- ─────────────────────────────────────────────────────────────────────────────

INSERT OR IGNORE INTO _migrations (version) VALUES (6);
