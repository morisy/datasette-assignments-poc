# Task 1 Report: Edit Live Assignments (Copy Edits Only) — v0.3 Wave

**Date:** 2026-07-15
**Branch:** v0-3-wave
**Commit:** 80da751

## What Was Implemented

### 1. `schema.py` — `merge_editable(stored, posted) -> dict`
- Whitelist merge accepting only editable properties: name, instructions, field labels, help text, header/paragraph text, adding options to select/checkbox_group
- Raises `DefinitionError` on structural changes: different mode, different slug, different field count, field id or type changes
- Existing options preserved at original indices; new options from post are appended

### 2. `registry.py` — `update_definition(datasette, slug, defn)`
- Standalone async function: `UPDATE assignments_registry SET definition=?, name=? WHERE slug=?`

### 3. `views.py` — `assignments_edit` GET/POST handler
- GET: Loads stored definition, detects hand-edits by comparing current app HTML to `render_app_html(stored_defn, db_name)`, renders template in edit mode
- POST: Calls `merge_editable`, `validate_definition`, `registry.update_definition`, regenerates HTML via `render_app_html`, updates app via `datasette_apps update_stored_app`
- Hand-edit guard: shows warning banner + requires `confirm_overwrite` checkbox when HTML differs
- Auth: uses `_require_owner_or_root` pattern

### 4. `__init__.py` — Route registration
- Added: `(r"^/-/assignments/(?P<slug>[a-z][a-z0-9_]{0,39})/edit$", views.assignments_edit)`

### 5. `templates/assignments_new.html` — Edit mode guards
- `{% if not edit_mode %}` wrappers around: mode radio cards, advanced/slug section, tasks CSV section, palette
- Edit mode: slug shown as static text (immutable), "Structure is locked" hint, "Save changes" + "Cancel" buttons
- Type + id rendered as static badge text (`TEXT · ID: ANSWER`)
- `window.__editMode = true` set in script block

### 6. `templates/assignments_manage.html` — Edit link
- Added "Edit assignment" link to manage-links bar

### 7. `static/builder.js` — `window.__editMode` locking
- No move/remove buttons in edit mode
- Type+id shown as static badge
- ID input hidden in edit mode (label only editable)
- Required/Gallery/companion checkboxes `disabled`
- Existing options `readOnly` with gray background; only new options get remove buttons
- Add-option button remains active

## TDD Evidence

### RED (before implementation)
```
ERROR plugins/datasette-assignments/tests/test_schema.py
ImportError: cannot import name 'merge_editable'
ERROR plugins/datasette-assignments/tests/test_edit.py
ImportError: ... (cascade)
2 errors during collection
```

### GREEN (after implementation)
```
................................................  [100%]
48 passed in 0.90s
```
- 34 original tests: all green
- 4 new `merge_editable` tests in `test_schema.py`: all green
- 10 new route/behavior tests in `test_edit.py`: all green

## Files Changed
- `plugins/datasette-assignments/datasette_assignments/schema.py` — added `merge_editable`
- `plugins/datasette-assignments/datasette_assignments/registry.py` — added `update_definition`
- `plugins/datasette-assignments/datasette_assignments/views.py` — added `assignments_edit`
- `plugins/datasette-assignments/datasette_assignments/__init__.py` — registered `/edit` route
- `plugins/datasette-assignments/datasette_assignments/templates/assignments_new.html` — edit mode guards
- `plugins/datasette-assignments/datasette_assignments/templates/assignments_manage.html` — "Edit assignment" link
- `plugins/datasette-assignments/datasette_assignments/static/builder.js` — `__editMode` locking
- `plugins/datasette-assignments/tests/test_schema.py` — 4 new `merge_editable` tests (import added)
- `plugins/datasette-assignments/tests/test_edit.py` — new file, 10 route tests

## Self-Review Findings
- `merge_editable` is the authoritative server-side guard; client-side JS locking is defense-in-depth
- Hand-edit detection and `update_stored_app` are best-effort (try/except) to not break edit page if datasette-apps unavailable
- Registry is always updated even if app HTML regeneration fails

## Screenshot
**Path:** `/private/tmp/claude-501/-Users-morisy-Documents-Code-datasette-assignments/fb0b3728-21a2-4476-a86f-8859a9d0d0c6/scratchpad/v03_edit.png`

**Verified:**
- "Edit Assignment" heading visible
- No palette buttons (structure locked)
- Field shows "TEXT · ID: ANSWER" as static badge
- Label + help text inputs editable
- Required/Gallery/Couldn't find checkboxes greyed/disabled
- Slug shown as `demo_survey (immutable)` — no editable slug field
- No mode radio cards
- "Save changes" + "Cancel" buttons present
- Preview pane present (shows "Preview paused: Failed to fetch" — expected for local file capture)

---

## Fix Round 1

**Date:** 2026-07-15
**Commit:** b2eecec
**Branch:** v0-3-wave (pushed)

### What changed per finding

**Finding 1 — Options prefix guard (TDD)**
- `tests/test_schema.py`: Added three verbatim tests from the brief:
  - `test_merge_editable_accepts_copy_changes` — confirms name/instructions/label/help all editable, structural fields unchanged
  - `test_merge_editable_rejects_structural_changes` — verifies mode change, slug change, field id rename, and field type change all raise DefinitionError
  - `test_merge_editable_options_append_only` — confirms append is fine, but rename/reorder/removal of existing options all raise DefinitionError
- `schema.py` `merge_editable` (lines 254-266): Changed options merge logic from "slice-and-append" to a prefix check: `if posted_opts[:len(stored_opts)] != stored_opts` → raises DefinitionError. Added a `if errors: raise DefinitionError(errors)` guard after the field merge loop so options errors actually propagate.

**Finding 2 — Hand-edit test scenario**
- `tests/test_edit.py`: Added `test_edit_hand_edit_warning_and_confirm_overwrite`. Test sequence:
  1. Creates assignment (which auto-creates app HTML via AppsRegistry)
  2. Retrieves app_id from registry
  3. Calls `apps_registry.update_stored_app(...)` with `"<html><body>HAND EDITED</body></html>"` to simulate a hand-edit
  4. GET asserts 200 and that warning keywords ("customized" / "hand" / "overwrite") appear in page
  5. POST without `confirm_overwrite` asserts status in (400, 200) and registry name is still unchanged
  6. POST with `confirm_overwrite=1` asserts 302 redirect, registry reflects new name, app HTML no longer contains "HAND EDITED"

**Finding 3 — Description truncation in views.py**
- `views.py` line ~200: Changed `validated.get("instructions", "")` to `(validated.get("instructions") or "")[:200]` in the `apps_registry.update_stored_app(...)` call. Matches the pattern already used in `creator.py` `_create_app`.

**Finding 4 — Strengthen status assertion**
- `tests/test_edit.py` line ~114: `assert r.status_code in (302, 200)` → `assert r.status_code == 302`

**Finding 5 — `__editMode` assertion on GET**
- `tests/test_edit.py` `test_edit_get_returns_200_for_owner`: Added `assert b"__editMode" in r.content`

**Finding 6 — Assert regenerated app HTML contains new label**
- `tests/test_edit.py` `test_edit_post_updates_name_and_label`: After confirming registry updated, retrieves current version from AppsRegistry and asserts `"Updated Label"` in the HTML.

### RED/GREEN evidence for Finding 1

**RED** (three new tests added, `test_merge_editable_options_append_only` failed):
```
FAILED plugins/datasette-assignments/tests/test_schema.py::test_merge_editable_options_append_only
E       Failed: DID NOT RAISE <class 'datasette_assignments.schema.DefinitionError'>
1 failed, 18 passed in 0.07s
```

**GREEN** (after prefix guard fix in schema.py):
```
...................
19 passed in 0.04s
```

### Test commands run and output tails

```
# Targeted (schema + edit):
.venv/bin/pytest plugins/datasette-assignments/tests/test_schema.py plugins/datasette-assignments/tests/test_edit.py -q
..............................                                           [100%]
30 passed in 0.46s

# Full suite:
.venv/bin/pytest plugins/datasette-assignments/tests/ tests/ -q
..........................................................               [100%]
58 passed in 0.99s
```
