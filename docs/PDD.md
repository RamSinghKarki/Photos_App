# PhotoSphere AI 2.0 — Product Design Document

**Status: APPROVED — FROZEN (rev 2).** Qt Widgets confirmed for 2.0 (no QML
migration). Rev 1 added: three-pane layout, search-first workflow, activity
dashboard, immersive viewer workspace, rich people profiles, categorized AI
Review, command palette, notification center, visual-hierarchy levels, empty
states, full design system, future reservations, responsive rules,
micro-interactions, visual identity, Phase 0 UX prototype. **Rev 2 (product
review) added:** guided onboarding, the Insights ("what PhotoSphere knows")
page, an About/trust page, the user-facing vocabulary table, liveness
behaviors, the delight catalogue, and Phase 0 validation criteria (30-second
first-use test + two-click audit). Design is frozen; Phase 1 implementation
proceeds. Amendments from here are edits to this file, reviewed the same way.

This is the design contract for the 2.0 experience: what we build, why each
piece exists, and the order it lands in. It supersedes screen-by-screen tweaks;
every future UI change traces back to a rule here.

---

## 1. Product Vision

PhotoSphere AI is an **AI-powered visual knowledge platform**, not a photo
viewer. The user explores *memories*, not folders. The interface must
communicate three ideas without ever saying them:

1. Everything is organized.
2. Everything is searchable.
3. The app understands your library.

The experience is calm, elegant, professional, and nearly invisible. AI is
never announced — it quietly makes everything easier.

**Positioning:** Google Photos' organization + Lightroom's professionalism +
Apple Photos' immersion + Raycast's speed + Windows 11's material language —
fully offline, privacy-first.

## 2. UX Principles (binding)

| # | Principle | Operational rule |
|---|-----------|------------------|
| 1 | **Content first** | Photos are the hero; chrome recedes. No toolbar may exceed 48 px height; viewer chrome auto-hides. |
| 2 | **One click away** | Any core object (photo → person → their photos; photo → date → that day) reachable in ≤ 2 clicks. |
| 3 | **Zero waiting** | Never a blocking spinner. Skeleton cards, progressive thumbnails, streamed results, 150 ms fades. |
| 4 | **Invisible AI** | Vocabulary: "People", not "Face Recognition". "Search your memories…", not "Semantic search". "Same person?", not "Cluster merge". Confidence numbers only in Review, never in browsing surfaces. |
| 5 | **One question per screen** | Dashboard: *what's happening?* Photos: *everything.* People: *who?* Timeline: *when?* Albums: *how organized?* Review: *what does the app need from me?* |
| 6 | **Trust through control** | Every automatic decision is inspectable and reversible (already true in the engine: rejections, merge feedback, appearances). The UI's job is to surface it calmly. |

### 2.1 Vocabulary (binding, user-facing)

Research language never reaches the user. Technical detail lives only in
Insights → Diagnostics and in the docs.

| Never show | Say instead |
|---|---|
| Face recognition / clustering / HDBSCAN | **People** |
| Semantic search / CLIP / embeddings | **Search your memories…** |
| OCR | **Text in photos** |
| Confidence score (outside Review) | *(nothing — evidence lives in Review only)* |
| Merge clusters | **Same person?** |
| Re-index / pipeline | **Update library** |
| Model / inference / GPU CUDA EP | **AI (on this device)** / **Accelerated** |

### 2.2 Liveness (the app works while you watch)

Premium software never feels static. Required behaviors: greeting follows the
clock; "On this day" rotates daily; the Review badge updates live as the
pipeline finds questions; indexing progress ticks in place; GPU/status pulses
subtly while processing; recent searches accumulate automatically; "Recently
added" fills during import. All driven by existing signals — no polling loops
on the UI thread.

### 2.3 Delight catalogue (the "wow" moments)

Budgeted, not scattered — each is one orchestrated moment: first launch opens a
**guided welcome**, never an empty app (§6.10); the first import becomes a live
"building your library" experience (progress + filling grid); a person newly
recognized confirms with a subtle toast + card shimmer; hovering a person card
peeks their recent photos; opening a photo zooms from its thumbnail (220 ms).
Nothing exceeds the motion caps; all honor reduced-motion.

## 3. Information Architecture

### 3.1 Three-pane layout (the structural change)

```
┌─────────┬───────────────────────────────┬──────────────────────┐
│ Sidebar │        Main content           │  Context / Inspector │
│ (nav)   │  (the current workflow)       │  (about the selection)│
└─────────┴───────────────────────────────┴──────────────────────┘
```

The right **inspector** is one persistent panel whose content follows context —
Lightroom/VS Code style, killing most dialogs:

| Context | Inspector shows |
|---|---|
| Photo selected | metadata, faces, OCR text, similar, (later) objects |
| Person | profile summary, known appearances, appears-with |
| Album | info, counts, rules (for smart albums) |
| Search | active filters + "why matched" explanation |
| AI Review | evidence and confidence for the focused question |
| Nothing | collapsed |

### 3.2 Responsive rules

- **Ultra-wide:** sidebar + content + inspector all visible.
- **Laptop (< ~1280 px):** inspector collapses to a toggle (I key / button).
- **Narrow (< ~900 px):** sidebar collapses to icon rail; content only.
Breakpoints are layout-driven (splitter policies), never fixed pixels.

### 3.3 Navigation

Navigation reorganizes around workflows, not modules:

```
┌ LIBRARY ─────────────┐   Search  = permanent capability (top bar + Ctrl+K
│  Dashboard           │            command palette), not a page.
│  Photos              │   Import  = global action (button, drop anywhere,
│  Timeline            │            Ctrl+O), not a place.
│  People              │
│  Albums              │   Reserved (hidden until built): Videos, Documents,
│  Favorites           │   Maps, Duplicates, Plugins.
├ AI ──────────────────┤
│  Review  (badge: N)  │   ← consolidates ALL pending questions:
│  Insights            │     Same person? · Is this <name>? · Unknown faces ·
├ SYSTEM ──────────────┤     (later) duplicates, low-confidence matches.
│  Settings            │   Insights = "what PhotoSphere knows" (§6.9).
│  About               │   About = the trust page (§6.10).
└──────────────────────┘
```

Changes from 1.x: "Search" leaves the sidebar (permanent top bar + palette);
"Videos/Objects/Similar/Archive/Trash" placeholders are removed from view
(reserved keys remain in the registry); **AI Review** is new and absorbs the
per-page suggestion strips as *one* workflow with a live badge.

**Search is the heart of the app, not a page**: the "Search your memories…"
box is permanently visible in the top bar on every screen; typing anywhere
routes intent automatically (person / text / semantic / date / album — the
engine decides, never the user). Ctrl+K opens the same engine as a command
palette.

**Future reservations** (registry keys exist, hidden until built): Videos,
Documents, Maps, Duplicates, Shared Libraries, Plugins, Developer Mode. Adding
any of them later is a registry entry, not a navigation redesign.

## 4. Visual Language & Design Tokens

Fluent-family look: layered surfaces, rounded corners, soft elevation, generous
whitespace, typography-led hierarchy. Dark mode is the default identity;
light mode fully supported.

**Tokens (single source: `viewer/theme.py` — no literal values in pages):**

- **Spacing:** 4 / 8 / 12 / 16 / 24 / 32 / 48. Nothing arbitrary.
- **Radius:** 8 (controls), 12 (cards), 16 (dialogs/overlays).
- **Elevation:** L0 window bg · L1 cards/sidebar · L2 dialogs/inspector ·
  L3 popups/palette. Expressed as background tint + 1 px border + soft shadow.
- **Type:** Segoe UI Variable (fallback: Segoe UI / system). Sizes 12 (meta),
  14 (body), 16 (emphasis), 20 (section), 28 (page title), 36 (hero greeting).
  Weights: Regular, Medium, Semibold, Bold only.
- **Color:** neutral surface ramp (5 stops per mode) + one accent
  (Fluent blue family) + semantic green/amber/red. Photos supply the color;
  the UI stays neutral. Colorblind-safe: semantic colors always paired with an
  icon or label.
- **Motion:** hover 120 ms · selection 150 ms · fade 150 ms · dialog 180 ms ·
  sidebar 200 ms · photo-open 220 ms. **Hard cap 250 ms**; every animation is
  interruptible; `prefers-reduced-motion`-style toggle in Settings disables all.

### 4.1 Visual hierarchy (three emphasis levels)

Every screen composes exactly three levels, so the eye always knows where to
look first: **Primary** — large imagery/cards (photos, profiles, review
evidence); **Secondary** — lists and grids supporting the primary; **Tertiary**
— metadata, chips, counts (muted color, size 12–14, never bolder than
secondary). A screen with two competing primaries is a design bug.

### 4.2 Visual identity

Recognizable at a glance: lens-inspired mark (concentric rounded aperture, used
in the sidebar header and About), single blue accent, rounded cards, one icon
family (the existing line-drawn set, extended — never mixed with emoji in
chrome), minimal gradients (photos provide the color), generous whitespace.

### 4.3 Micro-interactions (the premium feel)

Hover elevation (card lifts one level, 120 ms) · press ripple on buttons ·
thumbnail fade-in as decodes land (already async) · animated selection check
(150 ms) · smooth kinetic scrolling · native context menus everywhere ·
skeleton loaders on every list · animated determinate progress. Nothing
flashy; all interruptible; all within the 250 ms cap.

### 4.4 Notification center (no interrupting dialogs)

Modal popups are reserved for destructive confirmations only. Everything else
flows through a **notification panel** (bell in the top bar, badge for unread)
plus transient 3 s toasts: *Import finished · 3 duplicate people found · OCR
complete · GPU switched to CUDA · Backup completed.* Notifications are
actionable (click → relevant screen) and logged, not lost.

## 5. Component Library (build once, reuse everywhere)

`viewer/components/` grows into a real kit; pages may only compose these:

PhotoCard · PersonCard · AlbumCard · SuggestionCard (one design for *all* AI
questions: evidence left, verdict buttons right) · SearchResultRow ·
InspectorPanel (context-driven, §3.1) · MetadataChip · StatusBadge ·
ProgressOverlay · TimelineHeader (sticky) · EmptyState · SkeletonLoader ·
Toolbar · ContextMenu · CommandPalette · NotificationCenter · Toast.

Rules: every interactive element ≥ 40 px hit target; every component renders a
skeleton state; every list is virtualized (existing model/view pattern).

**Empty states are designed, not blank**: every page ships one — icon, one
sentence, one action ("No albums yet — Create your first album [New Album]";
"All caught up" in Review; "Import photos to begin" in Photos). An empty page
without its empty state fails review.

## 6. Screen Specifications (low-fi wireframes)

### 6.1 Dashboard — "the control center"

```
┌────────────────────────────────────────────────────────────────┐
│  Good evening                                    ⟳ Processing…  │
│  102,451 photos · 438 people · 12 albums                        │
│                                                                 │
│  ┌ Review (7) ──────────┐ ┌ Recently added ──────────────────┐ │
│  │ ▣▣ Same person? (2)  │ │ ▢ ▢ ▢ ▢ ▢ ▢ ▢ ▢   (photo strip) │ │
│  │ ☺ Is this Ram? (5)   │ └──────────────────────────────────┘ │
│  └──────────[Open]──────┘ ┌ On this day ─────────────────────┐ │
│  ┌ Library health ──────┐ │ ▢ ▢ ▢ ▢    July 20, 2023 · 2021  │ │
│  │ GPU ● · DB ● · 98%   │ └──────────────────────────────────┘ │
│  │ indexed              │  Quick actions:                       │
│  └──────────────────────┘  [Import] [Search] [New album] …      │
└────────────────────────────────────────────────────────────────┘
```

Activity, not statistics: Review card (live badge), Recently added, On-this-day
memories, processing/GPU/storage health, quick actions, recent searches.

### 6.2 Photos — adaptive gallery

Adaptive **justified rows** (variable widths, uniform row height — masonry's
look without its scroll-virtualization cost), infinite scroll, hover reveals
date/name/♥, marquee + Ctrl selection with 150 ms check animation, zoom
Ctrl+wheel. Skeletons while pages stream in.

### 6.3 Photo Viewer — the centerpiece

```
┌──────────────────────────────────────────────┬───────────────┐
│                                              │ People    ▸   │
│                                              │  ☺ Ram  ☺ ?   │
│                 (photo, immersive,           │ Info      ▾   │
│                  chrome auto-hides)          │  f/1.8 1/250  │
│                                              │  Jul 4 2021   │
│                                              │  GPS · Camera │
│                                              │ Text (OCR) ▸  │
│                                              │ Similar    ▸  │
├──────────────────────────────────────────────┴───────────────┤
│  ▢ ▢ ▢ ▣ ▢ ▢ ▢   (filmstrip)                                 │
└──────────────────────────────────────────────────────────────┘
```

The viewer is a **workspace, not a popup**: opening a photo replaces the main
content (sidebar collapses to an icon rail) rather than floating a dialog.
Right inspector with People / Info / OCR text / Similar tabs (updates
instantly from the knowledge base). Keyboard: double-click or Enter enters the
workspace · **Space** hides all UI (photo only) · **F** OS fullscreen · ← → and
filmstrip navigate · ♥/F-key favorites · Esc backs out with scroll position
preserved. Full-res streams progressively over the already-loaded thumbnail —
opening is always instant.

### 6.4 People — identity profiles

Every person is a **profile, not a folder**:

```
┌ ☺ Ram ✎                      452 photos ┐
│ First seen 2019 · Last seen yesterday    │
│ Known appearances: ▣▣▣▣▣  (the gallery)  │
│ Appears with: ☺ Hari · ☺ Sita · ☺ Mother │
│ [Suggestions strip]  [Merge] [Export]    │
│ ─ photos grid, newest first ─            │
└──────────────────────────────────────────┘
```

Avatar + click-to-rename name; first/last seen (min/max `taken_at`, cheap
query); photo count; **Known appearances** = the representative gallery
(built); **Appears with** = co-occurrence (people sharing photos — one new
query, no schema change); suggestions strip (built); actions Merge / Export /
Delete. Confidence numbers stay out of the profile (Review-only). People grid
keeps virtualization, adds name search and the "Same person?" strip (built).

### 6.5 Search — the signature

One box, always visible; **Ctrl+K command palette** opens the same engine
anywhere. Intent is inferred, never chosen: person names → person filter
(built), text-match → OCR boost (built), dates/"2024" → time filter, the rest →
semantic. Results stream into the standard grid with subtle "why" chips
(☺ Ram · ⊞ text match) — the only place AI evidence is visible outside Review.

### 6.6 Timeline — memory navigation

Year → month sticky headers in one continuous scroll (replacing the tree),
right-edge year scrubber for direct jumps, smooth per-section fades. Backed by
the existing bucket queries.

### 6.7 AI Review — a workflow, not a dialog

```
┌ Review ────────────────────────────────────────────┐
│ Same person? (2) · Is this Ram? (5) · Unknown (12) │  ← filter tabs
│ ┌───────────────────────────────────────────────┐  │
│ │ ☺A ☺B  "These look like the same person"      │  │
│ │         match 0.63      [Merge] [Not the same]│  │
│ ├───────────────────────────────────────────────┤  │
│ │ ☺  "Is this Ram?"  0.52       [Yes] [No]      │  │
│ └───────────────────────────────────────────────┘  │
│            keyboard: Y / N / ↓  — flow, not clicks │
└────────────────────────────────────────────────────┘
```

Consolidates every pending question as one keyboard-driven queue (the in-page
strips remain as shortcuts to the same data). Work is **categorized**, and every
future source of uncertainty lands here without new UI:

| Category | Source |
|---|---|
| Possible merge ("Same person?") | merge scan (built) |
| Low-confidence match ("Is this \<name\>?") | active learning (built) |
| Needs identity / Unknown faces | large unnamed persons + ungrouped clusters |
| Possible duplicate photos | duplicates module (queued) |
| OCR / Object review | future modules |
| Model updates | future re-embedding reviews |

Sidebar badge shows the total; the inspector shows evidence (covers, scores,
context) for the focused item — the *only* surface where confidence numbers
appear.

### 6.8 Settings

Grouped panes (Library folders · Appearance · AI & performance · Shortcuts)
reading/writing the existing env-backed settings; worker counts and thresholds
live under "AI & performance" with plain-language labels. Diagnostics (model
names, CUDA provider, thresholds' raw values) live here — the only place
technical vocabulary is allowed.

### 6.9 Insights — "what PhotoSphere knows"

The AI made visible — reinforcing that the app builds *knowledge*, not files:

```
┌ Insights ────────────────────────────────────────┐
│ Your library, understood                          │
│  ☺ 438 people      ⌖ 72 places     ⊞ 8,120 photos│
│  ¶ text in 3,204   ♥ 512 favs      ？16 unknown  │
│  ✓ 7 awaiting review        ⚡ Accelerated (GPU) │
│  Knowledge base: healthy · learning from you:     │
│  212 corrections remembered · 31 people named     │
└──────────────────────────────────────────────────┘
```

Counts come from existing queries (library stats, feedback counts, suggestion
counts). A quiet "Diagnostics" link at the bottom exposes the technical view.

### 6.10 Onboarding & About

**First launch is a guided welcome, never an empty app:**
Welcome → choose folder → live "building your library" (scan → thumbnails →
finding people → making it searchable, with the grid filling behind) → Ready.
Each step is the real pipeline with friendly stage names; skippable; replayable
from About.

**About is the trust page**, in plain language: *Everything stays on your
computer · No cloud, no accounts, no telemetry · Your corrections teach it ·
Accelerated by your GPU · Works completely offline.* One screen that sells the
product's difference.

## 7. User Flows

- **Import:** drop folder anywhere (built) → toast "Importing 1,204 photos" →
  status-bar progress (built) → dashboard "Recently added" fills live → Review
  badge increments as questions appear. Zero dialogs.
- **Search:** Ctrl+K → type "ram beach 2021" → results stream < 100 ms cached /
  < 1 s first-model-load with skeletons → Enter opens viewer → Esc back with
  query preserved.
- **Review:** click badge → queue → Y/N/↓ through questions → each answer
  teaches the engine (built) → empty state: "All caught up."
- **Browse people:** People → profile → appearances/suggestions/photos →
  rename inline → merge duplicates via strip or profile.
- **View photo:** click → 220 ms open → inspector tabs → click a face chip →
  that person's profile (2 clicks, rule upheld).

## 8. Accessibility

Full keyboard navigation (every action reachable; palette lists shortcuts);
screen-reader names on all interactive elements (Qt accessible names); high-
contrast mode follows OS; colorblind-safe semantics; 125/150/200 % DPI via
layout-driven sizing (no absolute pixel layouts); ≥ 40 px targets; visible
focus rings.

## 9. Performance Constraints (non-negotiable, measured)

Launch < 3 s · tab switch < 50 ms · search < 100 ms (warm) · viewer open
instant (progressive: thumbnail first, full-res streamed) · 60 fps scroll ·
stable memory at 100k+ photos. The existing benchmark harness gates every
phase; a phase that regresses these does not merge.

## 10. Technology Decision: Qt Widgets, not QML (for 2.0)

Assessed honestly: QML offers GPU-composited motion, but a QML rewrite means
rebuilding the proven virtualized model/view stack (the exact code meeting the
50 ms/60 fps targets today), a big-bang risk violating "every phase remains
functional", and a second language surface. **Decision: stay on QtWidgets** —
the entire spec above (tokens, elevation, motion ≤ 250 ms, palette, justified
gallery) is achievable with QSS + custom painting + `QPropertyAnimation`, built
incrementally with zero regressions. QML remains a future presentation-layer
option behind the same Python backend if 3.0 demands richer motion.

## 11. Implementation Phases (each ships functional, tested, benchmarked)

| Phase | Scope | Builds on |
|---|---|---|
| 0 | **UX prototype**: clickable mockup of the full journey (three-pane shell, dashboard, photos, viewer workspace, person profile, review queue, palette, notifications, insights, onboarding, about) — walked through and approved *before* Qt code. **Validation criteria:** a first-time user completes import / find a person / search "passport" / merge two people / open the viewer / find Review in 30 s unaided; every core task audited at ≤ 2 clicks; zero technical vocabulary visible outside Settings/Diagnostics | `docs/prototype.html` — ✅ approved |
| 1 | **Design system**: tokens, elevation, type ramp, component kit + skeletons, motion utilities | audit item 7 (page registry) folds in here |
| 2 | **Navigation**: registry-driven sidebar w/ badge, top bar, Ctrl+K palette | |
| 3 | **Dashboard** (activity model) | |
| 4 | **Photos** (justified gallery, hover, selection motion) | |
| 5 | **Viewer** (inspector tabs, filmstrip, immersion) | |
| 6 | **People** (profiles) | strips already built |
| 7 | **Timeline** (continuous scroll, scrubber) | |
| 8 | **Search** (palette + why-chips + streaming) | |
| 9 | **AI Review** (queue + keyboard flow) | engine complete |
| 10 | **Settings** | |
| 11 | **Polish**: toasts, undo, empty states, a11y audit, perf regression run | |

Rules for every phase: no regressions (118-test suite + benchmarks green),
docs updated, offline/incremental/GPU constraints preserved.

---

*Approval gate: implementation of Phase 1 begins only after this document is
approved. Amendments are edits to this file, reviewed the same way.*
