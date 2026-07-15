# datasette-assignments Plugin (Phase 2) — Design

**Date:** 2026-07-14
**Status:** Approved by user (generator approach, two modes, privacy model, palette confirmed via Q&A + screenshot of MuckRock Assignments' builder)
**Builds on:** Phase 1 (`docs/superpowers/specs/2026-07-14-assignments-phase1-design.md`) — the shipped City Public Records Census demo at https://records-census-demo.fly.dev

## Goal

A pip-installable Datasette plugin, `datasette-assignments`, that gives signed-in users a WYSIWYG builder for Assignment-style crowdsourcing: they design a form (and optionally a task list), and the plugin **generates standard Datasette artifacts** — tables, a done-marking trigger, stored queries, and a real datasette-apps app. Remove the plugin and existing assignments keep running.

## Approach (decided)

**Generator, not interpreter.** The wizard collects a definition and emits concrete artifacts. The definition JSON is stored for provenance (leaves room for a later "regenerate" feature; not built in v1). Rejected alternatives: a runtime interpreter app (opaque, couples all assignments to one app, kills the "here's your app HTML, customize it" story) and a hybrid with regeneration UX (deferred — destructive-regeneration warnings are v2 polish).

## Two assignment modes

Wizard's first choice:

- **Task mode** — creator supplies a task list as pasted/uploaded CSV (first row = headers). Contributors work through tasks one at a time; each task collects `responses_per_task` independent answers (default 3) then leaves rotation via the phase-1 trigger pattern. Progress bar: "X of N tasks complete."
- **Form mode** — no CSV, no tasks table, no trigger. The app is the form; every submission appends one response row. Progress UI: "N contributions so far."

Task-mode wizard also asks: which CSV column is the task **title**, which extra columns display on the task card, and optionally which column holds an **image URL** (with an inline warning that the image's origin must be on the admin's `allowed_csp_origins` list, and the app must opt in — link NOTES.md).

## Field palette

Matches MuckRock Assignments' builder (per screenshot) plus two phase-1 additions:

| Type | Input | Notes |
|---|---|---|
| Text Field | single-line text | optional "couldn't find one" companion |
| Text Area | multi-line text | optional companion |
| Number | number input | |
| Date | date input | |
| Select | dropdown | creator-defined options |
| Checkbox Group | multi-select checkboxes | options + "Add Option"; stored as JSON array |
| Check Box | single checkbox | stored 0/1 |
| URL | url input | validated `https?://`; optional companion |
| Email | email input | regex-validated; optional companion |

Layout blocks (render, don't collect): **Header**, **Paragraph** — for explanatory text anywhere in the form.

Per input field: **Label**, **Help Text**, **Required**, **Gallery** (may-become-public flag), Options where applicable. The "couldn't find one" companion checkbox (URL/Email/Text types) writes a paired `<field>_missing` 0/1 column — flagged absence is data.

## Privacy model (responses private by default)

- Generated **responses tables are private**: readable by the assignment owner and root only. Enforced by the plugin via Datasette 1.0 permission hooks (dynamic, resource-scoped — same mechanism family datasette-apps uses).
- **Raw SQL (`execute-sql`) is denied on the assignments database** for non-root — raw SQL would bypass table-level permissions. Consequence: **generated apps use stored queries exclusively**, never `datasette.query()` raw SQL. Reads: `next_task_<slug>` (task-mode; excludes a comma-joined `:seen` id list via `instr()` matching) and `progress_<slug>` (aggregate counts only — never answer content). Write: `submit_<slug>`. Each is individually anonymous-allowed.
- **Per-response `is_public` column, default 0.** The owner's management page lists responses with a per-row public/private toggle (the "make these public" column). Toggle is a plugin-internal write, owner-or-root only.
- **Public view** per assignment: `a_<slug>_public`, selecting only Gallery-flagged fields of rows `WHERE is_public = 1`. Anonymous-readable; serves as the results/gallery page in plain Datasette.
- Tasks tables and public views are world-readable. The phase-1 census (designed public, pre-plugin) is untouched.
- **Verification item for the plan (not a blocker):** confirm the datasette-apps query bridge lets an anonymous actor invoke anonymous-allowed *stored* queries when `execute-sql` is denied on the database. Fallback if not: expose progress/next-task as public SQL views (aggregates only), which this design already half-uses.

## What "Create" generates

All-or-nothing (cleanup on failure), in one configured writable database (setting `database`, default `assignments_data`; the deployment adds an empty `assignments_data.db` to the volume seed):

1. `a_<slug>_tasks` (task mode only): `id INTEGER PK`, one TEXT column per CSV header (sanitized), `status` ('pending'|'done'), `created_at`.
2. `a_<slug>_responses`: `id`, `task_id` (task mode), one column per input field (+ `_missing` companions), `is_public INTEGER DEFAULT 0`, `submitted_at`.
3. `a_<slug>_config`: `responses_per_task` (task mode), `status` ('open'|'closed').
4. Trigger `a_<slug>_mark_done` (task mode) — phase-1 pattern, reads config.
5. Stored queries via core `datasette.stored_queries.add_query()`: `submit_<slug>` (is_write; INSERT respecting `status='open'` via a WHERE guard on a SELECT-based INSERT), `next_task_<slug>` + `progress_<slug>` (reads).
6. The app via datasette-apps `Registry.create_stored_app(actor_id=creator, ...)`: HTML rendered from a Jinja template that generalizes `apps/census.html` (same look: progress bar, card, toast, skip [task mode], validation, closed-state); `is_private=0`; `sql_databases=[]` (stored queries only); `stored_queries` = the three above.
7. A row in the plugin's registry table `assignments_registry` (in the plugin's own space in the same database): slug, name, mode, owner actor_id, definition JSON, created_at.

**Slugs:** derived from the name, strictly `^[a-z][a-z0-9_]{0,39}$`, uniqueness-checked — they become SQL identifiers; whitelist, never escape. CSV headers sanitized the same way (collisions → suffixed).

## Pages & permissions

| Route | Who | What |
|---|---|---|
| `/-/assignments` | signed-in | list your assignments (root: all); links to create |
| `/-/assignments/new` | signed-in | the builder wizard |
| `/-/assignments/<slug>` | owner or root | progress, open/close toggle, responses-per-task edit, response list with per-row public toggle, CSV export (full = owner view; public = the view) , link to app + public view |

Wizard is server-rendered forms + vanilla JS for the field-list editor (add/remove/reorder fields, options editing) and a **live preview iframe** (client-side render of the generated app HTML with sample data) before Create. Menu link ("Assignments") for signed-in actors via `menu_links` hook.

Contributors: anonymous, via the generated app, exactly as phase 1.

## Packaging & layout

`plugins/datasette-assignments/` in this repo — a real package (pyproject.toml, `datasette_assignments/` module, tests) installed with `pip install -e` locally and in the Docker image. PyPI later. Module layout: `__init__.py` (hooks/routes), `schema.py` (definition → DDL/queries), `render.py` (definition → app HTML via Jinja template), `views.py` (wizard/list/manage pages), `registry.py` (assignments_registry access), `templates/`, `static/`.

## Error handling

- Wizard validation server-side (slug rules, ≥1 input field, options present for choice fields, CSV parse errors reported with row numbers, CSV size cap ~10k rows).
- Creation is transactional-in-effect: on any step failing, previously created artifacts for that slug are dropped (tables/queries/app) before the error page renders.
- Generated app handles: closed assignment (friendly closed state), no tasks remaining, submit failure toast (phase-1 patterns).

## Testing

- Unit: slug/header sanitization; definition → DDL golden tests; definition → HTML golden test (known definition vs expected app HTML); mode differences.
- Integration (datasette test client): signed-in wizard POST creates all artifacts; anonymous submit through the bridge endpoint lands a row and (task mode) fires the trigger; responses table 403s anonymously; public view shows only Gallery fields of `is_public=1` rows; owner toggles a response public; close → submit rejected; non-owner cannot manage.
- Demo deployment updated (plugin in image + seed `assignments_data.db`) only after tests pass locally.

## Out of scope for v1

Editing live assignments' fields / regeneration; contributor accounts; moderation beyond the public toggle; email notifications; PyPI release; per-assignment theming UI (creators can still edit the generated app HTML by hand — that's the point of the generator approach).
