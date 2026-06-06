-- Newton v4 — provider state (migration 004).
--
-- Adds one table: provider_state.
--
-- Part of block 2 (provider registry). Stores the permanently-selected
-- provider per capability, so a `permanent`-scope swap survives restart.
-- `once` and `session` scopes are in-memory only and never touch this table.
--
-- No FK: `capability` and `active_provider` are code-registry identifiers
-- (strings), not rows in another table. One row per capability; the active
-- provider is overwritten in place on each permanent swap.
--
-- Idempotent (CREATE TABLE IF NOT EXISTS) and wrapped in a transaction by
-- the runner. Reapplying is a no-op once _migrations has version=4.

-- ─────────────────────────────────────────────────────────────────────────────
-- Group: providers
-- ─────────────────────────────────────────────────────────────────────────────

-- provider_state — the permanent active provider for a capability.
--   capability is the primary key: at most one permanent selection each.
CREATE TABLE IF NOT EXISTS provider_state (
    capability           TEXT     PRIMARY KEY,
    active_provider      TEXT     NOT NULL,
    updated_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Mark this migration applied.
-- ─────────────────────────────────────────────────────────────────────────────

INSERT OR IGNORE INTO _migrations (version) VALUES (4);
