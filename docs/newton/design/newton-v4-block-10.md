# Newton v4 — Block 10: LoRA per Persona (Conditional)

> Master plan: `newton-v4-master.md`
> Tech stack: `newton-v4-tech-stack.md`
> Voice (STT LoRA section): `newton-v4-voice.md` §5
> Terminology: `TERMINOLOGY.md`
> Prerequisite: Block 9 complete (`v0.9.0-block9`, `docs/newton/block-9-summary.md`)
>
> **Goal:** When sir's data has grown enough, fine-tune adapters to make
> JARVIS / Friday / Butler sound more like *Newton's particular usage*,
> and improve STT on sir's vocabulary. **This block is conditional and
> may be skipped entirely.**

---

## 0. Block 10 — overall goals

This is the *adaptation* block. By now Newton has accumulated:

- Conversation summaries in `_auto/conversations/` (block 3)
- STT corpus from sir's post-wake-word audio (block 5)
- Gesture activations + tool usage patterns (blocks 7–8)
- Inbox + calendar history (block 9)

Block 10 turns that accumulation into model improvements:

1. **Per-persona LLM LoRA** — fine-tune Qwen 2.5 32B with persona-specific
   conversation samples so JARVIS sounds even more like *Newton's JARVIS*
2. **Whisper STT LoRA** — fine-tune Whisper Large v3 on sir's accumulated
   STT corpus so technical / Korean vocabulary recognition improves
3. **Ollama hot-swap orchestration** — load / unload LoRA adapters at
   runtime per active persona

### When this block runs — explicit triggers

Block 10 is **CONDITIONAL**. Skip directly to Block 11 unless one of:

| Trigger | Threshold |
|---------|-----------|
| Per-persona conversation count | ≥ 500 summarized conversations for that persona |
| STT corpus duration | ≥ 1 hour of sir-only post-wake-word audio |
| Sir requests explicitly | "JARVIS, can you sound more like yourself?" |

If neither trigger applies → skip to Block 11. Newton works fine without
fine-tuning; this is *polish*.

### Locked decisions (entering Block 10)

| Item | Decision | Source |
|------|----------|--------|
| **LLM LoRA backend** | Unsloth (Apache 2.0) | tech-stack.md |
| **STT LoRA backend** | faster-whisper compatible LoRA tooling | voice.md §5 |
| **Adapter hot-swap** | Ollama LoRA adapter swap (no full reload) | tech-stack.md |
| **Per-persona scope** | each persona gets its own LoRA; Butler defaults to no LoRA | this block |
| **Training data filter** | only `status='canonical'` notes; never `_guest_quarantine/` | privacy |
| **STT LoRA rank** | 16 (proven good baseline for low-resource fine-tune) | voice.md §5 |
| **STT LoRA epochs** | 1–3, linear decay LR | voice.md §5 |
| **LLM LoRA evaluation** | manual sir A/B test before activation | this block |
| **Rollback** | every adapter atomically swappable; previous version retained | this block |
| **Conditional skip** | if neither trigger applies, this block is *empty* — just tag and move on | this block |

### Completion criteria (block as a whole)

```bash
# Check triggers
$ uv run newton lora status
JARVIS conversations: 612    >= 500 ✓ trigger met
Friday conversations: 184    < 500 ✗
Butler conversations: n/a    (no fine-tune planned)
STT corpus: 1h 47m           >= 1h ✓ trigger met

# Train JARVIS LoRA (only if trigger met)
$ uv run newton lora train jarvis --epochs 2
[runs 2-6 hours on RTX 5090]
[validation: A/B preview ready]

$ uv run newton lora preview jarvis
[3 sample prompts answered by base model vs LoRA-tuned]
[sir picks "tuned is better" / "no preference" / "base is better"]

$ uv run newton lora activate jarvis
LoRA active for persona jarvis (version 1)

# STT LoRA
$ uv run newton stt train-lora --target-lang ko --epochs 2
[runs 2-4 hours on RTX 5090]
[WER on validation set drops from 11.2% to 7.8%]

$ uv run newton stt lora activate
STT LoRA active

# Roll back if needed
$ uv run newton lora rollback jarvis
LoRA deactivated; base model in use again

# Tests
$ uv run pytest tests/newton/ -v
# Blocks 1-9: ~708 + Block 10: ~30 = ~738 passed
```

If both triggers are skipped, completion criteria reduce to:
"Block 10 skipped intentionally; tag and proceed."

---

## 1. Block 10 — 7 steps

Each step: one focused change, one verification, one commit.
`ruff check` + `ruff format` clean before commit.

Estimated total: **5–10 days at sir's pace** *when triggered*. If
skipped: **half a day** (just the trigger check + tag).

Block 10 is much shorter than block 8 or 9 because it leverages
existing Unsloth + Whisper LoRA tooling — Newton glue code is thin.

---

### Step 10.1 — Trigger assessment + skip-or-proceed decision (half-day)

**Goal:** Look at the data sir has accumulated. Decide whether to do
Block 10 at all.

**Outputs:**

- `newton/lora/triggers.py` — checks conversation counts + STT corpus duration
- `newton/cli.py` — `newton lora status`
- Decision document: `docs/newton/block-10-decision.md` (records the answer)

**Trigger logic:**

```python
def assess_triggers() -> dict:
    return {
        "jarvis_conversations":    count_notes("_auto/conversations/", persona="jarvis"),
        "friday_conversations":    count_notes("_auto/conversations/", persona="friday"),
        "butler_conversations":    None,  # never fine-tune butler
        "stt_corpus_hours":        sum_audio_duration("data/voices/sir/stt_corpus/"),
        "triggers_met": {
            "jarvis_llm":  conversations["jarvis"] >= 500,
            "friday_llm":  conversations["friday"] >= 500,
            "stt_ko":      stt_corpus_hours >= 1.0,
        }
    }
```

**Decision flow:**

```bash
uv run newton lora status

# Output e.g.:
JARVIS conversations: 612  >= 500 ✓  → eligible
Friday conversations: 184  < 500     → not eligible
STT corpus (ko):     1h 47m  >= 1h ✓  → eligible

Block 10 plan:
  - JARVIS LLM LoRA: PROCEED (step 10.2-10.4)
  - Friday LLM LoRA: SKIP (insufficient data)
  - Butler LLM LoRA: SKIP (by design)
  - STT LoRA (ko):   PROCEED (step 10.5-10.6)
```

If *none* are eligible: skip directly to Step 10.7 (tag empty block).

**Verification:**

```bash
uv run newton lora status
# decision rendered; written to docs/newton/block-10-decision.md
```

**Commit:** `docs(block-10): trigger assessment + decision`

---

### Step 10.2 — LLM LoRA training data preparation (1 day)

**Goal:** Build the training dataset from conversation summaries for
each eligible persona.

**Outputs:**

- `newton/lora/dataset.py` — vault → JSONL conversion
- Filters: `status='canonical'` only; `read_personas` includes target persona
- Format: instruction-tuning compatible (`{instruction, input, output}`)
- `data/lora/jarvis/train.jsonl` (gitignored)
- `tests/newton/lora/test_dataset.py`

**Per-conversation extraction:**

```
read note: data/vault/_auto/conversations/<id>.md
    ↓
extract messages (sir's question + persona's response)
    ↓
filter: only conversations >= 3 messages (avoid noise)
filter: only with positive proactive_notifications acceptance OR no notification
    ↓
emit JSONL rows:
{
  "instruction": "<sir's question>",
  "input": "<system_prompt + recent context>",
  "output": "<persona's response>"
}
```

**Train/val split:** 90/10.

**Privacy:** never include guest_quarantine, never include shared notes
unless persona is in read_personas, never include other users' notes.

**Verification:**

```bash
uv run newton lora dataset build jarvis
# data/lora/jarvis/train.jsonl: 551 rows
# data/lora/jarvis/val.jsonl: 61 rows

uv run pytest tests/newton/lora/test_dataset.py -v
```

**Commit:** `feat(lora): training dataset builder from vault`

---

### Step 10.3 — Unsloth LLM LoRA training (1–2 days, plus runtime)

**Goal:** Train a LoRA adapter for each eligible persona.

**Outputs:**

- `newton/lora/train_llm.py` — Unsloth wrapper
- `scripts/newton/train-lora-llm.sh` — entry point
- `newton/cli.py` — `newton lora train <persona> [--epochs N] [--rank N]`
- `data/lora/<persona>/adapter-v<n>/` (the trained adapter files)
- `tests/newton/lora/test_train_llm.py`

**Dependencies:**

```bash
uv add unsloth bitsandbytes
```

**Training config:**

```yaml
lora_llm:
  base_model: qwen2.5-32b
  rank: 16
  alpha: 32
  dropout: 0.05
  learning_rate: 2e-4
  epochs: 2
  batch_size: 1                  # 32B is memory-heavy
  gradient_accumulation: 16
  warmup_steps: 100
```

**GPU usage:** Qwen 2.5 32B + LoRA training ≈ 24 GB VRAM. Within RTX
5090's 32 GB. No model swap during training (other Newton subsystems
should be paused or run on CPU).

**Training runtime:** ~2–6 hours per persona depending on dataset size.

**Verification:**

```bash
uv run newton lora train jarvis --epochs 2
# trains; logs to data/lora/jarvis/training.log
# adapter saved: data/lora/jarvis/adapter-v1/
```

**Risk:** RTX 5090 + Unsloth + Qwen 2.5 32B may have compatibility
issues at the cutting edge. **Mitigation:** falls back to QLoRA on
Qwen 2.5 14B; documented in step 10.3 notes.

**Commit:** `feat(lora): Unsloth LLM LoRA training pipeline`

---

### Step 10.4 — LLM LoRA A/B preview + activation (1 day)

**Goal:** Before activating, let sir compare base vs LoRA-tuned outputs
on a small set of prompts. Sir chooses.

**Outputs:**

- `newton/lora/preview.py` — A/B test runner
- `newton/cli.py` — `newton lora preview <persona>`, `newton lora activate <persona>`, `newton lora rollback <persona>`
- Ollama integration: load adapter, set as active for persona
- `tests/newton/lora/test_activation.py`

**Preview flow:**

```bash
uv run newton lora preview jarvis

Prompt 1: "Sir, I need to draft an email."
  [base model]:    "Of course, sir. What's the subject?"
  [LoRA tuned]:    "Of course, sir. To whom and about what?"

Prompt 2: "What's on my calendar?"
  [base model]:    "You have 3 events tomorrow..."
  [LoRA tuned]:    "Tomorrow: ML stand-up at 09:00, lunch with..."

(3 more prompts...)

sir, which sounds more like the JARVIS you want?
  [a] base       [b] LoRA       [c] no preference
> b

LoRA activated for persona jarvis (version 1).
Previous: base. Rollback: newton lora rollback jarvis
```

**Activation:**

`personas.lora_adapter_path` field (already in block 1 schema) gets set.
At LLM-call time, the persona engine adds the LoRA adapter to the
Ollama request.

**Rollback:** atomic. Set `personas.lora_adapter_path = NULL`.

**Verification:**

```bash
uv run newton lora preview jarvis
# 5 A/B comparisons rendered

uv run newton lora activate jarvis
sqlite3 data/newton.db "SELECT persona_id, lora_adapter_path FROM personas WHERE persona_id='jarvis'"
# jarvis | data/lora/jarvis/adapter-v1/
```

**Commit:** `feat(lora): A/B preview + activation/rollback`

---

### Step 10.5 — Whisper STT LoRA training data + training (1.5 days)

**Goal:** Fine-tune Whisper Large v3 on sir's STT corpus.

**Outputs:**

- `newton/lora/train_stt.py` — Whisper LoRA training wrapper
- `scripts/newton/train-lora-stt.sh`
- `newton/cli.py` — `newton stt train-lora --target-lang ko [--epochs N]`
- `data/lora/stt/adapter-v<n>/`
- `tests/newton/lora/test_train_stt.py`

**Dataset:**

```
data/voices/sir/stt_corpus/*.{wav,txt}
    ↓
filter: any (wav, txt) pair where confidence > 0.85
    ↓
audio + transcription pairs ready for whisper LoRA
```

**Training config (from voice.md §5):**

```yaml
lora_stt:
  base_model: whisper-large-v3
  rank: 16
  learning_rate: pretrain_lr / 40      # ≈1.25e-5
  schedule: linear_decay_to_zero
  epochs: 1-3
  language: ko
```

**Expected effect:** WER 23–36 % reduction on sir's vocabulary
(Nepali study baseline; Korean expected similar).

**Verification:**

```bash
uv run newton stt train-lora --target-lang ko --epochs 2
# trains for 2-4 hours
# val WER: 11.2% → 7.8% (sample)
# adapter saved
```

**Commit:** `feat(lora): Whisper STT LoRA training`

---

### Step 10.6 — STT LoRA activation + hot-swap (1 day)

**Goal:** Hot-swap STT model with LoRA adapter; rollback support.

**Outputs:**

- `newton/lora/stt_swap.py` — atomic Whisper model swap
- `newton/cli.py` — `newton stt lora activate/rollback`
- Block 5 STT facade reads active adapter on every call
- `tests/newton/lora/test_stt_swap.py`

**Verification:**

```bash
uv run newton stt lora activate
# next STT call uses LoRA-tuned Whisper

# test against held-out audio
uv run newton stt /tmp/test-utterance.wav
# improved transcription

uv run newton stt lora rollback
# back to base Whisper
```

**Commit:** `feat(lora): STT LoRA hot-swap with rollback`

---

### Step 10.7 — Block 10 summary + tag (half-day)

**Goal:** Lock the block. Both for the *trained* case and the *skipped*
case.

**Outputs:**

- `docs/newton/block-10-summary.md`
  - if trained: list adapters, A/B results, WER improvement
  - if skipped: explicit "Block 10 intentionally skipped: triggers not met"
- `README.md` — Block 10 marked complete (or skipped)
- Git tag: `v0.10.0-block10`

**Block 11 entry conditions (provisional):**

- `newton lora status` runs (decision recorded)
- If trained: at least one adapter active or available for swap
- If skipped: this is fine and explicitly documented
- All pytest cases pass
- Preflight 9/9 still ✓
- OpenJarvis: still 0 files modified

**Commit + tag:** `chore: block 10 complete` (or `chore: block 10 skipped`)

---

## 2. Deliberately not in Block 10

- ❌ **Full base-model fine-tune** — LoRA only; never modify base weights
- ❌ **Multi-persona shared LoRA** — each persona has its own adapter
- ❌ **Cross-user LoRA** — sir's data only; never blend with gf's
- ❌ **Image / Vision LLM fine-tune** — out of scope
- ❌ **Continuous online learning** — adapters trained as snapshots, not streaming
- ❌ **Federated LoRA across multiple Newton instances** — out of scope; Newton is single-machine

---

## 3. Risk matrix

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Triggers never met → block never runs | Low | Acceptable; Newton works without LoRA |
| Fine-tune overfits to recent style → JARVIS sounds odd | Med | A/B preview + sir chooses; rollback available |
| Training crashes mid-run | Med | Checkpointing; resume from last good checkpoint |
| VRAM exhaustion during 32B training | High | Other Newton subsystems paused; fallback to 14B QLoRA |
| LoRA adapter corrupts persona behavior | Med | Atomic rollback to base; A/B catches before activation |
| STT LoRA degrades on out-of-domain audio | Low | Held-out val set checks generalization; rollback if WER regresses |
| Vault contains sensitive data unsuitable for training | High | `status='canonical'` filter; ACL filter; sir can manually exclude tags |
| Adapter file disk space | Low | Adapters are ~100MB each; manageable |
| Unsloth / Qwen compatibility on RTX 5090 | Med | Smoke test before full run; documented fallback to 14B base |
| 5–10 day estimate too tight | Med | Re-estimate after step 10.3 if training runtime exceeds 6 h |

---

## 4. After Block 10 — opening message for the next chat

```markdown
# Newton v4 — Block 11 start (UI + 3D Brain + HUD + Multi-Client)

## Context
- Newton: multi-persona AI OS, OpenJarvis fork
- Environment: RTX 5090 + WSL2 Ubuntu + systemd
- Location: ~/newton-v4/

## Design docs
[newton-v4-master.md]
[newton-v4-tech-stack.md]
[newton-v4-gestures.md]   # 3D Brain gestures section
[newton-v4-block-10.md]   # complete or skipped
[newton-v4-block-11.md]   # this block
[TERMINOLOGY.md]

## Blocks 1–10 result
- v0.10.0-block10: LoRA per persona (conditional)
  - either: JARVIS / Friday / STT adapters trained and active
  - or: block intentionally skipped (triggers not met)

## Next
Block 11 step 11.1 — OpenJarvis UI fork.
```

---

## 5. Honest reality check

**Time estimate:** **5–10 days at sir's pace** *if triggers met*.
**Half a day if skipped.**

**Riskiest steps (if running):**

- **Step 10.3** (training) — first time we touch model weights at all.
  Lots can go wrong.
- **Step 10.4** (A/B preview) — sir's subjective judgment is the
  acceptance test

**Simplest steps:**

- 10.1 (trigger check), 10.7 (tag)

**Most important step:**

- **Step 10.4** (A/B preview + rollback). LoRA can make things *worse*
  not just better. The safety net here is non-negotiable.

**Behavioural shift:**

After Block 10 *if trained*: JARVIS speaks slightly more like the JARVIS
sir has been shaping for months. STT misses fewer technical terms.
Subtle polish, not revolutionary.

After Block 10 *if skipped*: nothing changes. Block 11 proceeds normally.

**Assets carried over:**

- `personas.lora_adapter_path` (block 1 schema) — finally populated
- Block 2 ProviderRegistry pattern — could host LoRA adapters as providers in future
- Vault conversations (block 3) — training data
- STT corpus (block 5) — training data
- ~708 pytest cases must still pass

---

## 6. Starting checklist

Before Block 10 begins:

- [ ] Block 9 tagged `v0.9.0-block9`, `newton status` green
- [ ] Pytest ~708 passing
- [ ] `newton lora status` ran; decision recorded
- [ ] If proceeding:
  - [ ] At least 24 GB free VRAM during training windows (other models unloaded)
  - [ ] At least 20 GB free disk (training artifacts + adapters)
  - [ ] Unsloth installable on this Python + CUDA
  - [ ] Plan a 2–6 hour quiet window for each training run

---

Ready when sir is. Step 10.1 is the entry point — it may also be the
exit point if triggers aren't met.
