-- Newton v4 — STT contextual biasing dictionary (migration 008).
--
-- Adds users.stt_bias_dict_json: a JSON array of entity strings extracted
-- from the user's vault notes (block 3.9 biasing hook). Block 5 reads this
-- at every STT call for Contextual Biasing, so Whisper recognises personal
-- vocabulary (project names, products, people) it would otherwise mangle.
--
-- The doc named this 006_user_biasing, but 006 (vault) and 007
-- (vault_indexed_hash) are taken — the block-3 doc predates the block-2
-- renumbering. This is 008.
--
-- ADD COLUMN runs exactly once because the runner only executes pending
-- migrations (verified in newton/db.py init_db). version=8.

ALTER TABLE users ADD COLUMN stt_bias_dict_json TEXT NOT NULL DEFAULT '[]';

INSERT OR IGNORE INTO _migrations (version) VALUES (8);
