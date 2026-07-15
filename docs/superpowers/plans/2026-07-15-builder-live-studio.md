# Builder Live Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle and restructure `/-/assignments/new` into a two-column live-preview studio without changing any server contract.

**Architecture:** Presentation-layer pass on three files (template, builder.js, builder.css) guided by `docs/superpowers/specs/2026-07-15-builder-live-studio-design.md`. The definition JSON shape, routes, and server validation are untouched; a new structural test locks the template's contract ids. Every stage is screenshot-verified via an authenticated local capture before its pushed checkpoint commit.

**Tech Stack:** Jinja template + vanilla JS/CSS (dependency-free), pytest for structural tests, headless Chrome for verification.

## Global Constraints

- Read the spec first: `docs/superpowers/specs/2026-07-15-builder-live-studio-design.md`. It is the design authority.
- NO changes to: definition JSON shape, any route or POST param, views.py behavior, schema/creator/registry/render modules, the generated app template.
- Contract invariants that must survive: `#assignment-form`, hidden `#definition-json` (name="definition"), `#assignment-name`, `#assignment-slug`, `#assignment-instructions`, `#tasks-csv` (name="tasks_csv"), palette buttons carry `data-type` (inputs) / `data-kind` (header/paragraph), mode value still one of `form|tasks` feeding buildDefinition() unchanged.
- Visual language: the CSS variable palette from `apps/census.html` (`--ink #1a1a2e, --ink-mid #4a4a6a, --ink-soft #8888aa, --paper #f7f7fb, --rule #dddde8, --accent #3b5bdb, --accent-dk #2f4ac5, --ok #2f9e44, --warn #e67700, --radius 6px`), applied inside the content area only (don't fight datasette's chrome).
- All 38 existing tests stay green after every task: `.venv/bin/pytest plugins/datasette-assignments/tests/ tests/ -q`
- Each task ends with a pushed commit (these are the user-requested GitHub checkpoints). Fallback tag `v0.1.0-working` already exists.
- Screenshot verification procedure (used by Tasks 1-3; controller runs it at each gate too):

```bash
# One-time per session: start stack + login (idempotent to re-run)
cd /Users/morisy/Documents/Code/datasette_assignments
sqlite3 /tmp/ui_assignments_data.db "VACUUM;" 2>/dev/null || true
cp -f census.db /tmp/ui_census.db; cp -f internal.db /tmp/ui_internal.db
export DATASETTE_ROOT_PASSWORD_HASH=$(.venv/bin/python -c "from datasette_auth_passwords.utils import hash_password; print(hash_password('localdev'))")
pkill -f "datasette serve /tmp/ui_census" 2>/dev/null; nohup .venv/bin/datasette serve /tmp/ui_census.db /tmp/ui_assignments_data.db --internal /tmp/ui_internal.db -c datasette.yaml --secret uidev -p 8009 > /tmp/ui_datasette.log 2>&1 & sleep 3
CSRF=$(curl -s -c /tmp/uicj.txt http://127.0.0.1:8009/-/login | grep -o 'name="csrftoken" value="[^"]*"' | sed 's/.*value="//;s/"//')
curl -s -b /tmp/uicj.txt -c /tmp/uicj.txt -o /dev/null -X POST http://127.0.0.1:8009/-/login -d "username=root&password=localdev&csrftoken=$CSRF"
# Capture (repeat after each change; server restart needed only for python/template changes — static files reload per request):
SC=/private/tmp/claude-501/-Users-morisy-Documents-Code-datasette-assignments/fb0b3728-21a2-4476-a86f-8859a9d0d0c6/scratchpad
curl -s -b /tmp/uicj.txt http://127.0.0.1:8009/-/assignments/new | sed 's|<head>|<head><base href="http://127.0.0.1:8009/">|' > $SC/wizard_check.html
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu --screenshot=$SC/wizard_check.png --window-size=1400,1600 --virtual-time-budget=8000 "file://$SC/wizard_check.html" 2>/dev/null
```
  Note: the `<base>` trick means RELATIVE ajax calls in the captured page hit the live server anonymously; the live-preview fetch (Task 3) will 403 in captures — the "preview paused" state showing in a capture is expected there; verify the live preview itself by exercising the endpoint with curl and by DOM-dumping with cookies via a Chrome `--user-data-dir` profile is NOT available — instead verify preview wiring with the structural test + a manual note for the controller's authenticated check.
- Interactive states (mode cards selected, fields added) are verified by appending an injection script before `</body>` of the captured HTML that drives the real UI (click palette buttons, set mode) after DOMContentLoaded, then screenshotting.

---

### Task 1: Studio layout — template + CSS restructure

**Files:**
- Modify: `plugins/datasette-assignments/datasette_assignments/templates/assignments_new.html`
- Modify: `plugins/datasette-assignments/datasette_assignments/static/builder.css` (full rewrite expected)
- Modify: `plugins/datasette-assignments/datasette_assignments/static/builder.js` (only where markup changes force it: palette selector, mode input reading)
- Test: `plugins/datasette-assignments/tests/test_views_template.py` (new)

**Interfaces:**
- Produces: the new DOM structure Tasks 2-3 build on: `.studio` grid wrapping `.studio-builder` (left) and `.studio-preview` (right, contains `#preview-frame` iframe + `#preview-note` div); mode as two radio cards `input[type=radio][name=mode]` values `form|tasks` inside `label.mode-card`; `details#advanced` containing slug + `#rpt-label`; palette as `.palette` with three labeled groups (`.palette-group` h4s: Questions / Choices / Layout), buttons keep `data-type`/`data-kind`; `#fields-empty` dashed empty-state div; `#tasks-section` wrapper for CSV + `#task-title-col` and `#task-image-col` selects (Task 2 populates them).

- [ ] **Step 1: Write the failing structural test** `tests/test_views_template.py`:

```python
import pytest
import sqlite3
from datasette.app import Datasette


async def new_page_html(tmp_path):
    db_path = str(tmp_path / "assignments_data.db")
    sqlite3.connect(db_path).close()
    ds = Datasette([db_path])
    await ds.invoke_startup()
    cookies = {"ds_actor": ds.client.actor_cookie({"id": "root"})}
    r = await ds.client.get("/-/assignments/new", cookies=cookies)
    assert r.status_code == 200
    return r.text


@pytest.mark.asyncio
async def test_builder_contract_ids_survive_restyle(tmp_path):
    html = await new_page_html(tmp_path)
    for needle in [
        'id="assignment-form"', 'id="definition-json"', 'name="definition"',
        'id="assignment-name"', 'id="assignment-slug"',
        'id="assignment-instructions"', 'name="tasks_csv"',
        'data-type="text"', 'data-type="select"', 'data-kind="header"',
    ]:
        assert needle in html, needle


@pytest.mark.asyncio
async def test_builder_studio_structure(tmp_path):
    html = await new_page_html(tmp_path)
    for needle in [
        'class="studio', 'studio-builder', 'studio-preview',
        'id="preview-frame"', 'id="preview-note"',
        'type="radio" name="mode"', 'id="advanced"',
        'id="fields-empty"', 'palette-group',
        'id="task-title-col"', 'id="task-image-col"',
    ]:
        assert needle in html, needle
    assert 'id="preview-btn"' not in html  # manual preview button removed
```

- [ ] **Step 2: Run to verify the studio-structure test fails** (contract test should already pass).
- [ ] **Step 3: Rebuild the template and CSS per the spec's Layout/Basics/palette sections; adjust builder.js minimally** (read mode from `document.querySelector('input[name=mode]:checked').value`; palette listener attaches to `.palette`; remove the Preview button handler; keep everything else working). Follow the spec's visual language; styled inputs/buttons/cards; sticky `.studio-preview` (`position: sticky; top: 1rem`); responsive stack under 980px.
- [ ] **Step 4: Full test run green; screenshot per the Global procedure (default state + injected state: tasks mode selected, one text + one select field added). Layout must visibly match the approved mockup's structure.**
- [ ] **Step 5: Commit + push:** `git add plugins/ && git commit -m "feat(plugin): studio layout for builder — two-column, mode cards, grouped palette" && git push`

---

### Task 2: Interaction behavior

**Files:**
- Modify: `plugins/datasette-assignments/datasette_assignments/static/builder.js`
- Modify: `plugins/datasette-assignments/tests/test_views_template.py` (append any server-visible assertions only if needed)

**Interfaces:**
- Consumes Task 1's DOM. Produces behavior Task 3 hooks into: a single `notifyChanged()` function called on EVERY definition-affecting change (field edits, mode change, name/slug/instructions input, CSV input, option edits, reorder/remove) — Task 3 subscribes its debounced preview render to it.

Behaviors (from spec): mode-card selection toggles `#tasks-section` and the advanced responses-per-task row; typing the name updates `#assignment-slug` placeholder live via the existing client slugify; pasting/typing CSV parses the first line and populates `#task-title-col` / `#task-image-col` selects (preserving a previously chosen value when still present; image col has a "(none)" first option; both feed buildDefinition() as task_title_column/task_image_column — note: buildDefinition already derives task_columns from the CSV header, extend it to read these two selects); `#fields-empty` shows only when fields array is empty; field cards get collapse-free full rendering as today but with the new styles from Task 1.

- [ ] **Step 1: Implement the behaviors** (this is JS-only; the structural test suite plus manual injection screenshots are the verification — write the code, no placeholder steps).
- [ ] **Step 2: Full test run green; injected-state screenshots:** (a) tasks mode with CSV pasted (`city,state\nBoston,MA`) showing populated column dropdowns; (b) empty-state visible with zero fields; (c) two fields added, one select with two options.
- [ ] **Step 3: Commit + push:** `git commit -m "feat(plugin): builder interactions — live slug, CSV column pickers, empty state" && git push`

---

### Task 3: Live preview

**Files:**
- Modify: `plugins/datasette-assignments/datasette_assignments/static/builder.js`

Behavior (from spec): debounce 600ms after any `notifyChanged()`; POST the current definition to the existing preview endpoint (same fetch the old Preview button used, including csrftoken form field); on 200, set `#preview-frame.srcdoc` and clear `#preview-note`; on 400/error, KEEP the last srcdoc and set `#preview-note` to `Preview paused: <first line of response text>`; never clear a good preview on failure; fire one initial render on page load. Guard against out-of-order responses (a simple request counter — apply only the latest).

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Full test run green. Verify the endpoint flow with curl (authenticated POST /-/assignments/preview with a valid + an invalid definition → 200 HTML / 400 text). Screenshot: captured page shows the preview pane with the paused note (expected anonymous 403 in capture mode — confirms the note path renders); controller does the authenticated visual check at the gate.**
- [ ] **Step 3: Commit + push:** `git commit -m "feat(plugin): live auto-updating preview pane" && git push`

---

### Task 4: Verify, deploy, document

- [ ] **Step 1:** Full suite (`38 + new structural tests` green). Authenticated end-to-end walkthrough on the local stack via curl: create a tasks-mode assignment through the restyled form POST (proves serialization unchanged), verify redirect + artifacts, then clean up that test assignment via its delete endpoint.
- [ ] **Step 2:** `fly deploy --ha=false --app records-census-demo`; production smoke: login → /-/assignments/new 200 → the studio renders (capture screenshot of production page authenticated via cookie-jar curl + base-href trick); existing assignments unaffected (progress_demo_feedback still 200 anon).
- [ ] **Step 3:** Update `plugins/datasette-assignments/README.md` only if it describes the old wizard flow in ways now wrong (e.g. mentions a Preview button). One screenshot `docs/images/builder-studio.png` (production capture) referenced from the plugin README.
- [ ] **Step 4:** Commit + push: `git commit -m "docs: builder studio screenshot + README touch-up; deployed"`

## Self-Review Notes

- Spec coverage: layout/preview → Tasks 1+3; basics/mode cards/advanced/CSV pickers → Tasks 1+2; palette/empty state/field-card styling → Task 1 (+2 behavior); contract invariants → Task 1 test; checkpoints → per-task pushed commits; deploy+screenshots → Task 4.
- Placeholders: Tasks 2-3 carry behavior contracts instead of full JS listings — deliberate for a visual pass where the reference implementation (existing builder.js) is in-repo and structural tests + screenshot gates enforce outcomes.
- Type consistency: `notifyChanged()` produced by Task 2, consumed by Task 3; DOM ids produced by Task 1 consumed by 2-3 and the tests.
