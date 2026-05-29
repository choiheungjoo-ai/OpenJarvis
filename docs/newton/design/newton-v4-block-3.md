# Newton v4 — Block 3: Persona Engine + Vault + ACL + RAG + Long-term Memory

> Master plan: `newton-v4-master.md`
> Tech stack: `newton-v4-tech-stack.md`
> Voice (vault → biasing hook): `newton-v4-voice.md` §2.5
> Terminology: `TERMINOLOGY.md`
> Prerequisite: Block 2 complete (`v0.2.0-block2`, `docs/newton/design/newton-v4-block-2.md`)
>
> **Goal:** Give Newton its knowledge memory. After this block, Newton can
> read sir's notes, respect ACL, do persona-aware RAG, and start
> remembering conversations long-term.

---

## 0. Block 3 — overall goals

This is the block where Newton starts to *know things*. Five concerns
wired together:

1. **Persona Engine** — route user input to the right persona based on
   2-stage activation (Stage 2: voice naming or face binding), set the
   system prompt, resolve `${OWNER_DISPLAY_NAME}` / `${PARTNER_DISPLAY_NAME}`.
2. **Vault parser** — read Obsidian-style markdown files under
   `data/vault/notes/` and `data/vault/shared/`, extract frontmatter
   (ACL + tags), index for search.
3. **ACL enforcement** — every read goes through the per-note ACL.
   Persona X cannot see notes that exclude it. User Y cannot see
   notes whose `read_users` doesn't include them.
4. **Persona-aware RAG** — single Qdrant index, ACL-filtered at query
   time. BGE-M3 embeddings. Query → context → LLM injection.
5. **Long-term memory** — conversations auto-summarized at session
   close, stored as auto-generated vault notes, searchable via RAG
   later. Foundation for proactive recall (block 4).

Vault → biasing hook (the STT side) is the final wiring step — after
the parser is solid, every save updates the user's STT Contextual
Biasing dictionary via spaCy NER.

### Locked decisions (entering Block 3)

| Item | Decision | Source |
|------|----------|--------|
| **Vault format** | Obsidian markdown + YAML frontmatter | master.md §3, §5 |
| **Storage location** | `data/vault/notes/` (canonical), `data/vault/shared/` (shared), `data/vault/_guest_quarantine/` (pending) | master.md §3.3 |
| **Vector DB** | Qdrant (local, Docker), Apache 2.0 | tech-stack.md §1 |
| **Embedding model** | BGE-M3 (Korean-strong, MIT) | tech-stack.md §1 |
| **ACL source of truth** | YAML frontmatter on the note itself; SQLite cache for fast queries | sir's design |
| **RAG architecture** | Single Qdrant collection; ACL filter applied at query time (not per-persona collections) | reduces index duplication |
| **Long-term memory location** | `data/vault/_auto/conversations/` (auto-generated notes, ACL-tagged to user) | master.md §5 |
| **Auto-summary trigger** | On `ChatSession` close (graceful), with timeout-based fallback for crashed sessions | sir's design |
| **Vault → biasing hook** | On every vault save, spaCy NER extracts entities, adds to `users.stt_bias_dict_json` | voice.md §2.5 |
| **Guest quarantine RAG** | Excluded from RAG queries until sir promotes the note | master.md §3.3 |
| **Approval hook (from block 2)** | Wired to vault writes — block 3 turns "log decision only" into "log decision + actually save to vault" | block 2 deferred |
| **Provider registry usage** | Embedding becomes a provider (`embedding.encode` capability) for future hot-swap (e.g. multilingual-e5) | engines.md pattern |

### Completion criteria (block as a whole)

```bash
# Vault commands work
$ uv run newton vault index
indexed 0 notes (vault empty)

$ echo "test note" > data/vault/notes/test.md
$ uv run newton vault index
indexed 1 note, 1 chunk, 1 embedding

$ uv run newton vault search "test"
1 result:
  data/vault/notes/test.md  (score: 0.82)

# ACL enforcement
$ cat > data/vault/notes/secret.md <<EOF
---
acl:
  owner: sir
  read_users: [sir]
  read_personas: [jarvis]
---
sir's secret content
EOF

$ uv run newton vault search "secret" --user gf
0 results (ACL filtered)

$ uv run newton vault search "secret" --user sir
1 result: data/vault/notes/secret.md

# Persona routing
$ uv run newton persona route --user sir --voice-stage2 "jarvis"
persona: jarvis (owner: sir)
system_prompt: rendered with ${OWNER_DISPLAY_NAME} → Alex

# RAG end-to-end (via tool)
$ uv run newton tools run vault_search --args '{"query":"test","user":"sir","persona":"jarvis"}'
ToolResult(status=ok, data={"matches": [...]})

# Long-term memory
$ uv run newton memory summarize-session <session_id>
Created: data/vault/_auto/conversations/2026-05-29-T1234.md

$ uv run newton memory recall "what did sir ask about Newton last week"
3 matches across conversation summaries.

# Vault → biasing hook
$ uv run newton voice biasing show --user sir
Entities in sir's biasing dict: 42
  "Newton" "RTX 5090" "BGE-M3" "Qdrant" ...

# Tests
$ uv run pytest tests/newton/ -v
# Block 1: 38 + Block 2: ~55 + Block 3: ~80 = ~173 passed
```

Block 3 ships **real knowledge handling.** Newton can store, retrieve,
remember, and respect access controls.

---

## 1. Block 3 — 12 steps

Each step: one focused change, one verification, one commit. `ruff check` +
`ruff format` before every commit.

Estimated total: **15–25 days at sir's pace.** Block 3 is the heaviest
foundation block.

---

### Step 3.1 — Qdrant installation + smoke test (half-day)

**Goal:** Get Qdrant running locally and confirmed reachable.

**Outputs:**

- `docker-compose.yml` — Qdrant service definition
- `scripts/newton/qdrant-up.sh`, `qdrant-down.sh`
- `newton/vault/qdrant_client.py` — minimal wrapper
- `tests/newton/vault/test_qdrant_smoke.py`

**Verification:**

```bash
docker compose up -d qdrant
curl http://localhost:6333/healthz
uv run pytest tests/newton/vault/test_qdrant_smoke.py -v
```

**Risk:** Docker Desktop / WSL2 Docker integration issues. **Mitigation:**
fallback to bare `qdrant-binary` install (Apache 2.0).

**Commit:** `feat(vault): qdrant local instance + smoke test`

---

### Step 3.2 — BGE-M3 embedding loader (half-day)

**Goal:** Load BGE-M3 once at process start, embed text efficiently.

**Outputs:**

- `newton/vault/embeddings.py`
  - `class EmbeddingService` — lazy loader, batch encode
  - Korean + English in one call (BGE-M3 is multilingual)
- `tests/newton/vault/test_embeddings.py`

**Provider integration:**

EmbeddingService is registered as a Provider for capability `embedding.encode`
(block 2 pattern). Default and only provider for now; future block can
hot-swap to e5-mistral, etc.

**Verification:**

```bash
uv run pytest tests/newton/vault/test_embeddings.py -v
# Korean sentence → 1024-dim vector
# English sentence → 1024-dim vector
# Batch of 10 sentences → 10 vectors
```

**Risk:** First load is slow (~30 sec) and uses ~2 GB VRAM.
**Mitigation:** singleton pattern, warm-up at app start.

**Commit:** `feat(vault): BGE-M3 embedding service`

---

### Step 3.3 — Vault parser + frontmatter ACL extraction (1 day)

**Goal:** Read a markdown file, parse YAML frontmatter, validate ACL
structure.

**Outputs:**

- `newton/vault/parser.py`
  - `class VaultNote` — pydantic model (path, frontmatter, body, hash)
  - `class ACL` — pydantic model (owner, read_users, read_personas, write_users, write_personas, tags, status)
  - `parse(path) -> VaultNote`
- `tests/newton/vault/test_parser.py`
- 3 sample notes under `tests/newton/vault/fixtures/`

**ACL schema:**

```yaml
---
acl:
  owner: sir                    # required, single user_id
  read_users: [sir, gf]         # default: [owner]
  read_personas: [jarvis]       # default: persona owned by owner
  write_users: [sir]            # default: [owner]
  write_personas: []            # default: []
  status: canonical             # canonical | shared | pending_review
tags: [project, newton]
---
```

**Validation rules:**

- `owner` must be an existing user_id in the database
- `read_users` / `write_users` must reference existing users
- `read_personas` / `write_personas` must reference existing personas
- Unknown ACL keys → warning, not error (forward compatibility)
- Missing `acl` block → fall back to "private to owner" inferred from path
  (e.g. `data/vault/notes/sir-private/X.md` → owner: sir)

**Verification:**

```bash
uv run pytest tests/newton/vault/test_parser.py -v
# Parse note with full ACL, partial ACL, no ACL, malformed ACL
```

**Commit:** `feat(vault): markdown parser with ACL extraction`

---

### Step 3.4 — Vault scanner + SQLite ACL cache (1 day)

**Goal:** Walk `data/vault/`, find all `.md` files, populate SQLite
cache for fast ACL queries without re-parsing each time.

**Outputs:**

- `migrations/005_vault.sql` — `vault_notes`, `vault_chunks` tables
- `newton/models/vault.py` — ORM models
- `newton/vault/scanner.py`
  - `scan(vault_dir) -> list[VaultNote]`
  - Incremental: only re-parses if file mtime changed
- `tests/newton/vault/test_scanner.py`

**Schema:**

```sql
CREATE TABLE vault_notes (
    note_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path             TEXT NOT NULL UNIQUE,        -- relative to data/vault/
    owner_user_id    TEXT NOT NULL,
    read_users_json  TEXT NOT NULL,               -- JSON array
    read_personas_json TEXT NOT NULL,
    write_users_json TEXT NOT NULL,
    write_personas_json TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'canonical',
    tags_json        TEXT,
    content_hash     TEXT NOT NULL,               -- SHA-256 of body
    indexed_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_user_id) REFERENCES users(user_id) ON DELETE SET NULL
);

CREATE INDEX idx_vault_notes_owner ON vault_notes(owner_user_id);
CREATE INDEX idx_vault_notes_status ON vault_notes(status);
```

**Verification:**

```bash
uv run pytest tests/newton/vault/test_scanner.py -v
# Empty vault → 0 notes
# 3 sample notes → 3 rows in vault_notes
# Modify one note → re-scan only updates that row
```

**Commit:** `feat(vault): vault scanner with SQLite ACL cache + migration 005`

---

### Step 3.5 — Chunking + Qdrant indexing (1.5 days)

**Goal:** Split note bodies into chunks, embed each chunk, store in
Qdrant with ACL metadata.

**Outputs:**

- `newton/vault/chunker.py` — markdown-aware splitter (heading-based, with sentence overlap)
- `newton/vault/indexer.py` — orchestrates parse → chunk → embed → upsert
- `newton/cli.py` — `newton vault index [--force]`
- `tests/newton/vault/test_chunker.py`
- `tests/newton/vault/test_indexer.py`

**Chunk strategy:**

- Split at `##` headings primarily; secondary split if a section is >800 tokens
- 50-token overlap between adjacent chunks (preserves context across boundaries)
- Each chunk carries: `note_id`, `chunk_index`, `text`, `embedding`, `acl_snapshot`

**Qdrant point payload:**

```json
{
    "note_id": 123,
    "chunk_index": 0,
    "path": "notes/projects/newton.md",
    "owner_user_id": "sir",
    "read_users": ["sir", "gf"],
    "read_personas": ["jarvis"],
    "status": "canonical",
    "tags": ["project", "newton"],
    "text": "first 200 chars of chunk..."
}
```

**Verification:**

```bash
echo "# Newton\n\nFirst section.\n\n## Architecture\n\nSecond." > data/vault/notes/sample.md
uv run newton vault index
# 1 note, 2 chunks (split by ##), 2 Qdrant points

uv run newton vault index   # idempotent — content hash unchanged
# 0 changes

echo "modified" >> data/vault/notes/sample.md
uv run newton vault index
# 1 note re-indexed, 2 chunks replaced
```

**Risk:** Embedding 1000 notes takes ~5 minutes. Acceptable for now;
async batching can come later.

**Commit:** `feat(vault): chunking + Qdrant indexing`

---

### Step 3.6 — ACL-filtered RAG search (1.5 days)

**Goal:** Query vault with semantic search, filter results by who is asking
and which persona is active.

**Outputs:**

- `newton/vault/search.py`
  - `search(query, user_id, persona_id, limit=5, status_filter='canonical') -> list[SearchHit]`
  - Embeds query → Qdrant query with payload filter → returns results
- `newton/cli.py` — `newton vault search "<query>" [--user X] [--persona Y]`
- `tests/newton/vault/test_search.py`

**ACL filter at query time (Qdrant payload filter):**

```python
filter = {
    "must": [
        {"key": "status", "match": {"value": status_filter}},
        {
            "should": [
                {"key": "read_users", "match": {"any": [user_id]}},
                {"key": "owner_user_id", "match": {"value": user_id}}
            ]
        },
        {"key": "read_personas", "match": {"any": [persona_id, "*"]}}  # "*" = any persona
    ]
}
```

**Note on guest quarantine:** the search function defaults to
`status_filter='canonical'`, which excludes `pending_review` (guest
quarantine) and `shared` content unless explicitly requested.

**Verification:**

The Step 0 completion-criteria block shows the expected behaviour. The
test suite covers: owner sees own note, non-owner without `read_users`
grant doesn't, persona filtering, status filtering, multi-user shared
notes.

**Commit:** `feat(vault): ACL-filtered RAG search`

---

### Step 3.7 — Persona Engine + render_personality wiring (1 day)

**Goal:** Given a user and a persona, build the LLM system prompt with
the right display names substituted.

**Outputs:**

- `newton/persona/engine.py`
  - `class PersonaEngine`
  - `route(user_id, stage2_signal) -> PersonaActivation` — handles Path A (voice naming) and Path B (face binding)
  - `render_system_prompt(persona_id, user_id) -> str` — applies `${OWNER_DISPLAY_NAME}` / `${PARTNER_DISPLAY_NAME}`
- `newton/cli.py` — `newton persona route --user X --voice-stage2 Y` (or `--face-stage2`)
- `tests/newton/persona/test_engine.py`

**2-stage activation (block 5 + block 6 do the actual sensors; block 3
just exposes the routing logic):**

```python
def route(user_id: str, stage2_signal: Stage2Signal) -> PersonaActivation:
    """
    stage2_signal is one of:
      - VoiceNamingSignal(persona_name="JARVIS")  → activate that persona for user
      - FaceBindingSignal()                       → activate user's default persona
    """
```

**`render_personality()` for block 3:**

This is the function block 1 left as the canonical placeholder. Block 3
implements it fully:

```python
def render_personality(persona: Persona, owner: User, partner: User | None) -> str:
    template = persona.personality
    rendered = template.replace("${OWNER_DISPLAY_NAME}", owner.display_name)
    if partner:
        rendered = rendered.replace("${PARTNER_DISPLAY_NAME}", partner.display_name)
    return rendered
```

**Verification:**

```bash
uv run newton persona route --user sir --voice-stage2 jarvis
# persona: jarvis
# rendered system prompt with "Alex" substituted

uv run newton persona route --user gf --face-stage2
# persona: friday (gf's default)
# rendered system prompt with "Stella" substituted

uv run pytest tests/newton/persona/ -v
```

**Commit:** `feat(persona): persona engine with 2-stage activation routing`

---

### Step 3.8 — `vault_search` and `vault_write` tools (1 day)

**Goal:** Expose vault search and write as block-2 tools, fully wired
through the approval hook.

**Outputs:**

- `newton/tools/builtin/vault_search.py` — risk 1 (READ_LOCAL), reads RAG with ACL
- `newton/tools/builtin/vault_write.py` — risk 2 (WRITE_LOCAL), saves new note + triggers re-index + triggers biasing hook
- `tests/newton/tools/test_vault_tools.py`

**`vault_search` tool:**

- Args: `{query: str, limit: int = 5}`
- Context provides `user_id` and `persona_id`
- Returns matches with paths, scores, snippets
- Risk: 1 (READ_LOCAL) — default auto_allow

**`vault_write` tool:**

- Args: `{path: str, content: str, frontmatter: dict}`
- Context provides `user_id` and `persona_id`
- Path must be under `data/vault/notes/` (sir's canonical area) or `data/vault/shared/`
- For guests: forced to `data/vault/_guest_quarantine/` regardless of requested path
- Risk: 2 (WRITE_LOCAL) — default require_approval
- On success: re-indexes the new note + fires biasing hook

**Approval hook wiring (the deferred piece from block 2):**

Block 2 logged decisions but didn't write to vault. Block 3 makes the
"save? share?" flow real:

```
LLM produces a tool call: vault_write(path=..., content=...)
    ↓
ToolRegistry.dispatch → ApprovalChannel.request_approval
    ↓
sir sees: "JARVIS wants to save a note. Path: ... Content: ... Approve?"
    ↓
sir: yes
    ↓
vault_write executes → note saved → re-indexed → biasing dict updated
log: decision=allowed, decided_by=sir, channel=cli, [block 3 addition:] vault_path=...
```

**Verification:**

```bash
uv run newton tools run vault_search --args '{"query":"newton"}' --user sir --persona jarvis
# returns matches

uv run newton tools run vault_write --args '{"path":"notes/test.md","content":"# Test","frontmatter":{}}' \
    --user sir --persona jarvis --auto-yes
# saves note, re-indexes, returns success

ls data/vault/notes/test.md
# exists

uv run newton vault search "test"
# finds it
```

**Commit:** `feat(tools): vault_search and vault_write tools wired to approval hook`

---

### Step 3.9 — Vault → biasing hook (spaCy NER) (1.5 days)

**Goal:** Every vault save extracts named entities; entities get added
to the writing user's STT Contextual Biasing dictionary.

**Outputs:**

- `newton/vault/biasing_hook.py`
  - `extract_entities(text: str, lang: str) -> list[str]`
  - `update_user_biasing(user_id: str, entities: list[str])`
- `migrations/006_user_biasing.sql` — adds `stt_bias_dict_json` column to `users`
- `newton/cli.py` — `newton voice biasing show --user X`, `newton voice biasing clear --user X`
- `tests/newton/vault/test_biasing_hook.py`

**Dependency:**

```bash
uv add spacy
uv run python -m spacy download ko_core_news_sm   # Korean NER
uv run python -m spacy download en_core_web_sm    # English NER (optional)
```

**Flow:**

```
vault_write executes
    ↓
biasing_hook.on_vault_save(note, user_id)
    ↓
spaCy NER on note body
    ↓
extract entities (PERSON, ORG, PRODUCT, GPE, etc.)
    ↓
deduplicate against existing user dict
    ↓
update users.stt_bias_dict_json
    ↓
[block 5 reads this dict at every STT call for Contextual Biasing]
```

**Verification:**

```bash
uv run newton tools run vault_write \
    --args '{"path":"notes/test.md","content":"Newton uses RTX 5090 and BGE-M3.","frontmatter":{}}' \
    --user sir --persona jarvis --auto-yes

uv run newton voice biasing show --user sir
# Newton, RTX 5090, BGE-M3 (3 entities added)
```

**Risk:** spaCy Korean model has known limitations on technical terms
(e.g. "BGE-M3" might not be recognized as an entity). **Mitigation:**
add a regex post-pass for known technical patterns (model names, version
numbers, all-caps acronyms).

**Commit:** `feat(vault): NER-driven biasing hook with migration 006`

---

### Step 3.10 — Long-term memory: session summarization (2 days)

**Goal:** When a `ChatSession` ends, auto-summarize and save as a vault
note. Searchable via RAG.

**Outputs:**

- `newton/memory/summarizer.py`
  - `summarize_session(session_id) -> VaultNote`
  - Uses Qwen 2.5 32B with a focused prompt (key topics, decisions, action items, sentiment)
- `newton/memory/triggers.py`
  - On `ChatSession.end()` event → schedule summarization
  - Idle timeout (30 min no messages) → also triggers
- `newton/cli.py` — `newton memory summarize-session <session_id>`, `newton memory recall "<query>"`
- `migrations/007_session_close.sql` — adds `summarized_at` column to `sessions`
- `tests/newton/memory/test_summarizer.py`

**Output note format:**

```markdown
---
acl:
  owner: sir
  read_users: [sir]
  read_personas: [jarvis]
  status: canonical
tags: [conversation, auto, 2026-05-29]
session_id: T1234
persona: jarvis
duration_min: 12
---

# Conversation 2026-05-29 14:30

## Topics
- Newton block 3 design
- BGE-M3 vs alternatives

## Key decisions
- Use Qdrant (already decided)
- ACL filter at query time

## Action items
- None for sir
- Newton to index 100 sample notes for testing

## Sentiment
Focused, technical, no friction.
```

**Path:** `data/vault/_auto/conversations/2026-05-29-T1234.md`

**ACL:** auto-set to "owner: <user_id>, read_users: [<user_id>],
read_personas: [<persona_id>]" — private by default.

**Verification:**

```bash
# Start a session, send a few messages, end it
# (Real flow needs block 5; for block 3 we test with synthetic session data)

uv run newton memory summarize-session T1234
# Created: data/vault/_auto/conversations/2026-05-29-T1234.md

uv run newton vault search "block 3 design"
# Finds the conversation summary

uv run newton memory recall "what did sir decide about embeddings"
# Returns relevant conversation summaries
```

**Risk:** Qwen 2.5 32B summarization can be slow (~5–15 sec per session).
Async scheduling means it doesn't block the user. **Mitigation:** use
Qwen 2.5 7B for short sessions (<10 messages), 32B only for long ones.

**Commit:** `feat(memory): session auto-summarization with migration 007`

---

### Step 3.11 — Guest quarantine + JARVIS briefing (1.5 days)

**Goal:** Wire the design that's been waiting since master.md §3.3.
Guest learning lands in quarantine; JARVIS auto-briefs sir when sir
returns.

**Outputs:**

- `newton/vault/quarantine.py`
  - `promote_to_canonical(note_path)` / `move_to_shared(note_path)` / `reject(note_path)`
- `newton/memory/briefing.py`
  - `generate_briefing(since: datetime) -> Briefing`
  - On sir's Stage-2 activation → check for pending guest activity → JARVIS speaks it
- `newton/cli.py` — `newton vault quarantine list`, `newton vault quarantine review <path>`
- `tests/newton/vault/test_quarantine.py`
- `tests/newton/memory/test_briefing.py`

**Briefing output (rendered by JARVIS at next activation):**

```
"Welcome back, sir. Briefing on guest activity in your absence:
 - 2 web searches (RTX 5090 driver, Korean weather)
 - 1 code analysis (Python function debugging)
 - 3 learning candidates in quarantine.
 How would you like to proceed?"
```

**Decision verbs (sir's response):**

```
"show each"          → list each quarantined item
"discard all"        → reject all pending
"promote the RTX one" → move to canonical vault
"shared for the weather" → move to shared/
"hold the code one"  → keep in quarantine
```

These map to CLI commands behind the scenes; voice handling lands in
block 5.

**Verification:**

```bash
# Simulate guest activity
mkdir -p data/vault/_guest_quarantine
echo "guest content" > data/vault/_guest_quarantine/2026-05-29-search.md
uv run newton vault index

uv run newton vault quarantine list
# 1 pending item: 2026-05-29-search.md

uv run newton vault quarantine review 2026-05-29-search.md --decision promote --target notes/
# moves to data/vault/notes/2026-05-29-search.md
# re-indexes
# logs decision
```

**Commit:** `feat(vault): guest quarantine workflow + JARVIS briefing scaffold`

---

### Step 3.12 — Block 3 summary + tag (1–2 hours)

**Goal:** Lock the block, list what shipped, define Block 4 entry conditions.

**Outputs:**

- `docs/newton/block-3-summary.md` — same tone as block-1-summary, block-2-summary
- `docs/newton/cli.md` — final pass to confirm every new command is documented
- `README.md` — Block 3 marked complete
- `pyproject.toml` — lockfile tidied
- Git tag: `v0.3.0-block3`

**Block 4 entry conditions (provisional):**

- `newton vault search` works with ACL
- `newton vault index` populates Qdrant
- `newton persona route` resolves `${OWNER_DISPLAY_NAME}` correctly
- `vault_search` and `vault_write` tools work end-to-end
- spaCy NER hook updates user biasing dict on every vault save
- `newton memory summarize-session` produces searchable notes
- `newton vault quarantine` commands work
- All pytest cases pass (~173 total)
- Preflight 9/9 still ✓
- OpenJarvis: still 0 files modified

**Verification:**

```bash
git log --oneline | head -20
git tag -l | grep block3

uv run newton status   # vault + memory counts reflected
```

**Commit + tag:** `chore: block 3 complete`

---

## 2. Deliberately not in Block 3

- ❌ **Voice / STT / TTS** — block 5. Block 3's biasing hook *prepares*
  the dictionary; block 5 actually consumes it.
- ❌ **Face recognition** — block 6. Block 3's persona engine *handles*
  Path B (face binding) routing; block 6 produces the FaceID signal.
- ❌ **Proactive recall** — block 4. Block 3 stores conversation
  summaries; block 4 decides *when* to surface them.
- ❌ **Real-time conversation streaming** — block 5. Block 3 works on
  completed sessions.
- ❌ **Multi-user simultaneous vault writes** — block 9 (if at all).
  Block 3 is serial-write.
- ❌ **LoRA per persona** — block 10. Conditional on vault size first.
- ❌ **Real web search / external tools** — blocks 7, 9.

Principle still: *add when needed, not before.*

---

## 3. Risk matrix

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Qdrant Docker on WSL2 flakiness | Med | Fallback to qdrant-binary; smoke test in step 3.1 catches early |
| BGE-M3 ~2 GB VRAM permanently reserved | Med | Singleton; only one instance per process |
| ACL filter performance at >10k notes | Low | Qdrant payload filters are indexed; revisit at 10k threshold |
| ACL parsing accepts malformed YAML | Med | Pydantic validation in step 3.3; warnings for unknown keys |
| Auto-summary uses Qwen 2.5 32B = slow | Med | Async; small sessions use 7B (step 3.10) |
| spaCy Korean NER misses technical terms | Med | Regex post-pass for known patterns (step 3.9) |
| Long-term memory notes pollute search results | Med | Separate status tag + default exclude from non-recall searches |
| Vault → biasing hook fires too often (every chunk) | Low | Fires per *note*, not per chunk |
| Guest quarantine + briefing interplay with block 4 | Med | Briefing scaffold in block 3; full proactive delivery in block 4 |
| Provider registration for embedding adds complexity | Low | Single provider for now; capability defined for future swap |
| 15–25 day estimate is itself uncertain | Med | Re-estimate after step 3.6 (mid-block checkpoint) |

---

## 4. After Block 3 — opening message for the next chat

Copy-paste this when starting Block 4:

```markdown
# Newton v4 — Block 4 start (⭐ Proactive Engine)

## Context
- Newton: multi-persona AI OS, OpenJarvis fork
- Environment: RTX 5090 + WSL2 Ubuntu + systemd
- Location: ~/newton-v4/

## Design docs (all English from this point)
[newton-v4-master.md]
[newton-v4-tech-stack.md]
[newton-v4-engines.md]
[newton-v4-voice.md]
[newton-v4-jarvis-gap.md]   # block 4 details
[newton-v4-block-3.md]      # complete
[newton-v4-block-4.md]      # this block
[TERMINOLOGY.md]

## Blocks 1–3 result
- v0.1.0-block1: identity & data foundation (13 tables)
- v0.2.0-block2: tool calling + approval hook + provider registry
- v0.3.0-block3: persona engine + vault + ACL + RAG + long-term memory
  - Qdrant indexed
  - vault_search, vault_write tools
  - spaCy NER biasing hook (feeds block 5 STT)
  - Session auto-summarization
  - Guest quarantine + briefing scaffold

## Next
Block 4 step 4.1 — monitoring daemon foundation.
```

---

## 5. Honest reality check

**Time estimate:** **15–25 days at sir's pace.** Block 3 is heavier than
block 2 because it touches more subsystems (vault, embedding, vector DB,
NER, memory).

**Riskiest steps:**

- **Step 3.5** (chunking + indexing) — embedding cost, chunk strategy
  tuning
- **Step 3.6** (ACL-filtered search) — Qdrant payload filter syntax can
  be tricky; over-permissive filters leak data
- **Step 3.10** (session summarization) — first time we wire LLM into
  a background task

**Simplest steps:**

- 3.1 (Qdrant smoke), 3.2 (BGE-M3 load), 3.12 (summary)

**Most important step:**

- **Step 3.6** (ACL-filtered RAG). This is *the privacy boundary*. If
  this leaks, sir loses trust. Spend extra test coverage here.

**Most exciting step:**

- **Step 3.10** (long-term memory) — first time Newton starts *remembering*
  conversations. Big behavioral shift.

**Assets carried over from Block 2:**

- Tool abstraction → `vault_search`, `vault_write` tools
- Approval hook → wires to vault writes (the deferred piece)
- Provider registry → embedding service registered
- Approval channel → CLI prompt still used; voice channel comes in block 5
- ~93 pytest cases — must still pass

**Newton's first real value emerges in block 3.** Block 1 and 2 were
plumbing. After block 3, sir can actually *use* Newton to manage notes
with privacy guarantees and ask questions across them.

---

## 6. Starting checklist

Before Block 3 begins:

- [ ] `git status` clean, on `newton-main`, HEAD at `v0.2.0-block2`
- [ ] `uv run newton status` reports green (DB + 3 personas + 2 users + 3 tools + 2 providers)
- [ ] `uv run pytest tests/newton/ -v` → ~93 passed (block 1 + 2)
- [ ] `./scripts/newton/preflight.sh` → 9/9 ✓
- [ ] Docker Desktop running, or `qdrant-binary` ready
- [ ] At least 10 GB free disk (Qdrant data + BGE-M3 model files)
- [ ] BGE-M3 model can be downloaded (~2.2 GB)
- [ ] spaCy Korean model can be downloaded
- [ ] sir has 3–4 weeks of focused work available (block 3 is a big block)

---

Ready when sir is. Step 3.1 is the entry point.
