# PhotoSphere AI — Self-Improving Recognition

The key design shift: PhotoSphere AI is not "AI run on photos," it is a **local
knowledge base about your collection that grows smarter from your actions**. The
models (InsightFace, CLIP) stay fixed; the knowledge built on top of them
improves. This stays 100% offline.

## Persistent person identity — recognition engine v2 (implemented)

The goal is not "recognize the same face" but **recognize the same *person*
despite viewpoint, facial hair, glasses, lighting, expression, age, and partial
occlusion** — the thing Google Photos does well. We do it the way they do: a
strong fixed embedding model (InsightFace) wrapped in a smart recognition system
that keeps a **diverse, evolving profile per person**, not a single average.

Each person carries a **representative gallery** (`person_embeddings`) — a
quality-gated, diverse set of embeddings covering their different appearances —
plus a centroid (`persons.centroid`) as a fast secondary signal and a per-person
**adaptive threshold** (`persons.adaptive_threshold`).

```mermaid
flowchart LR
    NF[New faces<br/>ungrouped] --> Q[Quality score<br/>det + resolution]
    Q --> M{best cosine vs<br/>each person's<br/>representatives ∪ centroid}
    M -- ">= person's<br/>adaptive threshold" --> A[Assign to person<br/>+ update centroid<br/>+ teach gallery]
    M -- "below" --> C[Cluster remaining<br/>into NEW people]
    A --> KB[(persons +<br/>person_embeddings)]
    C --> KB
    A -.re-curate.-> G[diverse reps +<br/>adaptive threshold]
```

Why this matters:

- **Multiple representatives, not one centroid.** A new face is scored by its
  **best** match across a person's stored appearances (front, profile, bearded,
  bespectacled, low-light…). Matching the closest *appearance* instead of a
  blurry average is what recognizes a person across big visual changes.
  (`clustering/gallery.select_representatives`, keeping a diverse set — near-
  duplicates are dropped, capped at `PHOTOSPHERE_PERSON_MAX_REPRESENTATIVES`.)
  *(Stage 1)*
- **Quality gates learning.** Every face gets a 0..1 quality score
  (`clustering/quality.face_quality`, from detector confidence + resolution; blur
  is a designed-in optional term). A tiny/low-confidence detection is shown but
  **never teaches** a profile — below `PHOTOSPHERE_FACE_QUALITY_STORE_MIN` it is
  ignored for learning. *(Stage 2)*
- **Multi-stage match.** Representatives **and** centroid are fused (best-of), so
  a strong match to any stored appearance *or* the average accepts. *(Stage 4)*
- **Adaptive per-person thresholds.** Each person's acceptance bar is derived
  from how *consistent* their gallery is (`clustering/gallery.adaptive_threshold`)
  — a tight identity demands a stricter match (fewer false accepts); a genuinely
  varied person gets a more permissive bar (so real variations still land) —
  clamped to `[PHOTOSPHERE_ADAPTIVE_THRESHOLD_MIN, …_MAX]`, falling back to the
  global `PHOTOSPHERE_FACE_MATCH_THRESHOLD` until there is enough evidence.
  *(Stage 11)*
- **Adaptive learning.** Each accepted face folds into the centroid *and* the
  gallery, then the diverse set + threshold are re-curated — so recognition
  improves as the library grows (20 → 500 photos of a person). *(Stage 6)*
- **Naming teaches the app; names are never destroyed.** Import / Re-index run
  the **incremental, name-preserving** update (`update_people`); existing people
  and their names are kept. A one-time **backfill** upgrades people grouped
  before the gallery existed with no reclustering. Destructive rebuild stays
  opt-in: `scripts.cluster_faces --rebuild`. *(Stage 6)*
- **Model-replaceable.** Nothing hard-codes Buffalo_L; the gallery is embedding-
  agnostic. A future face model (Buffalo_M, AdaFace, MagFace) drops in behind the
  same interface. *(Future model improvements)*

User corrections feed the loop: **rename** sets a name, **merge** reassigns faces
and **rebuilds the target's gallery** (re-curating representatives + threshold),
**delete** un-groups faces — all via `database/db.py` helpers; the next update
respects them.

- **Feedback memory — corrections stick.** On a person's page, select photos →
  **"Not <name>"**: the faces are detached *and* a durable **rejection** is
  recorded (`recognition_feedback`). Recognition consults these on every run, so
  a (face, person) the user rejected is **never re-assigned** — even though its
  embedding still matches. Emptying a person deletes the group (its rejections
  cascade away). Rejections are per-face, so correcting one photo never blocks a
  genuinely new photo of the same person. *(Stage 10)*
- **Learning is visible and steerable.** A person's page shows a **"Learned
  appearances"** strip — the actual representative crops the engine matches
  against, best-quality first, each labelled with its quality. Right-click a bad
  representative → **remove appearance**: it's dropped and remembered as a
  rejection, so you can see *and* correct what the system learned.
  (`viewer/appearance_strip.py`, `data.person_representatives` /
  `reject_representative`.) *(Stage 12)*
- **Active learning — ask only when unsure.** A face whose best match lands just
  *below* a person's threshold (within `PHOTOSPHERE_SUGGESTION_MARGIN`) is not
  dropped — it becomes a pending **"Is this <name>?"** suggestion
  (`recognition_suggestions`), shown as a Yes/No strip on the person's page.
  **Yes** assigns the face, teaches the gallery, and records a `confirm`; **No**
  records a `reject` (never re-offered). Uncertain cases become training signal
  instead of silent misses, and the app only interrupts when it's genuinely on
  the fence. *(Stage 9)*
- **Context fusion — where and when, not just the face.** When a face's match is
  near-miss, its **capture context** breaks the tie: a face taken the same day
  and at the same place (GPS) as a person's known photos gets a small, bounded
  boost (`PHOTOSPHERE_CONTEXT_BOOST`, up to ~0.06) that can lift it over the line.
  The boost applies **only** to faces already within `PHOTOSPHERE_CONTEXT_REACH`
  of the threshold, so context strengthens a genuine near-match but never invents
  one. Only strong, always-local signals are used (day + GPS); degenerate ones
  like "same import folder" are deliberately excluded. (`clustering/context.py`.)
  *(Stage 5)*

The self-improving recognition vision is now complete end-to-end: represent
(diverse gallery) → assess (quality) → match (best-of + adaptive threshold +
context) → adapt (fold back in) → correct (rejections) → show (appearances) →
ask (active learning). Models stay fixed and local; the knowledge grows.

- **Anti-fragmentation — one person, one profile.** Clustering can split an
  identity across appearances (frontal vs profile, beard vs clean-shaven,
  occlusions). Three defenses now run automatically: (1) a **person-merge scan**
  after every update compares persons by their galleries — obvious duplicates
  (both *unnamed*, similarity ≥ `PHOTOSPHERE_MERGE_AUTO`) are merged
  automatically; likely ones become **"Same person?"** questions on the People
  page (Merge / Not the same — a "no" is remembered forever, and *named* people
  are never auto-merged); (2) a young single-appearance gallery can no longer
  raise its threshold above the global bar and wall out its own other
  appearances (`PHOTOSPHERE_ADAPTIVE_STRICT_MIN_REPS`); (3) low-quality
  detections (occluded/blurry/tiny) may *join* people but can no longer *found*
  new ones. Merging invites naming; person cards also rename via right-click.
  (`clustering/merge_scan.py`, `viewer/merge_strip.py`.)

### Future refinements

- **Richer context**: co-occurring people ("seen with family") and event
  clustering, on top of the day/GPS fusion already in place.
- **Embedding versioning for faces**: as done for CLIP, to allow a face-model
  upgrade (Buffalo_M, AdaFace, MagFace) without losing names.
- **Personal classifier**: a lightweight per-library kNN/logistic head over
  embeddings as an alternative to centroid+gallery matching.

## The knowledge base

| Signal | Where | Status |
|--------|-------|--------|
| Faces + embeddings | `faces` | ✅ |
| Person profiles (centroids) | `persons.centroid` | ✅ |
| Representative galleries + adaptive thresholds | `person_embeddings`, `persons.adaptive_threshold` | ✅ |
| CLIP image embeddings | `clip_embeddings` (versioned by model) | ✅ |
| GPS / camera / time metadata | `photos` | ✅ |
| OCR text | `photos.ocr_text` (trigram-indexed) | ✅ |
| Favorites | `photos.is_favorite` (feeds search ranking) | ✅ |
| Recognition feedback (rejections) | `recognition_feedback` | ✅ |
| Object/scene labels | `photo_objects` | ⬜ planned |

## Roadmap of remaining "levels"

Built on the same principle (fixed models, growing knowledge):

- **L3 — Feedback history**: record accepted/rejected matches, manual merges/
  splits; bias future decisions.
- **L5 — Objects** (YOLO/RT-DETR, offline) → `photo_objects`, searchable.
- **L6 — OCR** (RapidOCR/PaddleOCR, offline) → `photos.ocr_text`, searchable.
- **L7 — Behavior ranking**: opens/favorites/recency blended into search ranking
  (the `SearchEngine.search(filters=…)` hook is already reserved).
- **L8 — Similar photos**: nearest-neighbour over `clip_embeddings` (index exists).
- **L9 — Hybrid recognition**: combine face + time + GPS + companions for
  confidence when the face signal alone is weak.
- **L11 — Active learning**: ask "Is this Ram?" only when confidence is
  borderline; each answer improves the profile.
- **L12 — Embedding versioning**: already done for CLIP (model+version); apply
  the same to face embeddings for model upgrades.
- **L13 — Personal classifier**: a lightweight kNN/logistic-regression head over
  embeddings per library (no GPU retraining) as an alternative to centroid match.

See [ROADMAP.md](ROADMAP.md) for milestone ordering and
[AI_PIPELINE.md](AI_PIPELINE.md) for the pipeline internals.
