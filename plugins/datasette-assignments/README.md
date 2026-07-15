# datasette-assignments

A no-code builder for [MuckRock Assignments](https://www.muckrock.com/assignment/)-style crowdsourcing assignments, built on [Datasette Apps](https://datasette.io/blog/2026/datasette-apps/).

Point it at a running Datasette instance, log in, and the wizard walks you through creating a form-based or task-based assignment. Every response lands in a SQLite table you can browse, query, and export — without writing any SQL or HTML.

**Requires:** `datasette>=1.0a35`, `datasette-apps>=0.1a3`

---

## Install

```bash
pip install -e plugins/datasette-assignments
```

(PyPI publishing is out of scope for the current release; install from this repo.)

---

## Configuration

Add to `datasette.yaml`:

```yaml
plugins:
  datasette-assignments:
    database: assignments_data   # optional; this is the default
```

`database` names the Datasette database where the plugin stores all assignment data (tasks, responses, config tables). The database must already exist when Datasette starts, or must be created by another mechanism — the plugin does not create the database file itself.

---

## Modes

### Tasks mode

You supply a CSV of tasks (one row = one thing to verify). Each contributor sees one task at a time, chosen randomly from the ones that still need more responses. When a task accumulates enough responses (`responses_per_task`, default 3) a trigger marks it `done` and it no longer appears in the queue.

Use this when: you have a bounded list of things to check — documents, cities, records — and want structured, redundant coverage.

### Form mode

No task list. Each submission creates a new row in the responses table. Rows accumulate without limit.

Use this when: you want an open-ended feedback form, a tip intake, or any other case where there is no fixed task list.

---

## Routes

| Route | Method | What it does |
|---|---|---|
| `/-/assignments` | GET | List assignments visible to the current actor |
| `/-/assignments/new` | GET / POST | Wizard to create an assignment |
| `/-/assignments/preview` | POST | Preview the generated app HTML |
| `/-/assignments/<slug>` | GET | Manage page (owner or root only) |
| `/-/assignments/<slug>/toggle-status` | POST | Open ↔ closed |
| `/-/assignments/<slug>/target` | POST | Update `responses_per_task` |
| `/-/assignments/<slug>/response-public` | POST | Toggle `is_public` on one response |
| `/-/assignments/<slug>/delete` | POST | Destroy all artifacts |
| `/-/assignments/<slug>/export.csv` | GET | Download all responses as CSV |

All routes require a signed-in actor. The manage route and its sub-routes additionally require either the assignment owner or `root`.

---

## What gets generated

When you create an assignment the plugin writes the following artifacts into the data database and the internal database. They belong to you — you can browse, query, and export them directly through Datasette.

| Artifact | Modes | Description |
|---|---|---|
| `a_<slug>_tasks` table | tasks only | One row per task; `status` flips to `done` when enough responses arrive |
| `a_<slug>_responses` table | both | One row per submission; private by default |
| `a_<slug>_config` table | both | Key/value store (`status`, `responses_per_task`) |
| `a_<slug>_mark_done` trigger | tasks only | Marks a task done once response count ≥ target |
| `a_<slug>_public` view | both (Gallery fields only) | Public subset: only rows where `is_public = 1`, only Gallery-flagged columns |
| `submit_<slug>` stored query | both | Write query used by the app to insert a response |
| `next_task_<slug>` stored query | tasks only | Picks the next undone task for a contributor |
| `progress_<slug>` stored query | both | Counts for the progress bar |
| datasette-apps app | both | The contributor-facing HTML app |
| Registry row | both | Plugin-internal record in `internal.db` |

Deleting an assignment from `/-/assignments/<slug>/delete` removes all of these artifacts.

---

## Privacy model

### Responses are private by default

`a_<slug>_responses` is denied to everyone except the assignment owner and `root`. The plugin enforces this through a `permission_resources_sql` hook that returns a deny row for every responses table not owned by the requesting actor.

Raw SQL (`execute-sql`) is also denied on the data database for all non-root actors. This matters: without it, any authenticated user could run `SELECT * FROM a_<slug>_responses` directly and bypass the table-level denial.

### Gallery fields and the public view

When you mark an input field as **Gallery**, the plugin creates `a_<slug>_public` — a view that exposes only Gallery-flagged columns from rows where `is_public = 1`. The view is readable by anyone the instance allows.

The manage page (`/-/assignments/<slug>`) lets the owner toggle `is_public` on individual responses.

### Why stored queries are `is_trusted`

All plugin-generated stored queries (`submit_<slug>`, `next_task_<slug>`, `progress_<slug>`) are created with `is_trusted=True`. This flag tells Datasette to bypass the `execute-sql` permission check when the query runs — the app calls the query, not the user typing SQL.

This is safe because the SQL is generated by the plugin from the validated definition and is immutable; it is not user-supplied. Trusted queries are what make anonymous submissions possible on an instance that denies raw SQL.

### Uninstall warning

> **If you uninstall the plugin, all permission enforcement disappears.**
>
> The `a_<slug>_responses` tables remain in the data database exactly as created, and your assignments keep accepting submissions if the stored queries and app are still present. But the `permission_resources_sql` hook is no longer registered, so `a_<slug>_responses` becomes visible to whoever the instance-level permissions allow (potentially everyone, including anonymous visitors).
>
> Before uninstalling: either delete all assignments through the plugin UI, or add explicit `allow: false` blocks on the responses tables in `datasette.yaml`, or take the database offline.

---

## Multi-user setup

Any authentication plugin that supplies `actor` objects works. The plugin's permission hook uses `actor["id"]` as the owner identifier.

The simplest setup for a small team is [datasette-auth-passwords](https://github.com/simonw/datasette-auth-passwords). Add one entry per creator in `datasette.yaml`:

```yaml
plugins:
  datasette-auth-passwords:
    alice_password_hash:
      $env: ALICE_PASSWORD_HASH
    bob_password_hash:
      $env: BOB_PASSWORD_HASH
```

Each user can then log in and create assignments. Owners can only see and manage their own assignments; `root` can see all.

---

## Definition shape

The wizard submits a JSON definition. You can also POST one directly to `/-/assignments/new`. The shape:

```json
{
  "slug": "census",
  "name": "City Census",
  "mode": "tasks",
  "responses_per_task": 3,
  "task_columns": ["city", "state"],
  "task_title_column": "city",
  "task_image_column": null,
  "instructions": "Find each city's public records page.",
  "fields": [
    {
      "kind": "header",
      "text": "Public Records"
    },
    {
      "kind": "input",
      "id": "records_url",
      "type": "url",
      "label": "Records page URL",
      "required": true,
      "missing_companion": true,
      "gallery": false
    }
  ]
}
```

Field kinds: `header`, `paragraph`, `input`. Input types: `text`, `textarea`, `number`, `date`, `select`, `checkbox_group`, `checkbox`, `url`, `email`. Set `missing_companion: true` on any text/textarea/url/email field to add a "couldn't find" checkbox alongside it. Set `gallery: true` on any input to include it in the public view (requires at least one Gallery field for the view to be created).
