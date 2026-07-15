# Task Variables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `{{column}}` tokens in assignment questions substitute per-task CSV values in generated apps, with validation, escaping, and a detected-columns affordance in the builder.

**Architecture:** A `TOKEN_RE`-based scan in `validate_definition` (tasks: unknown token → error listing columns; form: any token → error). The generated app re-renders the form per task and pipes the four text surfaces through `interp(text, task)` before `esc()`. The builder's CSV handler renders detected-column chips with a `{{token}}` usage hint.

**Tech Stack:** unchanged (plugin Python/Jinja/vanilla JS; pytest).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-15-task-variables-design.md` — read first.
- Token regex exactly: `\{\{\s*([a-z][a-z0-9_]*)\s*\}\}` (shared constant `TOKEN_RE` in schema.py; equivalent literal in the app JS).
- Interpolated surfaces exactly four: instructions, field label, field help, header/paragraph text. Interpolate THEN escape — hostile CSV values must render inert (test required).
- Branch `task-variables` from main; pushed commit per task; suite green throughout (97 at start); deploy + tag `v0.3.1` at the end.
- No subagent spawning by implementers; production access = final deploy + GET smoke only.
- Reference files: `plugins/datasette-assignments/datasette_assignments/schema.py` (validate_definition error-accumulation style), `templates/app_template.html` (renderField/renderTask/esc, per-task flow), `static/builder.js` (initCsvPicker debounce), `tests/test_schema.py` + `tests/test_render.py` patterns.

---

### Task 1: Validator + generated-app interpolation (TDD)

**Files:**
- Modify: `datasette_assignments/schema.py`, `templates/app_template.html`, `render.py` only if needed for test plumbing
- Test: `tests/test_schema.py`, `tests/test_render.py` (append)

**Interfaces:**
- Produces: `TOKEN_RE` module constant; validation errors of the forms `"unknown variable {{x}} in <surface> — available: city, state"` and `"variables like {{x}} only work in task-list assignments (found in <surface>)"`; app-side `interp(text, task)` applied in tasks mode to the four surfaces with per-task form re-render.

- [ ] **Step 1: Failing validator tests** (append to test_schema.py):

```python
def test_task_variables_valid_tokens_pass():
    d = make_defn(slug="vars", mode="tasks", task_columns=["city", "state"],
                  task_title_column="city",
                  instructions="Find {{ city }}'s page")
    d["fields"][0]["label"] = "What is {{city}}'s open government webpage?"
    validate_definition(d)  # no raise


def test_task_variables_unknown_token_lists_columns():
    d = make_defn(slug="vars", mode="tasks", task_columns=["city", "state"],
                  task_title_column="city")
    d["fields"][0]["label"] = "{{town}} portal?"
    with pytest.raises(DefinitionError) as e:
        validate_definition(d)
    msg = "; ".join(e.value.errors)
    assert "town" in msg and "city" in msg and "state" in msg


def test_task_variables_rejected_in_form_mode():
    d = make_defn(slug="vars")  # form mode
    d["fields"][0]["help"] = "about {{city}}"
    with pytest.raises(DefinitionError) as e:
        validate_definition(d)
    assert any("task-list" in m for m in e.value.errors)


def test_task_variables_checked_in_header_blocks():
    d = make_defn(slug="vars", mode="tasks", task_columns=["city"],
                  task_title_column="city",
                  fields=[{"kind": "header", "text": "About {{nope}}"},
                          {"kind": "input", "type": "text", "id": "a",
                           "label": "A", "help": "", "required": True,
                           "gallery": False, "missing_companion": False,
                           "options": []}])
    with pytest.raises(DefinitionError):
        validate_definition(d)
```

- [ ] **Step 2: RED.**
- [ ] **Step 3: Implement in validate_definition** — add near the top of schema.py: `TOKEN_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")`. In the validator, after fields are checked, collect `(surface_name, text)` pairs: `("instructions", d["instructions"])`, per input field `("label of <id>", label)` and `("help of <id>", help)`, per block `("<kind> block", text)`. For each token found: tasks mode + token not in task_columns → error `f"unknown variable {{{{{tok}}}}} in {surface} — available: {', '.join(task_columns)}"`; form mode → error `f"variables like {{{{{tok}}}}} only work in task-list assignments (found in {surface})"`. Accumulate, don't raise early.
- [ ] **Step 4: GREEN (validator).**
- [ ] **Step 5: Failing render tests** (append to test_render.py):

```python
def test_interp_machinery_present_tasks_mode_only():
    html = render_app_html(tasks_defn(), "assignments_data")
    assert "function interp(" in html
    form_html = render_app_html(validate_definition(make_defn(slug="tips")),
                                "assignments_data")
    assert "function interp(" not in form_html


def test_interp_applies_before_escape():
    # The composition esc(interp(...)) must appear for label rendering,
    # never interp(esc(...)) — hostile task values stay inert.
    html = render_app_html(tasks_defn(), "assignments_data")
    assert "esc(interp(" in html
    assert "interp(esc(" not in html
```

- [ ] **Step 6: RED.**
- [ ] **Step 7: Implement in app_template.html** (tasks-mode Jinja branch only): `function interp(text, task) { return String(text ?? "").replace(/\{\{\s*([a-z][a-z0-9_]*)\s*\}\}/g, function (m, col) { return task && task[col] !== undefined ? String(task[col]) : m; }); }` — currently the form is rendered once; move form rendering into the per-task path (tasks mode) so `renderTask(task)` rebuilds the form section with `esc(interp(label, task))`, `esc(interp(help, task))`, `esc(interp(text, task))` for blocks, and instructions likewise. Preserve entered values? NO — each task starts blank anyway (form resets per task today; verify and keep behavior). Form mode: rendering unchanged (no interp function emitted; use a Jinja conditional).
- [ ] **Step 8: GREEN + full suite** (`.venv/bin/pytest plugins/datasette-assignments/tests/ tests/ -q`, REAL count = 97 + 6).
- [ ] **Step 9: End-to-end escaping proof:** generate preview HTML for a tasks-mode defn whose label is `Visit {{city}}` and whose preview sample task value you override via injected stub to `<img src=x onerror=alert(1)>city`; dump-dom must show the value HTML-escaped in the label (no `<img` element inside the label node). Simplest: after generating preview HTML, inject a script that overrides the preview stub's task row before main runs, screenshot/dump-dom, grep. Record evidence.
- [ ] **Step 10: Commit + push:** `feat(plugin): {{column}} task variables in questions (validated, escaped)`

---

### Task 2: Builder affordance + docs + release

**Files:**
- Modify: `static/builder.js`, `templates/assignments_new.html` (hint copy + `#csv-detected` div), `plugins/datasette-assignments/README.md`, `TUTORIAL.md` (one-line mention in the adapting section if apt)
- Test: `tests/test_views_template.py` (append needle `id="csv-detected"`)

- [ ] **Step 1:** Failing structural needle → RED.
- [ ] **Step 2:** Implement: `#csv-detected` div under the CSV textarea (template); in builder.js's CSV parse handler, when headers parse: `Detected columns: ` + code chips (escaped) + ` — first row is treated as headers. Use {{<first>}} in your questions to insert each task's value.`; cleared when empty. Tighten section hint: "Paste CSV — the first row must be column headers; every other row becomes one task. Or upload a .csv file."
- [ ] **Step 3:** GREEN + full suite (REAL count). Screenshot: builder tasks mode with CSV pasted showing chips → `$SC/vars_chips.png`; confirm file exists (`ls -la`) and LOOK at it.
- [ ] **Step 4:** README: short "Task variables" section with the Boston/Chicago example; note tokens work in instructions/labels/help/blocks, tasks mode only.
- [ ] **Step 5:** Commit + push `feat(plugin): detected-columns hint + {{token}} affordance in builder; docs`.
- [ ] **Step 6:** Controller handles merge/deploy/tag (leave to controller; do not run fly).

## Self-Review Notes

- Spec coverage: validation → T1 (4 tests incl. whitespace + header block + form-mode); interp+escape order → T1 (structural + e2e proof); per-task re-render → T1 Step 7; chips + copy → T2; docs → T2; tag/deploy → controller after T2.
- Consistency: TOKEN_RE defined once in schema.py; JS literal matches; `#csv-detected` id shared between template, JS, and test needle.
