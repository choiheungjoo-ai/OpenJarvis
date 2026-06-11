-- Newton v4 — vault indexing state (migration 007).
--
-- Adds vault_notes.indexed_hash: the content_hash that was last embedded into
-- Qdrant for this note. The indexer compares it to the current content_hash
-- (set by the scanner) to decide what to (re)index:
--
--     indexed_hash IS NULL          -> never indexed -> index it
--     indexed_hash != content_hash  -> note changed  -> re-index
--     indexed_hash == content_hash  -> up to date     -> skip
--
-- Because content_hash covers the whole raw file (frontmatter + body), an
-- ACL-only edit also changes content_hash and thus triggers re-indexing,
-- keeping the ACL snapshot in each Qdrant point fresh.
--
-- Idempotent: ALTER TABLE ADD COLUMN is guarded by checking _migrations.
-- Transaction-wrapped by the runner. version=7.

ALTER TABLE vault_notes ADD COLUMN indexed_hash TEXT;

INSERT OR IGNORE INTO _migrations (version) VALUES (7);
