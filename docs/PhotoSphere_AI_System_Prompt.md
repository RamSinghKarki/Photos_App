# PhotoSphere AI — Master Build Prompt

> This document is the single, authoritative instruction set for building **PhotoSphere AI**.
> Feed it to the assistant at the start of every working session. It defines the vision,
> the non-negotiable constraints, the architecture rules, and the definition of "done" for
> every module. When any instruction here conflicts with a suggestion made later in a
> session, **this document wins** unless I explicitly override it.

---

## 0. Role & Operating Context

You are helping me build **PhotoSphere AI**, a fully offline, AI-powered photo management
application for Windows.

Environment you can assume:
- **OS:** Windows
- **Language:** Python 3.12
- **GPU:** available for local inference (CUDA); CPU fallback must still work
- **Database:** PostgreSQL with the `pgvector` extension
- **Face model:** InsightFace
- **Development style:** incremental, one module at a time, in a fixed module order

Everything the application does runs **100% locally**. No user data ever leaves the machine.

### Technology Stack (fixed — do not substitute)

| Component   | Language / Framework      | Reason                                                                         |
| ----------- | ------------------------- | ------------------------------------------------------------------------------ |
| AI Engine   | **Python 3.12**           | Best ecosystem for computer vision — InsightFace, OpenCV, PyTorch, ONNX Runtime |
| Backend API | **Python (FastAPI)**      | Easy integration with AI models and PostgreSQL                                 |
| Desktop UI  | **Python (PySide6 / Qt)** | Native desktop application, no browser dependency, excellent image handling    |
| Database    | **PostgreSQL + pgvector** | Stores metadata and face embeddings locally                                    |
| Frontend    | **Qt Widgets or QML**     | Professional desktop UI without needing a web stack                            |
| SQL         | SQL                       | Database queries and migrations                                                |

Do not introduce a different UI toolkit, a web frontend, or a different backend framework
unless I explicitly ask. This is a **native desktop app**, not a web app.

---

## 1. Project Vision

**Project Name:** PhotoSphere AI

**Vision:**

Build the best fully offline AI-powered photo management application for Windows.

The application should feel similar to Google Photos in speed and ease of use while keeping
100% of the user's data on the local machine.

This is **not** just a face sorter. Face recognition is **Version 1**.

The architecture should allow future modules without major rewrites, including:

- Timeline
- Albums
- Favorites
- Similar Photos
- Semantic Search
- OCR
- Object Detection
- Video Support
- Duplicate Detection
- AI Captions

Even if these are not implemented yet, **avoid designs that make them difficult later**.

Face sorting is simply the first major capability. Design the database and modules so that
future features — semantic search, OCR, duplicates, albums, timeline — can be added **without
redesigning the foundation**, but do not implement them prematurely.

---

## 2. Architecture Rules

Keep the architecture simple.

- Do **NOT** rewrite previous modules unless there is a genuine bug.
- Every new module must **integrate** with previous modules instead of replacing them.
- Never create duplicate functionality.
- Every module must remain **backwards compatible**.
- Avoid unnecessary abstractions.
- Prefer boring, readable code.

---

## 3. Project Structure

```
Photo_AI/
    config/
    database/
    models/
    scanner/
    faces/
    clustering/
    viewer/
    utils/
    storage/
    logs/
    tests/
    data/
        thumbnails/
        face_crops/
    scripts/
    docs/
```

**Never change this structure unless I explicitly ask.** Do not invent new top-level folders
between sessions. If you believe a new folder is genuinely needed, stop and ask first.

---

## 4. Logging Rules

Every module must use Python's `logging` module.

Write logs to **both**:
- `logs/photosphere.log`
- the console

Errors must never disappear silently.

---

## 5. Error Handling

- Never crash because of one bad image.
- Skip unreadable files.
- Continue processing.
- Write detailed logs for every skip and error.
- Always show a processing summary at the end of a run.

Example summary:

```
Processed:   2405
Skipped:       13
Duplicates:    52
Errors:         4
```

---

## 6. Database Rules

- The PostgreSQL database is the **single source of truth**.
- Never duplicate metadata elsewhere.
- Every change to the database must go through clearly named helper functions rather than
  inline SQL scattered throughout the code.
- Use transactions where appropriate.
- Always create indexes for columns that will be searched frequently.

---

## 7. Performance Rules

The application must eventually support:
- 10,000 photos
- 100,000 photos
- 500,000 photos

Rules:
- Avoid loading all images into RAM.
- Process photos one at a time or in configurable batches.
- Prefer generators over large lists.
- Reuse existing data whenever possible.

Google Photos-level performance does not happen accidentally — design for scale from day one.

---

## 8. Face Recognition Rules

- Always **normalize embeddings** before similarity comparisons.
- Store the **raw embedding** exactly as produced by InsightFace.
- Never regenerate embeddings if one already exists, unless I explicitly request reprocessing.
- The database must be designed so that **one photo can contain multiple faces**.

---

## 9. Future Search Compatibility

The `photos` table (and related schema) must be designed so future modules can attach:
- OCR text
- CLIP embedding
- Object detections
- AI caption
- GPS metadata

…**without changing the existing schema** (use related tables / nullable columns / extension
tables rather than requiring destructive migrations later).

---

## 10. Thumbnail Rules

Google Photos is fast because it never loads originals while browsing.

- The application will generate thumbnails.
- Do **not** display original images directly inside the gallery.
- Original files are only opened when the user requests full resolution.

---

## 11. Image Cache

Create a cache folder for generated artifacts:
- Thumbnails
- Face crops
- Temporary previews

These live in the cache/`data/` area. **Never store temporary files beside the user's
originals.**

---

## 12. Code Style

- Python 3.12
- PEP 8
- Type hints on all functions
- Docstrings on all public functions/classes
- Functions under ~50 lines when practical
- Meaningful variable names
- Avoid deep nesting where possible
- Comment **WHY**, not **WHAT**

---

## 13. AI Rules

All AI inference must be completely local.

**Never use:**
- OpenAI API
- Google Vision
- Azure AI
- AWS Rekognition
- HuggingFace Inference API
- Roboflow API

Everything must run on the **local GPU or CPU**.

---

## 14. UI Rules

Even though the Viewer is a later module, follow these rules when it arrives:

- Minimal, fast, responsive UI
- Dark mode
- Keyboard friendly
- Built with **PySide6 / Qt** (Qt Widgets or QML) — a **native desktop application, no browser
  dependency and no web stack**
- The UI is genuine desktop software, not a website styled to look like one
- Never load original full-resolution images into the gallery grid — use thumbnails (see §10)
  so scrolling stays fast even at 100k+ photos

---

## 15. Testing Rules

After every module, provide:
- How to run
- Expected output
- Common errors
- How to verify correctness
- How to undo changes if something went wrong

---

## 16. Documentation

Every completed module must include:
- README update
- Database changes
- New folders created
- Future TODOs
- Known limitations

---

## 17. Version Control

At the end of every module, suggest a Git commit message.

Example:

```
feat(scanner): migrate scanner from SQLite to PostgreSQL
```

---

## 18. Quality Bar (Most Important)

- **Never** generate placeholder code.
- **Never** generate pseudocode.
- **Never** leave TODO comments instead of implementing required functionality.
- If a module is incomplete because you need a decision from me, **stop immediately and ask
  the question** instead of guessing.
- Every module must be **production-quality and fully runnable** before moving to the next.

---

## Definition of Done (per module)

A module is only "done" when **all** of the following are true:

1. It runs end-to-end on real input without crashing.
2. It integrates with — and does not break — previous modules.
3. It logs to both `logs/photosphere.log` and the console.
4. Bad/unreadable files are skipped, logged, and summarized (not fatal).
5. All database access goes through named helper functions; needed indexes exist.
6. It respects the fixed project structure.
7. Testing notes are provided (run / expected output / verify / undo).
8. Documentation is updated (README, schema changes, TODOs, limitations).
9. A suggested Git commit message is included.
10. There is **no** placeholder code, pseudocode, or stray TODO left in place of real logic.
