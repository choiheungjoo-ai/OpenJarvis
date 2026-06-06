-- Newton v4 — tool approval policy (migration 002).
--
-- Adds one table: tool_policies.
--
-- Part of block 2 (tool calling + approval hook).  Stores the approval
-- matrix keyed by (tool_name, persona_id, user_id) with cascading defaults:
-- a NULL persona_id or user_id is a wildcard ("any").  Resolution picks the
-- most specific matching row; when no row matches, newton/tools/policy.py
-- falls back to a risk-based default in code (risk 0-1 auto-allow,
-- risk 2-4 require approval).
--
-- FK policy matches 001: persona_id / user_id reference their parents and
-- CASCADE on delete (a policy is personal data tied to that persona/user;
-- deleting the parent removes the override, falling back to defaults).
--
-- Idempotent (CREATE TABLE IF NOT EXISTS) and wrapped in a transaction by
-- the runner.  Reapplying is a no-op once _migrations has version=2.

-- ─────────────────────────────────────────────────────────────────────────────
-- Group: tools
-- ─────────────────────────────────────────────────────────────────────────────

-- tool_policies — per (tool, persona, user) approval override.
--   persona_id NULL ⇒ applies to any persona.
--   user_id    NULL ⇒ applies to any user.
-- tool_name is always concrete (never a wildcard).
CREATE TABLE IF NOT EXISTS tool_policies (
    policy_id            INTEGER  PRIMARY KEY AUTOINCREMENT,
    tool_name            TEXT     NOT NULL,
    persona_id           TEXT,                      -- NULL ⇒ any persona
    user_id              TEXT,                      -- NULL ⇒ any user
    require_approval     INTEGER  NOT NULL DEFAULT 1
                                  CHECK (require_approval IN (0,1)),
    note                 TEXT,                      -- why this override exists
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (persona_id) REFERENCES personas(persona_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id)    REFERENCES users(user_id)       ON DELETE CASCADE
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Indexes.
-- ─────────────────────────────────────────────────────────────────────────────

-- Uniqueness across the (tool, persona, user) triple.  SQLite treats NULLs
-- as distinct in a plain UNIQUE constraint, which would allow duplicate
-- wildcard rows like (echo, NULL, NULL) twice.  COALESCE-ing NULL to a
-- sentinel that cannot collide with a real id makes the triple truly unique.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tool_policies_triple
    ON tool_policies(
        tool_name,
        COALESCE(persona_id, '*'),
        COALESCE(user_id, '*')
    );

-- "Every policy row for tool X" — the resolver loads candidates by tool_name.
CREATE INDEX IF NOT EXISTS idx_tool_policies_tool
    ON tool_policies(tool_name);

-- ─────────────────────────────────────────────────────────────────────────────
-- Mark this migration applied.
-- ─────────────────────────────────────────────────────────────────────────────

INSERT OR IGNORE INTO _migrations (version) VALUES (2);
