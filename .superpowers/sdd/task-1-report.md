# Task 1 Report: Validator + Generated-App Interpolation (task-variables branch)

**Date:** 2026-07-15
**Branch:** task-variables

## TDD Evidence

**Steps 1–2 (Validator RED):** Appended 4 tests to `test_schema.py`.
- `test_task_variables_valid_tokens_pass` — passed immediately (correct: valid tokens should not raise)
- `test_task_variables_unknown_token_lists_columns` — FAILED (no raise)
- `test_task_variables_rejected_in_form_mode` — FAILED (no raise)
- `test_task_variables_checked_in_header_blocks` — FAILED (no raise)
Result: 3 RED, 1 GREEN.

**Steps 3–4 (Validator GREEN):** Added `TOKEN_RE` constant and surface-scan token-validation loop in `validate_definition`. All 4 validator tests GREEN.

**Steps 5–6 (Render RED):** Appended 2 tests to `test_render.py`. Both FAILED RED:
- `test_interp_machinery_present_tasks_mode_only` — `function interp(` absent
- `test_interp_applies_before_escape` — `esc(interp(` absent

**Steps 7–8 (Render GREEN):** Modified `app_template.html` with tasks-mode Jinja branches for `interp()` function and `renderField`/`buildFormHtml`. Both tests GREEN.

**Full suite:** 103 passed (97 prior + 6 new).

## E2E Escaping Proof

Hostile task value: `'<img src=x onerror=alert(1)>city'`

Applied `esc(interp("Visit {{city}}", task))`:
- label → `'Visit &lt;img src=x onerror=alert(1)&gt;city'`
- help  → `'About &lt;img src=x onerror=alert(1)&gt;city'`
- instructions → `'Review &lt;img src=x onerror=alert(1)&gt;city'`

No raw `<img` in any surface. `<` → `&lt;`, `>` → `&gt;`. XSS blocked. `interp(esc(` not present in HTML (correct order enforced).

## Files Changed

- `plugins/datasette-assignments/datasette_assignments/schema.py` — added `TOKEN_RE`; token-validation loop in `validate_definition`
- `plugins/datasette-assignments/datasette_assignments/templates/app_template.html` — tasks-mode `interp()` + split `renderField`/`buildFormHtml` per Jinja mode branch; `renderTask` passes task to `buildFormHtml(task)` and uses `esc(interp(..., task))` for instructions
- `plugins/datasette-assignments/tests/test_schema.py` — 4 new task-variable validator tests
- `plugins/datasette-assignments/tests/test_render.py` — 2 new interp machinery tests

## make_defn Adaptation

`make_defn` kwargs (`slug`, `mode`, `task_columns`, `task_title_column`, `instructions`, `fields`) match the brief exactly. No adaptation required.

## Self-Review

- `TOKEN_RE` is exactly `\{\{\s*([a-z][a-z0-9_]*)\s*\}\}` per spec
- All four surfaces checked: instructions, label, help, header/paragraph text
- Errors accumulate (no early raise in token loop)
- `esc(interp(...))` order enforced; `interp(esc(...))` never emitted
- Form mode rendering unchanged — no `interp` emitted, no behavioral change
- Per-task form re-render: `buildFormHtml(task)` inside `renderTask(task)` — each task rebuilds form with interpolated values
- No concerns.
