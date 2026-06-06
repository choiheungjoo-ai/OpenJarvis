-- Newton v4 — tool approval audit log (migration 003).
--
-- Adds one table: tool_approvals.
--
-- Part of block 2 (tool calling + approval hook).  Records every decision
-- that involved approval — i.e. a call the policy flagged as needing
-- approval, plus the outcome (approved / denied / timeout).  Auto-allowed
-- calls (risk-default or a relaxing policy row) are NOT logged here; this
-- table is a security audit trail, not a full call log.
--
-- FK policy follows 001's audit tables (auth_attempts, registration_requests):
-- user_id references users but SET NULL on delete, so the decision trail
-- survives user deletion with only the personal pointer dropped.
--
-- Idempotent (CREATE TABLE IF NOT EXISTS) and wrapped in a transaction by
-- the runner.  Reapplying is a no-op once _migrations has version=3.

-- ─────────────────────────────────────────────────────────────────────────────
-- Group: tools
-- ─────────────────────────────────────────────────────────────────────────────

-- tool_approvals — one row per approval-gated decision.
--   decision: how it resolved.
--   policy_source: where the require-approval verdict came from
--     ('db' = a tool_policies row, 'risk_default' = code fallback).
--   channel: which approval channel handled the prompt (e.g. 'cli', 'auto').
CREATE TABLE IF NOT EXISTS tool_approvals (
    approval_id          INTEGER  PRIMARY KEY AUTOINCREMENT,
    tool_name            TEXT     NOT NULL,
    risk_level           INTEGER  NOT NULL CHECK (risk_level BETWEEN 0 AND 4),
    persona_id           TEXT,                      -- best-effort context, no FK
    user_id              TEXT,                      -- SET NULL on user delete
    decision             TEXT     NOT NULL
                                  CHECK (decision IN ('approved','denied','timeout')),
    policy_source        TEXT     CHECK (policy_source IN ('db','risk_default')),
    channel              TEXT,                      -- 'cli' / 'auto' / future
    args_summary         TEXT,                      -- short, non-sensitive preview
    decided_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Indexes.
-- ─────────────────────────────────────────────────────────────────────────────

-- "Recent approval decisions, newest first" (audit review).
CREATE INDEX IF NOT EXISTS idx_tool_approvals_time
    ON tool_approvals(decided_at);

-- "Every decision for tool X".
CREATE INDEX IF NOT EXISTS idx_tool_approvals_tool_time
    ON tool_approvals(tool_name, decided_at);

-- ─────────────────────────────────────────────────────────────────────────────
-- Mark this migration applied.
-- ─────────────────────────────────────────────────────────────────────────────

INSERT OR IGNORE INTO _migrations (version) VALUES (3);
