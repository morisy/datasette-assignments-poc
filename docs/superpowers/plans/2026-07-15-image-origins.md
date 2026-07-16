# Image Origins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Image origins auto-opt-in when admin-approved, fail with actionable errors when not, at create and append time; builder shows origin approval status; demo allow-lists the three agreed hosts.

**Architecture:** `extract_image_origins(defn, rows) -> set[str]` in schema.py (pure); enforcement in `creator.create_assignment` (raises `CreationError`) and the add-tasks handler (400); opt-in via the `csp_origins` params of `create_stored_app`/`update_stored_app`; allow-list read from `datasette.plugin_config("datasette-apps")`. Builder indicator driven by `window.__allowedCspOrigins`.

**Tech Stack:** unchanged.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-15-image-origins-design.md` — read first. Error message wording per spec, verbatim shape.
- Branch `csp-origins` from main; pushed commit per task; suite green (103 at start); REAL counts reported (run, don't estimate).
- No subagent spawning; production = controller-run deploy only, never touched by implementers.
- Origin normalization: `urllib.parse.urlsplit`, `f"{scheme}://{netloc}".lower()`; skip non-`https?://` values; reject `http://` origins with "image hosts must use https".
- Reference files: `datasette_assignments/schema.py`, `creator.py` (_create_app), `views.py` (assignments_add_tasks), `static/builder.js` (initCsvPicker), datasette-apps `registry.py` (`get_csp_origins`, `update_stored_app` kwargs, `normalize_connect_origin`).

---

### Task 1: Extraction + create/append enforcement (TDD)

**Files:** `schema.py`, `creator.py`, `views.py`; tests appended to `tests/test_creator.py`, `tests/test_append_tasks.py`, `tests/test_schema.py`.

**Interfaces produced:** `extract_image_origins(defn, rows) -> set[str]` (raises `DefinitionError` on http origins); `creator.create_assignment` gains allow-list check + `csp_origins` pass-through to `_create_app` (whose signature gains `csp_origins=None`); add-tasks handler merges new approved origins via `update_stored_app`.

- [ ] Step 1: failing tests —
```python
# test_schema.py
def test_extract_image_origins():
    defn = validate_definition(make_defn(slug="pix", mode="tasks",
        task_columns=["city", "photo"], task_title_column="city",
        task_image_column="photo"))
    rows = [{"city": "A", "photo": "https://CDN.muckrock.com/a.jpg"},
            {"city": "B", "photo": "https://upload.wikimedia.org/b.png"},
            {"city": "C", "photo": "not a url"}]
    assert extract_image_origins(defn, rows) == {
        "https://cdn.muckrock.com", "https://upload.wikimedia.org"}
    with pytest.raises(DefinitionError):
        extract_image_origins(defn, [{"city": "D", "photo": "http://x.org/i.jpg"}])
    no_img = validate_definition(make_defn(slug="noimg", mode="tasks",
        task_columns=["city"], task_title_column="city"))
    assert extract_image_origins(no_img, [{"city": "E"}]) == set()

# test_creator.py — build Datasette with config={"plugins": {"datasette-apps":
#   {"allowed_csp_origins": ["https://cdn.muckrock.com"]}}}
async def test_create_opts_in_approved_image_origin(...):
    # create with photo column rows on cdn.muckrock.com →
    # AppsRegistry(ds).get_csp_origins(app_id) contains https://cdn.muckrock.com
async def test_create_rejects_unapproved_image_origin(...):
    # rows on https://evil.example → CreationError message contains
    # "evil.example" and "allowed_csp_origins" and the approved list; zero artifacts remain (reuse rollback assertions)

# test_append_tasks.py (same config fixture)
async def test_append_merges_new_approved_origin(...)
async def test_append_rejects_unapproved_origin(...)  # 400, no rows inserted
```
- [ ] Step 2: RED. Step 3: implement (extraction in schema.py; creator check before DDL creation so failure = no artifacts, pass origins through `_create_app`; add-tasks: extract on new rows, diff against `get_csp_origins(app_id)`, enforce, merge via `update_stored_app` passing current name/description/current-version html unchanged). Step 4: GREEN + full suite REAL count (103 + 7ish). Step 5: commit+push `feat(plugin): auto CSP opt-in for approved image origins; actionable errors otherwise`.

---

### Task 2: Builder indicator + demo config + docs + release prep

**Files:** `templates/assignments_new.html` (`window.__allowedCspOrigins` + `#image-origins-status` div), `static/builder.js`, `views.py` (pass allow-list to template), `datasette.yaml`, plugin README; needle test in `tests/test_views_template.py`.

- [ ] Step 1: needle `id="image-origins-status"` → RED → implement: on CSV parse or image-column change, extract origins from that column's values (same regex/URL logic in JS), render chips ✓ approved / ⚠ "needs admin approval" against `window.__allowedCspOrigins`; clear when no image column. GREEN + full suite REAL count.
- [ ] Step 2: `datasette.yaml` allowed_csp_origins → the three spec hosts. README "Images in tasks" section (recipe + the two-layer model + error meaning).
- [ ] Step 3: screenshot: tasks mode, CSV with a photo column mixing an approved + unapproved host, image column selected → chips show ✓ and ⚠ → `$SC/origins_chips.png` (exact path: /private/tmp/claude-501/-Users-morisy-Documents-Code-datasette-assignments/fb0b3728-21a2-4476-a86f-8859a9d0d0c6/scratchpad — copy it carefully, a prior agent typo'd it), ls proof, LOOK at it.
- [ ] Step 4: commit+push `feat(plugin): image-origin status chips; demo image hosts; docs`. Controller merges/deploys/tags v0.3.2.

## Self-Review Notes

Spec coverage: extraction/enforcement/opt-in/append → T1; indicator/config/docs → T2; tag → controller. Message wording pinned in spec. `_create_app(csp_origins=None)` signature consumed only by creator. Rollback-on-unapproved covered by reusing existing zero-artifact assertions (check happens pre-DDL so rollback is trivially satisfied — test asserts it anyway).
