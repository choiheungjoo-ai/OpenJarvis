# Newton v4 — Roadmap Extensions: Supervisor, Credential Vault, Dev Gateway, Investment

> Master plan: `newton-v4-master.md`
> Tech stack: `newton-v4-tech-stack.md`
> Engines (Provider matrix): `newton-v4-engines.md`
> Block 2 (Tool + Approval + Provider Registry): `newton-v4-block-2.md`
> Block 4 (Proactive Engine): `newton-v4-block-4.md`
> Block 7 (Search/Analysis/OS/Translation/Autoresearch): `newton-v4-block-7.md`
>
> **Status:** DESIGN — not yet scheduled into a numbered block.
> **Purpose:** Capture four capabilities discussed but absent from the
> 11-block plan, and show how each rests on the existing foundation
> (Block 2 providers + approval, Block 3 memory, Block 4 proactive).

---

## 0. Why this document exists

The 11-block roadmap delivers **capabilities** (voice, vision, web tools,
calendar, smart home). What it does **not** make explicit is:

1. **A general-purpose Supervisor** — the brain that receives any request,
   decides which tool/provider/model to use, plans multi-step work, and
   escalates when it is out of its depth. Block 7's `research.loop` is the
   closest thing, but it is autoresearch-specific, not a general router.
2. **A Credential Vault** — encrypted storage for secrets (site logins,
   exchange API keys), so Newton can act on sir's behalf without ever
   holding plaintext passwords.
3. **A Dev Gateway** — Newton orchestrating its own development: a local
   coding LLM does the routine work, escalating to sir and then to Claude
   Code only when it gets stuck.
4. **An Investment module** — stock and crypto: ingest price history and
   news, train forecasting models locally, simulate, and (only after a
   stability bar is cleared, and only with sir's confirmation) trade.

These are **applications on a shared foundation**, not isolated features.
This document specifies the foundation once, then each application on top.

### Governing principles (carried from the whole project)

- **No hardcoding, ever.** Coefficients, thresholds, model names, windows,
  routing rules — all live in config. Models sit behind provider seams.
- **Plugin-everything.** Every LLM and every model is a swappable provider
  (the Block 2 `ProviderRegistry` pattern). Model choice is a config line,
  never a code change.
- **Local-first.** Default to local, free, private compute (Ollama, local
  models on the RTX 5090). Anything that costs money or leaves the machine
  requires sir's explicit confirmation, every time.
- **Stability *and* extensibility — hybrid, not either/or.** Where a
  decision pits the two against each other, prefer a stable simple core
  with a documented seam for the richer version, rather than choosing one
  outright. (Same discipline as Block 4: ship the simple scorer, leave a
  config-driven seam for the elaborate one.)
- **Approval for anything irreversible or costly.** Sending, posting,
  trading, spending, logging in — show the draft/plan, get sir's yes,
  then act. The Block 2 approval gate is the single mechanism.
- **Self-evolving by record.** Dev and investment both improve by keeping
  their own run history (what worked, what was rejected) and feeding it
  back — never by silent self-modification.

---

## 1. The shared foundation

Everything below rests on four pieces. Three exist; two are new.

```
┌─────────────────────────────────────────────────────────────┐
│                     sir (voice / text)                       │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  SUPERVISOR  (new)                                           │
│  understand request → classify → plan → route → escalate     │
│  local Ollama model + rule layer + result-checking           │
└───────┬─────────────────────────────────────────┬───────────┘
        ▼                                          ▼
┌───────────────────────┐              ┌──────────────────────┐
│ ProviderRegistry (B2) │              │  Approval Gate (B2)  │
│ capabilities ↔ models │              │  risk → confirm → log│
│ hot-swappable         │              │  irreversible/costly │
└───────┬───────────────┘              └──────────┬───────────┘
        ▼                                         ▼
┌───────────────────────┐              ┌──────────────────────┐
│  Credential Vault (new)│             │  Memory / Vault (B3) │
│  encrypted secrets     │             │  context, history,   │
│  passphrase-derived key│             │  decisions, records  │
└────────────────────────┘             └──────────────────────┘
```

### 1.1 Supervisor / Orchestrator (NEW)

The brain. Takes any request and decides **what to do with it**.

**Responsibilities**
- Understand the request (local LLM).
- Classify it to a capability or a plan of capabilities.
- Route to the right provider(s) — single tool, or a multi-step chain.
- Execute through the Block 2 ToolRegistry (so risk/approval/logging all
  still apply — the Supervisor never bypasses the safety circuit).
- Escalate when local capability is insufficient.

**Routing is hybrid — rules first, LLM second, results third.** A weak
local model overestimates itself, so we do not trust its self-assessment
alone:

1. **Rule layer (fast, deterministic).** Map obvious request shapes to
   capabilities. "run tests", "format", "weather" → local, settled. This
   is the Jenie `ROUTING_RULES` / `SupervisorAgent` pattern, reused.
   Lowest latency, no model call for the common cases.
2. **Local LLM (judgment for the ambiguous).** When rules don't settle it,
   the local supervisor model picks a capability / drafts a plan.
3. **Result check (ground truth).** For anything verifiable — code that
   must pass tests, a query that must return rows — success is judged by
   the **actual result**, not the model's confidence. Tests don't lie. A
   red test → escalate, regardless of how sure the local model was.

**The Supervisor is itself a provider-backed component.** The supervisor
model is config (`qwen3:8b` today, larger or different tomorrow). The
rule table is config. Nothing about "which model is the brain" is
hardcoded.

**Relationship to Block 7's `research.loop`.** `research.loop` is a
*specialized* agentic loop (overnight autoresearch). The Supervisor is the
*general* case. Natural path: build the Supervisor as the generalization,
and let `research.loop` become one capability it can invoke. Most cleanly
introduced **with or just after Block 7**, when many real providers first
exist to route between.

### 1.2 Credential Vault (NEW)

Encrypted storage so Newton can authenticate **without ever holding a
plaintext password**.

**Threat model.** The repo is a public OpenJarvis fork. A plaintext secret
committed by accident is world-readable. A secret in an LLM prompt or log
leaks. So: secrets are encrypted at rest, decrypted only at the instant of
use, never enter a prompt or log, and the decryption key is never on disk.

**Design — two-factor: approval + passphrase (sir's proposal).**

```
sir: "log into <site> and …"
   ↓
Newton: this needs a login. Approve?          ← 1) approval gate
   ↓
sir: "yes, <passphrase>"                       ← 2) spoken/typed passphrase
   ↓
Newton: derive key from passphrase
        → decrypt the stored secret in memory
        → inject into the (already-open) browser/session
        → wipe the plaintext from memory immediately
   ↓
Newton: logged in. (secret never on disk in plaintext,
        never in a prompt, never in a log)
```

**Key properties**
- Secret stored **encrypted** at rest (e.g. authenticated encryption;
  AES-GCM or libsodium secretbox). The encrypted blob is gitignored and
  kept outside the repo tree.
- **Decryption key is derived from the passphrase** (KDF — Argon2id /
  scrypt), so the key lives only in sir's memory, never on disk.
- Plaintext exists **only in memory, only during the action**, then wiped.
- **Never** placed in an LLM prompt, tool argument that gets logged, or any
  audit record. Isolated even inside Newton.
- Each use requires **approval + passphrase** — Newton cannot act alone.

**Two storage tiers (keep them separate).**
- **General personal info** (preferences, routines, schedule patterns) →
  the normal Block 3 vault. Not sensitive in this sense.
- **Sensitive credentials** (passwords, API keys, payment tokens) → the
  Credential Vault. Different security grade, different storage.

**Honest caveats (must be designed around, not ignored).**
- *Spoken passphrase can be overheard* (people nearby, recordings, smart
  speakers). Mitigations: rotate it; combine with a second factor (device,
  time-of-day); allow typing instead of speaking for the most sensitive
  secrets.
- *STT can mishear the passphrase* → decryption fails. Choose a passphrase
  STT transcribes reliably (a clear distinctive phrase, not short common
  words). (Newton already runs faster-whisper; same lesson as Jenie.)
- *CAPTCHA / bot-detection.* Newton does **not** solve CAPTCHAs or bypass
  bot detection. If one appears, it escalates to sir. Preferring
  already-logged-in sessions avoids most login-time CAPTCHAs entirely.

**Where it slots in.** Independent enough to build early, but its first
real consumer is web automation. Natural home: **just before / inside
Block 7** (web tools), or paired with Block 5 if voice-passphrase UX is
wanted sooner.

### 1.3 Approval Gate (EXISTS — Block 2)

Reused as-is for every irreversible or costly action. Three escalating
needs:

- **Free + reversible** → proceed (read a price, fetch news, run a sim).
- **Costs money or leaves the machine** → confirm first (call a paid API,
  send a request to a 3rd party). **Hard rule: any cost → ask sir; default
  to the free path.**
- **Irreversible** → show the draft/plan, get an explicit yes, then act
  (send email, place reservation, **execute a trade**).

### 1.4 Memory / Vault (EXISTS — Block 3)

Stores context, decision history, and — crucially for the self-evolving
goal — the **run records** that Dev and Investment learn from.

---

## 2. Application: Dev Gateway

Newton develops software — primarily itself — using a local coding LLM
first, escalating to sir and then to Claude Code only when stuck.

### 2.1 Roles

```
sir ──request──► SUPERVISOR ──► Dev Gateway
                                  │
                                  ├─ 1. Local coding LLM (default)
                                  │     routine edits, boilerplate,
                                  │     test runs, simple fixes
                                  │
                                  ├─ 2. sir consult (on block / decision)
                                  │     "local is stuck — want me to call
                                  │      Claude Code, or take a look?"
                                  │
                                  └─ 3. Claude Code (sir-approved)
                                        hard design, tricky debugging
```

- **Newton = gateway**: memory, safety, escalation, context injection.
- **Local coding LLM = first engine**: most of the routine work.
- **Claude Code = escalation engine**: invoked only on sir approval.
- **Claude (chat) = judgment consultant**: design review when summoned.

### 2.2 Escalation ladder (general principle, not just dev)

1. **Local LLM first** — private, free, fast.
2. **Stuck → consult sir** — "I can't crack this; escalate?"
3. **sir approves → Claude Code** — costs/leaves machine, so it is an
   approval-gated step, never automatic fallback.

**Why not auto-fallback to Claude Code?** Because calling an external,
paid, internet model is exactly the kind of action the approval gate
governs. Provider-level auto-fallback would silently bypass it. So:
providers *execute*; the gateway (with sir) *decides which provider*.

### 2.3 Providers

New capability `code.generate` (or `dev.complete`) in the registry:

```
capability: code.generate
  ├── LocalCoderProvider   ← Ollama + local coding model   (default)
  ├── ClaudeCodeProvider   ← Claude Code, headless invoke   (escalation)
  └── (future models)      ← drop in via config
```

- Local coding model is **config**, behind the seam. Candidates run well
  on a 32 GB RTX 5090 (e.g. a strong open coding model, 4-bit quantized).
  Exact pick is a config decision verified against current options at
  build time — not baked into the design.
- `ClaudeCodeProvider` wraps Claude Code's headless/print mode as a tool
  (`claude -p …`, structured output). Subject to approval + cost rules.
- Usage/cost telemetry (Block 2 `provider_usage`) records local-free vs
  Claude-paid — feeding the escalation decision.

### 2.4 Detecting "stuck" (the real tension)

The hard part is knowing when local has failed and escalation is due.
Signals, in order of reliability:

1. **Test failure** (ground truth) — local says "done", tests are red →
   not done. Most reliable; tests don't lie.
2. **Repeated failure** — N attempts without passing → escalate.
3. **Explicit low confidence / "I don't know"** from the local model —
   weakest signal (overconfidence), used only as a tiebreaker.

Prefer structured signals (a "DECISION NEEDED:" convention, or
structured output) over free-text parsing, so the gateway reliably knows
when to surface a choice to sir.

### 2.5 Self-evolution

Dev Gateway keeps a record (Block 3 / dedicated table) of tasks, which
engine handled them, pass/fail, and sir's escalation choices. Over time
the rule layer is tuned from this history — "tasks like X are reliably
local; tasks like Y need Claude Code." Evolution is **by record and
review**, never silent self-modification of the running system.

---

## 3. Application: Investment (stocks + crypto)

A sibling of the Dev module: the Supervisor routes "how does X look?" /
"run the sim" to investment providers. **Read and simulate freely; trade
only after a stability bar is cleared and only with sir's confirmation.**

> **Not financial advice.** This module is architecture only. It does not
> recommend what to buy or assert that any forecast is reliable. Price
> prediction is inherently hard; backtests do not equal live results.
> Every real trade is sir's decision, gated by approval.

### 3.1 Capabilities (all providers, all swappable)

```
capability: market.data        price/volume history (stocks: yfinance-class;
                               crypto: exchange APIs e.g. Binance/Upbit)
capability: news.ingest        fetch financial news / filings / feeds
capability: news.sentiment     score sentiment per item  (see 3.3)
capability: forecast.price     time-series model(s)       (see 3.2)
capability: sim.backtest       historical backtest + paper trading
capability: trade.execute      place real orders          (highest approval)
```

Each is a provider behind a seam. Swap a forecasting model, a news source,
or an exchange by editing config.

### 3.2 Forecasting models (`forecast.price`)

Built as a provider so the model is never hardcoded. As of mid-2026 the
field splits into tiers; the design supports an **ensemble** because
research consistently shows combined models beat any single one.

- **Deep-learning time series** (train locally on the 5090; this is the
  "self-learn the last few years" path):
  - **N-HiTS / N-BEATS** — fast, interpretable (trend/seasonality
    decomposition), strong on classical benchmarks; light to train.
  - **Temporal Fusion Transformer (TFT)** — multivariate (price + volume
    + indicators + **news sentiment** as exogenous inputs) with built-in
    variable-importance interpretability. A strong default for the
    news-aware model.
  - **PatchTST / TimesNet** — recent transformer time-series models;
    good with sentiment features as covariates.
  - **LSTM / GRU** — the classic baseline; the well-studied **FinBERT +
    LSTM** combination (news sentiment + price) is a sensible first build.
- **Time-series foundation models** (pretrained; zero-shot or fine-tuned,
  useful when local history is thin):
  - **Chronos-2** (AWS), **TimesFM** (Google), **Moirai-2** (Salesforce),
    **Lag-Llama** (probabilistic, gives uncertainty intervals).
- **Frameworks** that make training/comparing these easy on local GPU:
  **NeuralForecast** (Nixtla — TFT/N-HiTS/PatchTST), **Darts**
  (batteries-included, one interface for many models), **GluonTS**.

**Design stance:** start with a small ensemble — one news-aware deep model
(TFT or FinBERT-LSTM) + one foundation model (Chronos-2 / TimesFM for
zero-shot) — behind `forecast.price`, combined by a config-weighted
ensemble. Exact picks verified against current SOTA at build time.

**Evolution path (start with proven, grow into our own).** sir's intent is
not to invent a novel architecture on day one, but to start from validated
models and evolve toward a custom one — the same way Newton itself grew out
of OpenJarvis. Concretely:

1. **Train proven architectures** (TFT / N-HiTS / LSTM) on our data →
   baselines.
2. **Compare + augment** — see which fits our data; add features (news
   sentiment, indicators).
3. **Ensemble** — combine models (research shows this beats any single one).
4. **Custom design** — compose our own `nn.Module` in PyTorch (e.g.
   LSTM + attention + news-embedding wired our way). This is *combining
   proven building blocks our way*, not inventing a new paradigm.
5. **Evolve by record** — retrain on the growing simulation log; tune
   ensemble weights from realized performance (§3.5).

Each stage rests on the previous: the step-1 baseline is what tells us
whether a step-4 custom model is actually *better*.

### 3.2.1 Training infrastructure — PyTorch, isolated (Strategy D)

Training these models needs **PyTorch**, which Newton's core deliberately
does not carry (Strategy D = no in-process CUDA in the core). The
resolution is the **same pattern already proven for embeddings (TEI):
run the GPU work in a separate process / Docker container, reached over
HTTP — never imported into the core.**

```
Newton core  (PyTorch-free — Strategy D held)
   │  provider call: forecast.price / forecast.train
   ▼
Training+Inference service  (separate Docker: PyTorch + CUDA 12.8)   ← new
   - train  TFT / LSTM / N-BEATS / custom nn.Module
   - tune   on our data + news features
   - infer  → return forecast over HTTP
   ▼
Newton receives results → simulate, record, trigger retrain (§3.5)
```

This mirrors the TEI/Qdrant split exactly — and that split has proven
stable in production (both containers healthy for days at a time). The
training container is the *third* GPU service alongside TEI and Qdrant.

**Verified prerequisite (2026-06).** The RTX 5090 is Blackwell / sm_120.
This was historically a problem (stable PyTorch only went up to sm_90,
forcing nightly builds or source compilation). **That barrier is gone:**
a clean local check confirmed **stable PyTorch 2.11.0 + CUDA 12.8** runs
real GPU compute on the 5090 —

```
PyTorch: 2.11.0+cu128   CUDA: True (12.8)
Device: NVIDIA GeForce RTX 5090   Capability: (12, 0)
GPU matmul OK — real compute, not a CPU-fallback
```

So: install via the `cu128` index (`--index-url
https://download.pytorch.org/whl/cu128`), **stable channel, no nightly.**
The check ran in a throwaway venv and was removed; the core stayed
PyTorch-free. Standard training ops (TFT/LSTM/N-BEATS) need no custom CUDA
kernels, so the known sm_120 JIT-compile gap (missing `libnvptxcompiler.so`
for things like FlashAttention) does not affect this path. Re-verify the
PyTorch/CUDA versions at build time — the field moves.

### 3.3 News learning (`news.sentiment`) — the "learn the news" part

- **FinBERT** is the open, finance-tuned sentiment standard (pos/neg/neutral
  with confidence); runs locally, free. Ensembling FinBERT with
  general models (RoBERTa/DeBERTa) measurably improves accuracy.
- Reuse Newton's existing **NER (spaCy)** and **embeddings (BGE-M3)** to
  tag which ticker/event a news item concerns and to dedupe/cluster.
- A local LLM (Ollama) can do richer narrative sentiment where a
  classifier is too blunt — local and free, so no cost gate.
- Sentiment scores become **exogenous features** feeding `forecast.price`
  (the FinBERT-LSTM / TFT-with-news pattern).

**Honest caveats baked into the design:**
- *Staleness.* A sentiment model is a snapshot of its training era; what
  "rate hike" implied in 2022 differs in 2026. The module must track
  whether sentiment scores actually preceded price moves (a ground-truth
  check), not assume polarity = prediction.
- *Cost discipline.* Frontier paid models for sentiment are expensive at
  scale. **Default to free local (FinBERT / local LLM); any paid API for
  news or sentiment requires sir's confirmation.**
- News learning enriches the signal; it does **not** make prediction
  reliable. Unpriced/surprise news still breaks any model.

### 3.4 Staged rollout (sir's "simulate → stabilize → invest" plan)

```
Stage 1 — Data + Forecast + News        RISK: none (read-only)
   ingest history, train models on the last few years, score news,
   produce forecasts. "How does X look?" → forecast + sentiment + why.

Stage 2 — Paper trading                  RISK: none (virtual money)
   models trade a virtual portfolio in real time; performance recorded.
   This is the "watch it for a while" stage. No real money at risk.

Stage 3 — Stabilization judgment         RISK: none (evaluation)
   evaluate against a PRE-DEFINED bar (config): e.g. paper-traded for
   N months, return / max-drawdown / Sharpe thresholds. Prevents
   "invest on a hunch." Until the bar is cleared, no real trading.

Stage 4 — Small real trades              RISK: real money — ALWAYS gated
   only after Stage 3 passes. Every order: "signal says buy X, amount Y —
   confirm?" → sir approves → trade.execute (Credential Vault holds the
   exchange API key). Start small. Newton never trades autonomously.
```

- **Stages 1–2 are zero-risk** and can begin relatively early (no
  dependency on web automation or vision).
- **Stage 3's bar is config**, defined in advance — the discipline that
  keeps Stage 4 honest.
- **Stage 4 is the most heavily gated action in the whole system** — real
  money, irreversible, credentialed. Approval gate at maximum.
- **Crypto note:** higher volatility (harder prediction) and exchange-key
  security matter more; same staging, extra caution.

### 3.5 Self-evolution

Every forecast, paper trade, and (later) real trade is recorded with its
outcome. Models are periodically retrained on the growing record and
re-evaluated against the Stage-3 bar; ensemble weights are tuned from
realized performance. The module **evolves from its own track record** —
exactly the "record → simulate → evolve" loop sir described, and the
mirror of the Dev Gateway's self-tuning.

---

## 4. Sequencing — when to build what

Nothing here jumps the queue ahead of finishing Block 4 and the core
capability blocks. Realistic order, by dependency:

| Piece | Depends on | Earliest sensible point | Risk |
|---|---|---|---|
| **Credential Vault** | crypto libs only (independent) | before/with Block 7; or with Block 5 for voice-passphrase | none until used |
| **Supervisor** | many real providers to route (Block 7) | with/just after Block 7; generalize `research.loop` | none |
| **Training service (Docker)** | PyTorch+CUDA container (verified) | with Investment Stage 1; the 3rd GPU service after TEI/Qdrant | none |
| **Investment Stage 1–2** | `market.data`, `forecast.price`, training service | early — zero risk | none |
| **Dev Gateway** | Supervisor + ToolRegistry + dev tools | after Supervisor (post-Block 7) | low |
| **Web automation / login** | Credential Vault + Block 7 browser tools | post-Block 7 | medium (CAPTCHA) |
| **Investment Stage 3–4** | Stages 1–2 stable + Credential Vault | latest; real money | high — max approval |

**Difficulty-ordered integration note (applies across applications):**
OAuth-clean services (Gmail, Google Calendar) are *easy and early* — token
auth, no CAPTCHA, official API. Screen-scraped logins (Naver reservation,
KakaoTalk) are *hard and late* — no clean API, CAPTCHA, account-risk; some
(personal-message automation) are blocked by policy regardless of OS and
are better served by official-API channels (Telegram/Slack/Discord) than
by scraping.

### 4.1 What to do now

1. **Keep this document** as the north star so the blocks already being
   built stay aligned to it (Block 2 approval, Block 4 proactive, Block 7
   providers all feed these applications).
2. **Finish Block 4** (proactive engine) — it powers investment briefings
   ("pre-market summary", "drawdown alert") and dev nudges via the same
   anticipation machinery.
3. When Block 7 lands its first real providers, **introduce the Supervisor
   there** (generalizing `research.loop`) and **the Credential Vault**
   alongside it.
4. Begin **Investment Stage 1–2** as soon as `forecast.price` /
   `news.sentiment` providers exist — it is zero-risk and produces the
   record that later stages evolve from.

---

## 5. Open questions to resolve at build time

These are deliberately left to the moment of implementation, when current
options can be re-checked (the field moves fast):

1. **Local coding model** — which open coding model is SOTA-for-32GB at
   build time. Config, not design.
2. **Local supervisor model** — the brain's model. Likely the current main
   Ollama model; revisit as larger local models become feasible.
3. **Forecasting ensemble composition** — which deep model + which
   foundation model, and the ensemble weighting. Verify against current
   benchmarks (NeuralForecast / Darts make this an experiment, not a
   commitment).
4. **Sentiment stack** — FinBERT alone vs FinBERT+RoBERTa/DeBERTa ensemble
   vs local LLM; measured by whether scores actually precede price moves.
5. **Credential Vault crypto** — exact KDF + cipher (Argon2id + AES-GCM /
   libsodium), and whether to lean on an OS keyring where available
   (Linux Secret Service; macOS Keychain if/when ported).
6. **Stage-3 stability bar** — the concrete numbers (months, return,
   drawdown, Sharpe). Config, defined before Stage 4 is enabled.

**Resolved (2026-06):** the training-infra prerequisite — does PyTorch run
on the 5090 (Blackwell/sm_120)? — is *verified*: stable PyTorch 2.11.0 +
CUDA 12.8 (`cu128` wheel, no nightly) runs real GPU compute on the 5090.
See §3.2.1. Still re-check the exact versions at build time, but the path
is no longer in doubt.

---

*End of roadmap-extensions design. This is a living document; numbers,
model names, and library choices are expected to be re-verified at the
moment each piece is built.*
