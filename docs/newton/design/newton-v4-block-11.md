# Newton v4 — Block 11: UI + 3D Brain + HUD + Multi-Client

> Master plan: `newton-v4-master.md`
> Tech stack: `newton-v4-tech-stack.md`
> Gesture details (3D Brain gestures): `newton-v4-gestures.md`
> Terminology: `TERMINOLOGY.md`
> Prerequisite: Block 10 complete or skipped (`v0.10.0-block10`, `docs/newton/block-10-summary.md`)
>
> **Goal:** The final block. Newton gets its face — a polished UI with
> persona switching, a 3D brain visualization sir can manipulate with
> gestures, a heads-up overlay always visible, and mobile clients.
> Movie-JARVIS visual aesthetic, locally rendered.

---

## 0. Block 11 — overall goals

Four UI surfaces ship in this block:

1. **Main UI** (OpenJarvis fork extension) — Tauri desktop app with
   persona switching, chat / vault / proactive / autoresearch tabs.
2. **3D Brain visualization** — R3F (React Three Fiber) scene showing
   per-persona memory as a 3D structure; gesture-manipulable (rotate /
   zoom / select node).
3. **HUD** — separate floating overlay window (Tauri secondary window)
   showing system status, current persona, last notification, gesture
   mode indicator. Movie-style elegance.
4. **Multi-client** — web, mobile (iOS + Android via Tauri Mobile or
   React Native), all thin clients talking to the home machine's
   Newton backend.

3D Brain gestures (brain_rotate, brain_zoom, node_grab) deferred from
Block 8 land here because the Brain itself ships in this block.

### Locked decisions (entering Block 11)

| Item | Decision | Source |
|------|----------|--------|
| **Desktop framework** | Tauri (already OpenJarvis baseline) | tech-stack.md |
| **Web framework** | React (OpenJarvis baseline) | tech-stack.md |
| **3D library** | React Three Fiber + drei | tech-stack.md |
| **HUD window** | Tauri secondary window, always-on-top, transparent | this block |
| **Mobile** | Tauri Mobile (Apache 2.0) — single React codebase for desktop + iOS + Android | tech-stack.md |
| **Brain data source** | Qdrant vault index → 3D layout via UMAP / t-SNE projection | this block |
| **Multi-client transport** | HTTP + Server-Sent Events to Newton FastAPI backend | OpenJarvis baseline |
| **Client auth** | local-network only by default; LAN-bound | privacy |
| **HUD priority levels** | info (visual only) / warning (visual + sound) / urgent (visual + sound + TTS) | jarvis-gap.md §3.8 |
| **HUD opacity** | 80% default, sir-configurable | jarvis-gap.md §3.8 |
| **Mobile feature parity** | core voice + read; persona switch; calendar; vault search. Full mobile = post-v1.0 | this block |
| **Block 1 invariants preserved** | OpenJarvis files still untouched | block 1 |

### Completion criteria (block as a whole)

```bash
# Desktop UI up
$ uv run newton ui start
Tauri desktop running on http://localhost:1420
Tauri HUD running on http://localhost:1421
3D Brain available at top-right corner button

# HUD visible
[floating overlay at top-right]
  ┌────────────────────────────┐
  │ JARVIS  · 09:42  · 5G+5    │
  │ ⬢ proactive: smart         │
  │ ✋ gesture: auto (armed)   │
  │ CPU 18%  GPU 12%  battery 78%│
  └────────────────────────────┘

# 3D Brain
[click brain button or say "JARVIS, show me your brain"]
[R3F scene opens]
[sir uses pinch gesture → zoom]
[sir uses palm-rotate → orbit]
[sir points at a node → JARVIS describes that memory cluster]

# Persona switcher
[click avatar in top-left]
[3 personas shown: Butler / JARVIS / Friday]
[click JARVIS → main chat now in JARVIS persona]

# Mobile client
[install Newton Mobile (Tauri Mobile build) on sir's iPhone]
[mobile connects to home Newton via LAN]
[voice + read + calendar + vault search works]
[sir's phone is now a thin client to home Newton]

# Tests
$ uv run pytest tests/newton/ -v
# Blocks 1-10: ~738 + Block 11: ~60 = ~798 passed (mostly UI integration tests are out-of-scope for pytest)
```

After Block 11, Newton is **v1.0**. Sir's personal AI operating system
is complete: voice, face, gesture, vault, proactive, search, comms,
home, and now a movie-JARVIS visual surface.

---

## 1. Block 11 — 13 steps

Each step: one focused change, one verification, one commit.
`ruff check` + `ruff format` clean before commit.

Estimated total: **20–30 days at sir's pace (4–6 weeks).** Final block.
Heavy on frontend work which is sir's slowest area; budgeted accordingly.

---

### Step 11.1 — OpenJarvis UI fork audit (half-day)

**Goal:** Inspect OpenJarvis's existing React + Tauri UI. Identify what
Newton can use directly and what needs replacement.

**Outputs:**

- `docs/newton/block-11-ui-audit.md` — inventory of OpenJarvis UI
  components + Newton needs

This is the *no-code* opening step. Pure investigation. **Newton never
modifies OpenJarvis files** (block 1 invariant); Newton extends.

**Audit checklist:**

- What chat UI does OpenJarvis ship?
- What component library (shadcn? custom?)
- What state management (Zustand? Redux?)
- What's the build pipeline (Vite? Next.js?)
- Tauri config, IPC patterns
- What's missing for Newton: persona switching, vault browser, proactive
  inbox, autoresearch dashboard, 3D Brain, HUD

**Output decision memo:**

```
- Keep OpenJarvis: base layout, chat component, Tauri shell, build setup
- Newton extends in new src directory: newton-ui/
- Components Newton adds: persona switcher, vault tab, proactive tab,
  autoresearch tab, settings tab, 3D Brain view, HUD secondary window
- Theme: extend OpenJarvis colors with Newton persona palette
```

**Verification:**

- ✅ docs/newton/block-11-ui-audit.md exists
- ✅ Next steps reference it as ground truth

**Commit:** `docs(block-11): UI audit + extension plan`

---

### Step 11.2 — newton-ui scaffold (1 day)

**Goal:** Set up `newton-ui/` directory under the repo root with React
+ Tauri integration that *coexists* with OpenJarvis UI.

**Outputs:**

- `newton-ui/` — new directory (not in OpenJarvis tree)
- `newton-ui/package.json`, `vite.config.ts`, etc.
- `newton-ui/src/App.tsx` — minimal "Hello Newton" entry
- Tauri config to launch both OpenJarvis UI (existing) AND newton-ui (new) on `newton ui start`
- `tests/newton-ui/` — Vitest setup

**Verification:**

```bash
cd newton-ui
npm install
npm run dev
# newton-ui dev server on port 5173; renders hello
```

**Commit:** `feat(ui): newton-ui scaffold alongside OpenJarvis UI`

---

### Step 11.3 — Persona switcher + chat extension (2 days)

**Goal:** Top-left avatar shows current persona. Click → switch.
Chat tab uses the active persona's color and prompt.

**Outputs:**

- `newton-ui/src/components/PersonaSwitcher.tsx`
- `newton-ui/src/components/ChatTab.tsx` — extends OpenJarvis chat with persona awareness
- API endpoints (FastAPI side): `GET /api/personas`, `POST /api/sessions/start`, `GET /api/sessions/active`
- `tests/newton/api/test_personas_endpoint.py`

**Behaviour:**

```
top-left avatar: shows current persona color circle + name
click → dropdown of 3 personas with color swatches
select JARVIS → POST /api/sessions/start { persona: 'jarvis' }
chat input area now styled with #185FA5 accent
system prompt rendered with sir's display_name substituted
```

**Verification:**

```bash
# UI test (manual)
# - persona switcher visible
# - clicking changes active session
# - chat reflects active persona
```

**Commit:** `feat(ui): persona switcher + chat extension`

---

### Step 11.4 — Vault browser tab (1.5 days)

**Goal:** Browse + search vault from the UI. ACL-aware (only see notes
you have access to).

**Outputs:**

- `newton-ui/src/tabs/VaultTab.tsx`
- API endpoints: `GET /api/vault/browse?path=...`, `GET /api/vault/search?q=...`,
  `GET /api/vault/note/{path}` (all ACL-filtered server-side using
  block 3 search)
- Markdown rendering for note bodies
- `tests/newton/api/test_vault_endpoint.py`

**ACL-filtered server-side (block 3 search):**

```
client request: GET /api/vault/search?q=newton
    ↓
server reads session.user_id, session.persona_id
    ↓
vault.search(q, user_id, persona_id) ← block 3 search, ACL-filtered
    ↓
return only allowed results
```

**Verification:**

- Vault tab shows tree + search box
- Search returns only ACL-permitted notes
- Click note → markdown rendered

**Commit:** `feat(ui): vault browser tab with ACL-filtered search`

---

### Step 11.5 — Proactive inbox tab (1 day)

**Goal:** UI list of recent proactive notifications. React buttons to
accept / reject / ignore.

**Outputs:**

- `newton-ui/src/tabs/ProactiveTab.tsx`
- API: `GET /api/proactive/notifications`, `POST /api/proactive/react/{id}`
- Real-time updates via Server-Sent Events (SSE)
- `tests/newton/api/test_proactive_endpoint.py`

**Behaviour:**

```
new notification arrives via SSE
    ↓
appears at top of list with persona color
    ↓
sir clicks ✓ → POST /api/proactive/react/<id> with action=accepted
              → block 4 learning records "accepted"
sir clicks ✗ → reaction=rejected
sir does nothing → after 5 min auto-recorded as ignored
```

**Verification:**

- Notification list shows recent
- Buttons fire correct API calls
- New notifications appear without refresh

**Commit:** `feat(ui): proactive inbox with reactions`

---

### Step 11.6 — HUD overlay window (2 days)

**Goal:** Always-on-top, semi-transparent floating window. Movie-JARVIS
elegance.

**Outputs:**

- `newton-ui/src/hud/HudApp.tsx`
- Tauri secondary window config: borderless, transparent, always-on-top,
  draggable, position default top-right
- HUD components:
  - clock + persona avatar
  - proactive mode indicator
  - gesture mode indicator
  - system mini-bars (CPU / GPU / memory)
  - next calendar event (block 9)
  - notification queue counter
  - audio level meter (when STT capturing)
- API: SSE feed of all signals → HUD subscribes to filtered set
- `newton/cli.py` — `newton hud show/hide/move`

**Notification priority levels (jarvis-gap.md §3.8):**

```
info     → visual only (small text in HUD)
warning  → visual + soft chime
urgent   → visual + sound + TTS (the persona speaks)
```

**Floating cards for transient notifications:**

```
new urgent → card slides in from right edge, 5s display, fade out
sir can drag to dismiss earlier
```

**Verification:**

```bash
uv run newton hud show
# overlay appears top-right
uv run newton hud move bottom-left
# overlay relocates
```

**Commit:** `feat(ui): HUD overlay window with priority levels`

---

### Step 11.7 — 3D Brain scene foundation (2.5 days)

**Goal:** R3F scene that visualizes persona memory in 3D space.

**Outputs:**

- `newton-ui/src/brain/BrainScene.tsx` — R3F scene
- `newton/api/brain.py` — endpoint that returns 3D-projected memory clusters
- Projection: UMAP from BGE-M3 embeddings → (x, y, z) coordinates
- Clustering: HDBSCAN groups semantically similar memories
- API: `GET /api/brain/{persona_id}` → JSON `{nodes: [...], edges: [...]}`
- `tests/newton/api/test_brain_endpoint.py`

**Visual design:**

```
each persona has its own brain
nodes = vault notes + conversation summaries
node color = persona's color (JARVIS blue, Friday pink)
node size = recency (recent = larger)
node connections = cross-references in notes (wikilinks)
ambient lighting matches persona's color theme
camera starts at center, free orbit
```

**Verification:**

```bash
# Manual: click 3D Brain tab; rotate with mouse drag; nodes labeled
```

**Commit:** `feat(brain): R3F scene with UMAP-projected memory clusters`

---

### Step 11.8 — 3D Brain gestures (deferred from Block 8) (1.5 days)

**Goal:** Gestures for rotating, zooming, and selecting Brain nodes.

**Outputs:**

- `newton/gesture/brain/brain_actions.py` — gesture-bound actions
- Tools (risk 1, since UI-only):
  - `brain_rotate` (continuous from hand orientation)
  - `brain_zoom_in` / `brain_zoom_out`
  - `brain_select_nearest_to_cursor` (pinch when pointing)
  - `brain_show_node_details` (point hold 1s)
- Activation: only when 3D Brain tab is focused
- `tests/newton/gesture/test_brain_gestures.py`

**Bindings sir registers (via block 8 CLI):**

```bash
newton gesture register palm_open --static --scope shared
newton gesture bind <palm_open_id> --action 'brain_rotate:{}'

newton gesture register pinch_close --static --scope shared
newton gesture bind <pinch_close_id> --action 'brain_zoom_in:{}'

# ... etc
```

**Verification:**

```bash
# Manual: 3D Brain tab open
# sir does palm_open → brain rotates with hand
# sir does pinch → brain zooms
# sir points + holds → node info appears
```

**Commit:** `feat(brain): 3D Brain gesture controls`

---

### Step 11.9 — Autoresearch dashboard tab (1 day)

**Goal:** UI for viewing autoresearch jobs (block 7).

**Outputs:**

- `newton-ui/src/tabs/AutoresearchTab.tsx`
- API: `GET /api/autoresearch/jobs`, `GET /api/autoresearch/jobs/{id}/cycles`
- Live progress for running jobs
- Best-result preview with markdown diff

**Verification:**

- Job list shows status / progress / best score
- Click job → see all cycles + scores
- Result preview shows the best version

**Commit:** `feat(ui): autoresearch dashboard`

---

### Step 11.10 — Settings tab + multi-user UI controls (1 day)

**Goal:** UI for everything sir would otherwise do via CLI.

**Outputs:**

- `newton-ui/src/tabs/SettingsTab.tsx` with sub-sections:
  - Personas (read-only — config-managed)
  - Proactive mode + quiet hours
  - Gesture mode
  - Provider hot-swaps (web.search, vision.llm, etc.)
  - Approval policies (table with per-tool decisions)
  - HUD position + opacity + which widgets visible
  - Voice samples directory status
- API: `GET/PUT /api/settings/<section>`
- `tests/newton/api/test_settings_endpoint.py`

**Verification:**

- Each setting maps to existing CLI command
- UI changes persist to the same DB rows

**Commit:** `feat(ui): settings tab covering all major controls`

---

### Step 11.11 — Mobile client (Tauri Mobile) (2.5 days)

**Goal:** iOS + Android build of newton-ui. LAN-only thin client.

**Outputs:**

- Tauri Mobile config in `newton-ui/`
- Mobile-specific layout (responsive)
- Mobile features (initial set):
  - Voice (uses phone mic)
  - Recent proactive notifications
  - Vault search
  - Calendar view
  - Persona switch
- Mobile *omits* (post-v1.0):
  - Full gesture / camera features
  - 3D Brain (or: simplified 2D view)
  - HUD (mobile has its own notification system)
- LAN discovery via mDNS (`newton.local`)
- `tests/newton/mobile/test_lan_discovery.py`

**Build artifacts:**

- iOS .ipa (requires sir's Apple Developer account or sideload)
- Android .apk (sideload-ready)

**Authentication on mobile:**

- Initial pairing via QR code from desktop
- Pairing exchanges a long-lived token bound to (device + sir's user_id)
- Token stored in iOS Keychain / Android Keystore
- All API calls TLS-encrypted within LAN; signed with token

**Verification:**

- iOS device on same LAN sees newton.local; can pair
- Voice command from iPhone reaches home Newton; response speaks on iPhone

**Risk:** Tauri Mobile is newer than Tauri Desktop; rough edges expected.
**Mitigation:** if blocked, fallback to React Native or a PWA install.

**Commit:** `feat(mobile): Tauri Mobile thin client with LAN pairing`

---

### Step 11.12 — Multi-client session management (1.5 days)

**Goal:** Same sir, multiple clients (desktop + mobile + HUD overlay).
One session, coordinated.

**Outputs:**

- `newton/api/sessions/multi_client.py`
- Session state syncs across clients via SSE
- Voice activated on desktop → mobile UI also shows "JARVIS listening"
- Notification fires → desktop HUD + mobile push (LAN push)
- `tests/newton/api/test_multi_client.py`

**Conflict resolution:**

```
two clients both send voice command "JARVIS, status?" within 1 second
    ↓
backend treats as single intent (deduplicate by content within 1s window)
    ↓
single response broadcast to both clients
```

**Verification:**

- Desktop + mobile both connected
- Voice on desktop → mobile shows active session
- Proactive notification → both clients show it

**Commit:** `feat(api): multi-client session synchronization`

---

### Step 11.13 — Block 11 summary + v1.0 release tag (1 day)

**Goal:** Final block. Newton reaches v1.0.

**Outputs:**

- `docs/newton/block-11-summary.md`
- `docs/newton/cli.md` — final audit
- `docs/newton/user-guide.md` — sir-facing manual (NEW for v1.0)
- `README.md` — Block 11 marked complete; v1.0 announced
- `CHANGELOG.md` — full block-by-block history
- Git tag: `v1.0.0`

**v1.0 release criteria:**

- All 11 blocks complete (block 10 may be skipped)
- All pytest cases pass (~738+ counted in block 9; UI tests are
  out-of-pytest)
- Preflight 9/9 still ✓
- OpenJarvis: still 0 files modified
- sir can use Newton end-to-end without the CLI for daily operations
- HUD always visible
- Mobile client paired
- 3D Brain rendering correctly
- All 13 movie-JARVIS capabilities from jarvis-gap.md operational
  (or explicitly noted as deferred / out-of-scope)

**Commit + tag:** `chore: block 11 complete — Newton v1.0`

---

## 2. Deliberately not in Block 11

These are explicitly post-v1.0:

- ❌ **Public release** — Newton stays personal use only
- ❌ **Federated Newton across sir's friends** — out of scope
- ❌ **Cloud deployment option** — local-first principle
- ❌ **VR / AR Brain viewer** — interesting but not v1.0
- ❌ **Voice-only setup for blind / low-vision users** — accessibility
  pass deferred
- ❌ **Theming engine / plugin system** — defer
- ❌ **Translation of UI text into Korean** — possible in v1.1
- ❌ **Web-public deployment** — never (local-first invariant)

---

## 3. Risk matrix

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Tauri Mobile too immature → mobile blocked | Med | PWA fallback documented |
| HUD performance impacts main work | Med | Throttled updates; SSE batching |
| 3D Brain laggy with large vaults (10k+ notes) | Med | LOD (level-of-detail) rendering; cluster collapse |
| OpenJarvis UI fork drift if upstream changes | Low | Newton extends, doesn't modify; merge upstream separately |
| Gestures conflict with mouse / keyboard input | Med | Activation gating (Block 8) prevents UI accidents |
| LAN-only mobile fails when sir is away | Med | Out of scope (local-first); future VPN extension noted |
| iOS App Store rejection (sideload only) | Low | Sir's personal cert; documented |
| Multi-client session sync race conditions | High | Last-write-wins + SSE serialization; tests cover concurrency |
| HUD always-on-top blocks dialogs sir wants | Low | toggleable; HUD respects fullscreen by hiding |
| 3D Brain shows private info to onlookers | Med | HUD shows only metadata; full content requires sir's session lock |
| 20–30 day estimate optimistic | High | Frontend work expands; mid-block re-estimate after step 11.5 |

---

## 4. After Block 11 — sir's daily Newton

There is no Block 12 in v4 scope. After Block 11:

- Newton runs as a systemd user service on the home machine
- Boots automatically; persona Engine + Proactive Daemon always on
- Sir uses voice, gesture, or UI as natural for each moment
- Mobile client paired; phone is a thin extension of home Newton
- HUD always visible (or toggled off)
- All 11 blocks of infrastructure quietly serving sir's day

The opening message for "Newton v1.1 planning" — if sir wants further
work — is a different document.

---

## 5. Honest reality check

**Time estimate:** **20–30 days at sir's pace (4–6 weeks).** Frontend
work expands. sir is slower in React than Python; budget realistically.

**Riskiest steps:**

- **Step 11.11** (mobile) — Tauri Mobile maturity is the biggest unknown
- **Step 11.7** (3D Brain) — UMAP projection of large vaults at
  interactive speed is non-trivial
- **Step 11.12** (multi-client sync) — concurrency bugs are hardest

**Simplest steps:**

- 11.1, 11.2, 11.13 — investigation + scaffolding + summary

**Most important step:**

- **Step 11.6** (HUD). This is the most user-visible artifact of Newton.
  Movie-JARVIS feel lives or dies here.

**Behavioural shift:**

After Block 11, Newton is *finished*. Sir's daily life features Newton
as a quiet, attentive household member with a movie-aesthetic interface,
voice, gestures, faces, vault, proactivity, autoresearch, and mobile
extension. v1.0.

The behavioral shift after every block in order:
- Block 1: Newton exists (just data)
- Block 2: Newton can use tools safely
- Block 3: Newton knows sir's notes
- Block 4: Newton speaks up usefully
- Block 5: Newton listens and talks
- Block 6: Newton sees and recognizes
- Block 7: Newton acts on the world
- Block 8: Newton responds to sir's hands
- Block 9: Newton reaches into sir's life beyond the desk
- Block 10: Newton sounds more like sir's Newton (optional)
- Block 11: Newton looks like JARVIS

**Assets carried over:**

- All 18 tables from blocks 1-9 in active use
- Provider Registry full of providers (web search, vision, doc, video, ...)
- Tool Registry with ~30 builtin tools
- Approval policies + reactions + patterns accumulated
- Vault: substantial; conversations summarized
- LoRA adapters (if Block 10 ran) loaded per persona
- Voice + face + gesture all wired
- ~738 pytest cases must still pass

---

## 6. Starting checklist

Before Block 11 begins:

- [ ] Block 10 tagged `v0.10.0-block10` (or marked skipped)
- [ ] Pytest ~738 passing
- [ ] Node.js + npm available (for newton-ui)
- [ ] Tauri toolchain installed and working
- [ ] React + Vite work on this Python's host system
- [ ] OpenJarvis UI builds and runs (baseline test)
- [ ] R3F + drei installable
- [ ] iOS dev account or Android dev mode available (for mobile)
- [ ] sir has 4–6 weeks of focused work
- [ ] LAN subnet identified for mDNS discovery

---

Ready when sir is. Step 11.1 is the entry point.

After this block, Newton is v1.0.
