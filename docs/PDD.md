# PhotoSphere AI 2.0 — Product Design Document

**Status: DRAFT — awaiting approval. No UI implementation until this document
is reviewed and approved.**

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

## 3. Information Architecture

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
├ SYSTEM ──────────────┤     Same person? · Is this <name>? · Unknown faces ·
│  Settings            │     (later) duplicates, low-confidence matches.
│  About               │
└──────────────────────┘
```

Changes from 1.x: "Search" leaves the sidebar (permanent top bar + palette);
"Videos/Objects/Similar/Archive/Trash" placeholders are removed from view
(reserved keys remain in the registry); **AI Review** is new and absorbs the
per-page suggestion strips as *one* workflow with a live badge.

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

## 5. Component Library (build once, reuse everywhere)

`viewer/components/` grows into a real kit; pages may only compose these:

PhotoCard · PersonCard · AlbumCard · SuggestionCard (one design for *all* AI
questions: evidence left, verdict buttons right) · SearchResultRow · InfoPanel
(inspector) · MetadataChip · StatusBadge · ProgressOverlay · TimelineHeader
(sticky) · EmptyState (icon + one sentence + one action) · SkeletonLoader ·
Toolbar · ContextMenu · CommandPalette · Toast.

Rules: every interactive element ≥ 40 px hit target; every component renders a
skeleton state; every list is virtualized (existing model/view pattern).

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

Right inspector with People / Info / OCR text / Similar tabs (updates
instantly from the knowledge base); Esc or F toggles full immersion; ← → and
filmstrip navigate; ♥ favorites.

### 6.4 People — identity profiles

Person page becomes a profile: avatar + editable name (click-to-rename),
first/last seen, photo count, **Appearances** (the learned gallery — already
built), **Suggestions** (already built), photos grid, actions (Merge, Export,
Delete). People grid keeps virtualization; adds search-within-people and the
"Same person?" strip (already built).

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

Consolidates every pending question (the strips remain in-place shortcuts; the
Review page is the same data as one keyboard-driven queue). Sidebar badge shows
the count. Future: duplicates, model-update reviews land here.

### 6.8 Settings

Grouped panes (Library folders · Appearance · AI & performance · Shortcuts ·
About) reading/writing the existing env-backed settings; worker counts and
thresholds live under "AI & performance" with plain-language labels.

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
