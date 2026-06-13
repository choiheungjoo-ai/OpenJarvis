# Block 3 — Vault, RAG & Long-term Memory

Tag: `v0.3.0-block3`
Branch: `newton-main`

## What this block delivers

The memory of the system. After block 2 Newton could *act* safely; after
block 3 it can *remember*. Block 3 gives Newton a private, ACL-governed
knowledge store (the vault), turns that store into a semantic search
surface backed by a real vector database, exposes it to personas as two
risk-classified tools, and adds three memory behaviours on top: every
note save teaches the speech recognizer new vocabulary, every finished
conversation condenses itself into a searchable note, and every guest's
activity lands in quarantine for sir to review with a spoken briefing.

Concretely:

- A markdown vault under `data/vault/` whose every note carries an `acl`
  block (owner, read_users, read_personas, status). The parser is pure;
  ACL validation against the user/persona tables is a separate pass.
- A GPU-accelerated embedding path that stays out of the Newton process:
  **Qdrant** (vector store) and **TEI** (HuggingFace text-embeddings-
  inference serving **BGE-M3**, 1024-dim, multilingual) run in Docker with
  CDI GPU passthrough; Newton talks to them over HTTP. No PyTorch is
  imported in-process.
- A scan → chunk → index pipeline: an incremental scanner (mtime then
  content-hash) with a SQLite ACL cache, a heading-aware chunker with
  token-budget sub-splitting and overlap, and an indexer that writes an
  ACL snapshot into each Qdrant point's payload.
- ACL-filtered semantic search: a query is answered only with chunks the
  asking `(user_id, persona_id)` is allowed to read, enforced as a Qdrant
  payload filter at query time, not in Python after the fact.
- A persona engine with two-stage activation routing and ownership
  enforcement: a public persona answers to anyone, an owned persona only
  to its owner, otherwise the caller falls back to their default. System
  prompts render `${OWNER_DISPLAY_NAME}` from the live user row.
- Two built-in tools wired into block 2's approval circuit:
  `vault_search` (risk 1, READ_LOCAL) and `vault_write` (risk 2,
  WRITE_LOCAL, guests forced into quarantine, re-indexes on save).
- A biasing hook: every vault save runs spaCy NER (`ko_core_news_sm` +
  `en_core_web_sm`, CPU-only) plus a regex pass for technical patterns,
  and merges the entities into the writing user's STT contextual-biasing
  dictionary.
- Session summarization: a finished conversation is condensed into a
  private vault note (topics / decisions / action items / sentiment) via
  an injectable `SessionSummarizer`, so the actual model is a later-block
  concern while the build-and-store path is testable now.
- A guest quarantine workflow: orphan quarantine files are reconciled
  into `guest_activity` rows, and each item is reviewed by id
  (promote / shared / reject / hold) with the file moved, the status
  recorded, and the vault re-indexed. JARVIS renders a deterministic
  "welcome back" briefing of pending guest activity.
- Migrations 006–009 (vault notes, indexed-hash column, user biasing
  dict, session summarized-at).
- A CLI surface across `newton vault` (index / search / quarantine
  list / quarantine review), `newton persona route`, `newton voice
  biasing` (show / clear), and `newton memory` (summarize-session /
  recall).
- 130 new pytest cases (**284 total** in `tests/newton/`: 245 unit plus
  39 behind live `qdrant` / `embedding` markers).

What this block deliberately does **not** include: an LLM actually
producing the conversation summaries or the briefing prose (the seams
exist; the model is injected in a later block), a real event/timer wiring
for summarization triggers (block 5 runtime), voice handling for the
quarantine decision verbs (block 5), and any network retrieval into the
vault (block 7).

## Steps and commits

| Step | Outcome                                                        | Commit     |
|------|----------------------------------------------------------------|------------|
| 3.1  | TEI service for BGE-M3 (GPU via CDI), Phase 0 infra            | `87f23a9`  |
| 3.2  | Decorator-based provider auto-discovery; embedding service via TEI backend | `3108d9c`, `a8ded23` |
| 3.3  | Markdown parser with ACL extraction (`status_explicit`)        | `2633d25`  |
| 3.4  | Vault scanner with SQLite ACL cache (migration 006)            | `a14f526`  |
| 3.5  | Chunking + Qdrant indexing (migration 007)                     | `eda677f`  |
| 3.6  | ACL-filtered RAG search (Option C payload filter)              | `f04c802`  |
| 3.7  | Persona engine: 2-stage activation routing, ownership check    | `da09c49`  |
| 3.8  | `vault_search` / `vault_write` tools wired to approval hook    | `2eee92f`  |
| 3.9  | NER-driven biasing hook (migration 008)                        | `142b136`  |
| 3.10 | Session auto-summarization (migration 009)                     | `150c62b`  |
| 3.11 | Guest quarantine workflow + JARVIS briefing scaffold           | `9fa9363`  |
| 3.12 | This summary + tag `v0.3.0-block3`                             | (this tag) |

## Key design decisions (locked)

These shape every following block.

**GPU work lives in containers, never in the Newton process.**
The RTX 5090 (Blackwell, sm_120) needs nightly PyTorch builds that the
in-process path can't rely on. So embeddings are served by TEI in Docker
and reached over HTTP; spaCy runs CPU-only (thinc/blis, no torch). The
Newton process imports no CUDA-bound library. This "strategy D" keeps the
core importable and testable anywhere.

**The vault is ACL-first.**
Every note's access is declared in its own frontmatter, parsed into an
`ACL`, and snapshotted into the vector store. Search filters on that
snapshot at query time. A note with an owner but no explicit `status` is
treated as canonical (`status_explicit` tracks whether the field was
actually written) — owning a note shouldn't silently hide it from your
own search.

**Search filtering is a vector-store concern, not a post-filter.**
ACL is enforced as a Qdrant `must` filter (status match AND
(read_users matches OR owner matches) AND read_personas matches the
persona or the `*` wildcard). Filtering in Python after retrieval would
leak result counts and waste recall; the store does it.

**Identity flows through, content hashes whole.**
A note's `content_hash` is the sha256 of the entire raw file including
frontmatter, so editing an ACL re-indexes the note. Search always carries
the caller's `(user_id, persona_id)`; tools pass it from `ToolContext`.

**New tools inherit safety for free.**
`vault_search` and `vault_write` only declare a `RiskLevel`. Dispatch's
existing policy/approval hook (block 2) gates them — read auto-allows,
write requires approval — with no new approval code. A guest (not in the
user table) writing to the vault is forced into `_guest_quarantine/`
regardless of the path requested.

**Memory model calls sit behind seams, not hardcoded model names.**
Session summarization depends on a `SessionSummarizer` ABC, not on
"Qwen 2.5 32B". `FakeSummarizer` makes the build-and-store path
deterministic and offline-testable; the real model is injected by a
later block. The guest briefing needs no model at all — it is a
deterministic count by activity type, matching the documented output.

**Guest review is keyed by primary key, with files reconciled in.**
`guest_activity.activity_id` is the source of truth for a review
decision — a primary key is never ambiguous, and every decision records
status + reviewed_at + reviewed_by. Files that reached quarantine without
a row are folded in first by `reconcile()`, so review always operates on
a real record and the decision trail is complete.

**Briefing pluralization and ordering are deterministic.**
The briefing renders counts in a fixed type order with correct English
plurals (`web searches`, not `web searchs`), so the same pending set
always produces the same text — testable without a model.

**Test expectations stay filesystem-derived.**
Block 2's `_schema_helpers.py` pattern continues to pay off: migrations
006–009 and the new models needed zero edits to earlier blocks' tests.
The one place this surfaced — adding `users.stt_bias_dict_json` (a column
on an existing table, unlike the new tables of 006/007) — was fixed once
by making the model/seed test fixtures apply *all* migrations in order
rather than only migration 001, so any future ALTER is covered.

## What you can do after this block

```bash
# Index the vault into Qdrant (scan + chunk + embed + upsert)
uv run newton vault index

# ACL-filtered semantic search as a given user/persona
uv run newton vault search "architecture" --user sir --persona jarvis

# Route a Stage-2 activation signal to a persona and render its prompt
uv run newton persona route --user sir --voice-stage2 jarvis --show-prompt

# Inspect / clear a user's STT biasing dictionary
uv run newton voice biasing show --user sir
uv run newton voice biasing clear --user sir

# Condense a finished session into a searchable vault note
uv run newton memory summarize-session T1234
uv run newton memory recall "block 3 design" --user sir --persona jarvis

# Review guest activity held in quarantine
uv run newton vault quarantine list
uv run newton vault quarantine review 1 --decision promote --by sir
```

## Verification

Block-3 acceptance criteria, all met:

- `uv run newton init` applies migrations 001 through 009; idempotent.
- `uv run newton vault index` populates the Qdrant `vault` collection
  (1024-dim points with an ACL payload snapshot).
- `uv run newton vault search` returns only chunks the asking
  `(user, persona)` may read; a Korean query matches an English chunk
  (BGE-M3 is cross-lingual).
- `uv run newton persona route --user sir --voice-stage2 jarvis
  --show-prompt` renders "personal assistant to Alex"; an unowned
  persona falls back to the caller's default.
- `vault_search` and `vault_write` run end-to-end through dispatch;
  writes are gated, guests are quarantined, and the note is searchable
  immediately after write.
- A vault save updates the writer's biasing dict
  (`RTX 5090`, `BGE-M3`, `Qdrant`, `Newton` all captured).
- `uv run newton memory summarize-session` writes a private note under
  `_auto/conversations/` that `recall` then finds.
- `uv run newton vault quarantine list` / `review` move a quarantined
  file to `notes/` or `shared/`, record the decision, and re-index.
- `uv run pytest tests/newton/` reports **245 passed** (unit), with a
  further **39** behind the live `qdrant` / `embedding` markers — **284
  total**.
- OpenJarvis files: still zero modifications.

## Known limits (resolved in later blocks)

- **No LLM produces the summaries or briefings yet.** `FakeSummarizer`
  and the deterministic briefing exercise the path; a real model slots
  in behind `SessionSummarizer` / `render_briefing` in a later block.
- **Summarization triggers are pure policy, not wired to events.**
  `find_due_sessions` decides *what* to summarize given a clock; the
  real "session ended" signal and idle timer belong to the block-5
  runtime.
- **Quarantine decision verbs are CLI-only.** The spoken forms
  ("promote the RTX one", "discard all") map to these CLI commands;
  voice handling lands in block 5.
- **Embeddings require the Docker services up.** `vault index` /
  `search` and the `qdrant` / `embedding`-marked tests need Qdrant + TEI
  running (`scripts/newton/{qdrant,tei}-up.sh`). The unit suite does not.
- **STT biasing dict is written, not yet consumed.** Block 5's STT call
  reads `users.stt_bias_dict_json` for contextual biasing; block 3 only
  populates it.

## Entry conditions for block 4

Block 4 can assume:

- `newton init` applies migrations 001–009.
- The vault is searchable: `newton vault index` populates Qdrant and
  `newton vault search` enforces ACL for `(user, persona)`.
- `newton persona route` resolves `${OWNER_DISPLAY_NAME}` from the live
  user row.
- `vault_search` and `vault_write` work end-to-end through the block-2
  approval circuit.
- The spaCy NER hook updates the user biasing dict on every vault save.
- `newton memory summarize-session` produces searchable notes; the
  `SessionSummarizer` seam is where a real model attaches.
- `newton vault quarantine` list/review operate on `guest_activity` by
  id, with orphan files reconciled.
- `tests/newton/_schema_helpers.py` and the all-migrations test fixtures
  mean new tables or columns in block 4 need no edits to earlier tests.

If `newton status` reports everything green and `uv run pytest
tests/newton/` shows 245 passed (plus 39 marker tests with the Docker
services up), block 4 is good to start.
