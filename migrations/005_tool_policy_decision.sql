-- Newton v4 — tool policy decision enum (migration 005).
--
-- Replaces tool_policies.require_approval (0/1) with a 3-state decision
-- column: 'auto_allow' | 'require_approval' | 'always_deny'.
--
-- Rationale: a single boolean cannot express "always_deny" (refuse without
-- prompting). The CLI's `tools policy set --decision ...` exposes all three
-- states, so the model needs them too. A TEXT enum keeps the three values
-- mutually exclusive (a 2-boolean encoding would allow contradictory rows).
--
-- SQLite's ALTER TABLE cannot drop or rename columns in 3.x without the
-- table-rebuild dance: create new table, copy data, drop old, rename. This
-- migration does exactly that, mapping require_approval=0 -> 'auto_allow'
-- and =1 -> 'require_approval'. No row ever meant 'always_deny' before, so
-- nothing maps to it during migration.
--
-- Idempotent. Wrapped in a transaction by the runner.

-- ─────────────────────────────────────────────────────────────────────────────
-- Rebuild tool_policies with the new column.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tool_policies_new (
    policy_id            INTEGER  PRIMARY KEY AUTOINCREMENT,
    tool_name            TEXT     NOT NULL,
    persona_id           TEXT,
    user_id              TEXT,
    decision             TEXT     NOT NULL DEFAULT 'require_approval'
                                  CHECK (decision IN
                                  ('auto_allow','require_approval','always_deny')),
    note                 TEXT,
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (persona_id) REFERENCES personas(persona_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id)    REFERENCES users(user_id)       ON DELETE CASCADE
);

-- Copy data only when the old shape exists (i.e. on machines that ran 002
-- before this migration). The next migration up from a fresh install will
-- find no rows; that's fine too.
INSERT INTO tool_policies_new (
    policy_id, tool_name, persona_id, user_id, decision, note, created_at
)
SELECT
    policy_id,
    tool_name,
    persona_id,
    user_id,
    CASE require_approval WHEN 0 THEN 'auto_allow' ELSE 'require_approval' END,
    note,
    created_at
FROM tool_policies;

DROP TABLE tool_policies;
ALTER TABLE tool_policies_new RENAME TO tool_policies;

-- Re-create the indexes lost with the original table.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tool_policies_triple
    ON tool_policies(
        tool_name,
        COALESCE(persona_id, '*'),
        COALESCE(user_id, '*')
    );

CREATE INDEX IF NOT EXISTS idx_tool_policies_tool
    ON tool_policies(tool_name);

INSERT OR IGNORE INTO _migrations (version) VALUES (5);
