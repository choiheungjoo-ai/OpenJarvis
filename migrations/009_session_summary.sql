-- Newton v4 — session summarization bookkeeping (migration 009).
--
-- Adds sessions.summarized_at: when the conversation was condensed into a
-- vault note (block 3.10). NULL = not yet summarized; the trigger layer
-- uses this to avoid re-summarizing.
--
-- The block-3 doc named this 007_session_close, but 007 and 008 are taken
-- (the doc predates the block-2 renumbering). This is 009.
--
-- ADD COLUMN runs once: init_db only executes pending migrations. version=9.

ALTER TABLE sessions ADD COLUMN summarized_at TIMESTAMP;

INSERT OR IGNORE INTO _migrations (version) VALUES (9);
