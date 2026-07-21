# PhotoSphere AI — Plugin Architecture

The AI ingestion pipeline is built from **plugins**. Import / Re-index scans the
folder, then a `PluginManager` runs each enrichment stage. Adding a capability
(object detection, video analysis, duplicate detection, a new embedding model)
means writing **one plugin and registering it** — the pipeline worker, UI, and
search don't change.

## The contract

```python
# pipeline/plugins.py
class Plugin(Protocol):
    name: str        # stable id, e.g. "faces"
    title: str       # UI step label, e.g. "Detecting faces"
    ai: bool         # needs an AI model? (gated by run_ai)

    def is_available(self) -> bool:       # deps/model present?
        ...
    def run(self, on_progress) -> str:    # process pending photos; return a summary
        ...
```

- **`is_available`** lets a plugin degrade gracefully — if its model isn't
  installed the stage is skipped, not failed.
- **`run`** does the work by calling an existing processor (a plugin *wraps* a
  processor, it doesn't re-implement it), threading `on_progress` through for the
  progress bar / ETA and cancellation.
- Everything stays **incremental** (each processor only touches photos that
  still need it), **batched**, and **cancel-safe** — the plugin layer adds no
  new state.

## The default pipeline

`pipeline/manager.default_manager()` registers the stages in order:

```
thumbnails → faces → people → clip → ocr
```

`PluginManager.run(run_ai, on_step, on_progress)`:
- skips `ai=True` plugins when `run_ai` is False,
- skips unavailable plugins (noting them in the summary),
- calls `on_step(title)` and `on_progress(done, total)` as it goes,
- returns the per-stage summary fragments.

## Adding a plugin (worked example: object detection)

1. Write `objects/processor.py` (incremental, batched, cancel-safe — model it on
   `ocr/processor.py`) and an `ObjectBackend` behind an interface if it needs a
   model.
2. Add an `ObjectPlugin(_BackendPlugin)` in `pipeline/plugins.py`:
   ```python
   class ObjectPlugin(_BackendPlugin):
       name, title, ai = "objects", "Detecting objects", True
       def __init__(self, factory=None):
           super().__init__(factory, default_object_backend)
       def run(self, on_progress):
           from objects.processor import detect_objects
           s = detect_objects(self._get(), on_progress=on_progress)
           return f"+{s.labels} objects"
   ```
3. Register it in `default_manager()`.
4. Feed search: add a `search_photos_by_object` DB helper and merge it in
   `SearchEngine.search` (same candidate → filter → rank shape).

Steps 1–3 make it run in Import/Re-index; step 4 makes it searchable. No changes
to the worker, the UI, or existing plugins.

See [AI_PIPELINE.md](AI_PIPELINE.md) for the pipeline internals and
[DEVELOPMENT.md](DEVELOPMENT.md) for conventions.
