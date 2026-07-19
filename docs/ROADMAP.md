# PhotoSphere AI — Roadmap to v1.0

**Vision.** A professional, **fully offline**, AI-powered photo management
platform: complete privacy with intelligent organization, search, and
recognition — no cloud, ever. It scales from today's face recognition to
semantic search, OCR, object detection, duplicate detection, and smart albums
while keeping everything local.

This roadmap sequences the work into milestones. It is deliberately incremental:
each milestone is production-quality and shippable on its own.

---

## Where we are today (v0.4)

Already built, tested, and offline:

| Capability | Status | Notes |
|-----------|--------|-------|
| Scanner (EXIF + dedup) | ✅ | SHA-256 identity, EXIF incl. GPS, streaming, idempotent |
| Thumbnails | ✅ (single size) | cached, EXIF-oriented, async decode; **multi-res pending** |
| Metadata in PostgreSQL | ✅ (core) | camera/model/orientation/GPS/dims/taken_at; **lens/ISO/exposure/focal pending** |
| Face detection + embeddings | ✅ | InsightFace on GPU (CPU fallback), 512-d, raw embeddings |
| Clustering → people | ✅ | DBSCAN cosine; cover face; ungrouped left NULL |
| Background pipeline | ✅ | one worker chains scan→thumb→face→cluster, progress + ETA, **Stop/Continue** |
| Manual per-photo face detection | ✅ | select → right-click → detect |
| Desktop UI (Fluent, dark) | ✅ | shell, dashboard, gallery (paged + async), people, viewer, status/GPU badges |
| Resume UI state | ✅ | window/page/zoom/import-folder remembered |
| GPU detection + graceful CPU fallback | ✅ | `scripts/setup_check`, status badge |
| Docs | ✅ (core) | README, INSTALL, ARCHITECTURE, DATABASE, DEVELOPMENT, system prompt |

So several roadmap items (thumbnail engine, metadata engine, background jobs,
memory cache, GPU fallback, error recovery, base docs) already exist in a first
form. The milestones below **extend** them rather than starting over.

---

## Milestones

### M5 — Google-Photos core (next, user-prioritized)
The immediate milestone, in order:
1. ✅ **Clustering** — DBSCAN + optional **HDBSCAN** (auto-select if installed,
   DBSCAN fallback); `--algorithm` flag / `PHOTOSPHERE_CLUSTER_ALGORITHM`.
2. ✅ **People page: rename + merge** (+ delete/ungroup) — people are editable.
3. ✅ **Fast gallery with cached thumbnails** — Photos and People are both
   virtualized (Model/View + async); People tab 228 ms → 11 ms (see
   [PERFORMANCE.md](PERFORMANCE.md)). Multi-resolution tiers still optional (M8).
4. ✅ **AI Search subsystem with CLIP** — modular embedding backend interface
   (CLIP first; SigLIP/others pluggable), incremental + batched + GPU embedding
   in the background pipeline, versioned `clip_embeddings` table, text-embedding
   cache, and a Search tab. See [AI_PIPELINE.md](AI_PIPELINE.md).

**M5 complete.**

### M6 — Self-improving recognition (done: core loop)
Person profiles (centroids) + **incremental, name-preserving** recognition:
naming a person teaches the app, new faces are auto-matched, existing names are
never wiped, confidence-gated. Covers vision Levels 1, 2, 4, 14. See
[LEARNING.md](LEARNING.md). Remaining levels (feedback history, hybrid signals,
active learning, personal classifier) are queued there.

### Architecture — Plugin pipeline ✅
The AI ingestion pipeline is now a **plugin system** (`pipeline/`): thumbnails,
faces, people, CLIP, OCR are plugins run by a `PluginManager`. New capabilities
(object detection, video, duplicates, new models) register one plugin and slot
into Import/Re-index with no core changes. See [PLUGINS.md](PLUGINS.md).

### Recognition engine v2 — persistent person identity ✅
Recognition now keeps a **representative gallery** per person (a diverse,
quality-gated embedding set) with **adaptive per-person thresholds**, instead of
a single centroid — recognizing the same person across viewpoint, facial hair,
glasses, lighting, and age. Quality scoring gates what may teach; accepted faces
adapt the profile; names are preserved and pre-gallery people are backfilled.
New tables/columns: `person_embeddings`, `persons.adaptive_threshold`. See
[LEARNING.md](LEARNING.md).

**Feedback memory** ✅ — "Not <name>" on a person's page detaches faces and
records a durable **rejection** (`recognition_feedback`); recognition never
re-assigns a rejected (face, person) pair.

**Appearance gallery UI** ✅ — a person's page shows the learned representative
crops ("Learned appearances", best-quality first); right-click removes a bad one
(recorded as a rejection). *Next:* context fusion, active learning (the `confirm`
verdict is reserved).

### Phase A — Stabilize v1.0 (in progress)
- ✅ **Benchmarks** — `scripts/benchmark.py` + [BENCHMARKS.md](BENCHMARKS.md):
  all interactions < 50 ms up to 100k photos.
- ✅ **Robustness tests** — missing thumbnails, AI model/GPU unavailable, DB
  unreachable at launch (`tests/test_robustness.py`); corrupt/deleted images and
  interrupted work covered by existing suites.
- ✅ **Timeline view** — Year → Month browsing over `taken_at`, virtualized
  grid (`viewer/timeline_page.py`, `db.list_timeline_buckets` /
  `list_photos_by_month`).
- ✅ **Drag-and-drop import** — drop a folder anywhere on the window to import it.
- ⬜ **UI polish** — skeleton loading, transitions, richer context menus,
  notifications, search suggestions.

### Phase B — Unified AI Search platform ✅
The search engine now ranks across signals: CLIP similarity blended with
**favorites** and **recency**, with structured **filters** (favorite / date /
person) and **person-name auto-detection** (faces × CLIP). Favorites are a real
user signal (♥ in the viewer). OCR/object labels plug into the same
candidate → filter → rank shape with no API change. See
[AI_PIPELINE.md](AI_PIPELINE.md).

### Signals feeding the unified search
- ✅ **CLIP** semantic embeddings
- ✅ **Faces** (person-name auto-filter)
- ✅ **Favorites** + **recency** ranking
- ✅ **OCR** text (RapidOCR, trigram-indexed, merged + boosted)
- ✅ **Similar image** (CLIP nearest-neighbour; right-click → Find similar)
- ⬜ **Objects** (YOLO/RT-DETR) → `photo_objects`, next

### Then per the recommended order
Object detection → duplicates → timeline → albums → map → video →
backup/export → installer.

### M6 — Timeline ✅
Google-Photos-style date browsing over the `taken_at` we already store. Shipped
as a Year → Month tree (with per-month counts) beside the same virtualized,
async grid the Photos tab uses; defaults to the most recent month. Undated
photos are simply absent (nothing to place them on). *Built:*
`db.list_timeline_buckets` / `list_photos_by_month`, `viewer/timeline_page.py`.

### M6 — Duplicate detection
Three-tier: exact (SHA-256, already stored) → **perceptual hash** (resized/
recompressed) → **embedding similarity** (edited/near-dupes, via pgvector).
*New:* `duplicate_detection/`, a `duplicates` table, a review UI.

### M7 — Metadata engine expansion + structured search
Add lens, ISO, exposure, focal length, and normalize into searchable fields.
Turn the top-bar search into structured filters (camera / lens / ISO / date /
favorite / folder). *New:* `metadata/` extractor, extra `photos` columns,
search grammar.

### M8 — Multi-resolution thumbnails + persistent job queue
Generate 128/256/512 tiers into `cache/thumbnails/<size>/`; a `jobs` table makes
indexing durable and resumable across restarts, with independent per-worker
progress. *New:* `cache/` tiers, `workers/` queue, `jobs` table.

### M9 — Smart albums + favorites/tags
Auto-albums (e.g. by person, place, time cluster, "night", "drone") + manual
albums, favorites, tags. *New:* `albums/`, tables `albums`, `photo_album`,
`tags`, `favorites`.

### M10 — Semantic (AI) search with CLIP
Local CLIP embeddings into the existing `photos.clip_embedding vector(768)`;
natural-language search ("red car", "mountain", "dog") via vector search. *New:*
`search/` + CLIP model (local), reuse pgvector.

### M11 — OCR
Extract text into the existing `photos.ocr_text`; make it searchable
("passport", "certificate"). *New:* `ocr/` (local OCR engine).

### M12 — Object detection
Detect objects/scenes; searchable tags. *New:* `objects/` + `object_detections`
table.

Cross-cutting, folded in as we go: face **quality check** + alignment metadata
(M6-ish), per-area log files, memory/disk cache tuning for the 100k/60fps
targets, and the remaining docs (AI_PIPELINE, SYSTEM_DESIGN, UI_GUIDE,
PERFORMANCE, TEST_PLAN, SECURITY, CHANGELOG, DECISIONS, CONTRIBUTING).

---

## Performance targets (v1.0)

| Metric | Target |
|--------|--------|
| Launch (100k photos) | < 3 s |
| Gallery scroll | ~60 FPS |
| Thumbnail fetch (cached) | < 20 ms |
| Face detection | GPU (CPU fallback) |
| Structured DB search | < 100 ms |

Current design already supports these directionally (paging, async thumbs,
indexes, ivfflat); M8 (tiered thumbnails + job queue) and targeted profiling
close the gap and let us measure them.

---

## Open architectural decision: directory layout

The proposed v1.0 tree nests everything under `app/` (`app/gui/...`,
`app/faces/...`, etc.). Trade-off:

- **Restructure now:** matches a large commercial layout, but is a big-bang move
  that rewrites every import for **zero user-facing value** and churns history.
- **Keep the current flat packages** (`scanner/`, `faces/`, `viewer/`, …) and
  add new modules alongside; split the UI internally (`viewer/pages/`,
  `viewer/widgets/`) as it grows.

**Recommendation:** keep flat for now and refactor to `app/` only when the tree
actually hurts — decided with the user, not pre-emptively.

---

## Documentation to add on the way to v1.0

`AI_PIPELINE.md`, `SYSTEM_DESIGN.md`, `UI_GUIDE.md`, `PERFORMANCE.md`,
`TEST_PLAN.md`, `SECURITY.md`, `CHANGELOG.md`, `DECISIONS.md` (ADRs),
`CONTRIBUTING.md`, `API.md` — added alongside the milestone that makes each one
meaningful, not all up front.
