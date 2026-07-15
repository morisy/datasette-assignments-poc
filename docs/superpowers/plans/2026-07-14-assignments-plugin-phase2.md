# datasette-assignments Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pip-installable plugin giving signed-in users a WYSIWYG builder that generates complete, standard-Datasette crowdsourcing assignments (tables, trigger, stored queries, datasette-apps app) with private-by-default responses.

**Architecture:** Generator, not interpreter. `schema.py` turns a validated definition dict into DDL + stored-query SQL; `render.py` turns it into app HTML (generalizing `apps/census.html`); `creator.py` orchestrates creation with rollback; `registry.py` tracks assignments in the internal DB; a `permission_resources_sql` hook makes responses tables owner-only and denies raw SQL on the data DB. Wizard/list/manage pages are server-rendered with vanilla-JS field editing and a preview iframe.

**Tech Stack:** Datasette 1.0a35 (pinned), datasette-apps 0.1a3 (pinned), Python 3.11+, Jinja2 (via datasette), pytest + pytest-asyncio, sqlite3.

## Global Constraints

- Pins unchanged: `datasette==1.0a35`, `datasette-apps==0.1a3`, `datasette-auth-passwords==1.1.1`.
- Slug regex, exactly: `^[a-z][a-z0-9_]{0,39}$`. Slugs and sanitized CSV headers become SQL identifiers: whitelist, never escape or quote your way around it.
- Table names: `a_<slug>_tasks`, `a_<slug>_responses`, `a_<slug>_config`; trigger `a_<slug>_mark_done`; public view `a_<slug>_public`; stored queries `submit_<slug>`, `next_task_<slug>` (task mode only), `progress_<slug>`.
- Responses private by default: `is_public INTEGER NOT NULL DEFAULT 0` on every responses table; view-table on responses tables denied to everyone except owner/root; execute-sql on the data DB denied except root — both via the plugin's `permission_resources_sql` hook.
- Generated apps call ONLY `datasette.storedQuery()` — never `datasette.query()` raw SQL.
- Data database name comes from plugin config `plugins.datasette-assignments.database`, default `assignments_data`.
- Registry table `assignments_registry` lives in the INTERNAL database.
- Stored write queries are single-statement; task-mode side effects live in the trigger.
- Every mutation path is idempotent-or-rolled-back; creation failure must leave zero artifacts for that slug.
- Repo: /Users/morisy/Documents/Code/datasette_assignments, branch `phase-2` (create from main at start). Venv: `.venv`.
- Reference files the implementer should read when told to: `apps/census.html` (app look/behavior), `.venv/lib/python3.11/site-packages/datasette_apps/permissions.py` (PermissionSQL pattern), `.venv/lib/python3.11/site-packages/datasette/stored_queries.py` (`add_query`, `remove_query`).

## File Structure

```
plugins/datasette-assignments/
├── pyproject.toml
├── datasette_assignments/
│   ├── __init__.py        # hookimpls: startup, register_routes, menu_links, permission_resources_sql
│   ├── schema.py          # validation, sanitization, DDL + stored-query SQL generation
│   ├── registry.py        # assignments_registry CRUD (internal DB)
│   ├── render.py          # definition -> app HTML
│   ├── creator.py         # create/destroy orchestration with rollback
│   ├── views.py           # list / new / preview / manage / toggle / export routes
│   ├── templates/
│   │   ├── assignments_list.html
│   │   ├── assignments_new.html
│   │   ├── assignments_manage.html
│   │   └── app_template.html
│   └── static/
│       ├── builder.js
│       └── builder.css
└── tests/
    ├── conftest.py
    ├── test_schema.py
    ├── test_registry.py
    ├── test_render.py
    ├── test_creator.py
    └── test_permissions_views.py
```

## The Definition dict (canonical shape, used everywhere)

```python
{
    "slug": "city_survey",            # validated ^[a-z][a-z0-9_]{0,39}$
    "name": "City Survey",
    "mode": "tasks",                  # "tasks" | "form"
    "instructions": "Help us ...",    # public, shown atop the app
    "responses_per_task": 3,           # tasks mode only, int >= 1
    "task_columns": ["city", "state"],# tasks mode: sanitized CSV headers, in order
    "task_title_column": "city",      # tasks mode: which column is the card title
    "task_image_column": None,         # tasks mode: column holding an image URL, or None
    "fields": [
        # layout blocks (no data):
        {"kind": "header", "text": "About the records page"},
        {"kind": "paragraph", "text": "Look for ..."},
        # input fields:
        {"kind": "input", "type": "url", "id": "records_page",
         "label": "Records page", "help": "", "required": True,
         "gallery": True, "missing_companion": True, "options": []},
        # type ∈ text | textarea | number | date | select | checkbox_group | checkbox | url | email
        # id: sanitized like slugs (headers rule), unique among fields
        # options: non-empty list required for select / checkbox_group
        # missing_companion allowed only for text | textarea | url | email
    ],
}
```

---

### Task 1: Package scaffold, installable and loading

**Files:**
- Create: `plugins/datasette-assignments/pyproject.toml`, `plugins/datasette-assignments/datasette_assignments/__init__.py`, `plugins/datasette-assignments/tests/conftest.py`, `plugins/datasette-assignments/tests/test_schema.py` (loading test only)

**Interfaces:**
- Produces: installed editable package; `PLUGIN_NAME = "datasette-assignments"`; `get_data_db_name(datasette) -> str` in `__init__.py` (reads plugin config, default `"assignments_data"`). All later tasks import from `datasette_assignments`.

- [ ] **Step 1: Create branch and scaffold**

```bash
cd /Users/morisy/Documents/Code/datasette_assignments
git checkout -b phase-2
mkdir -p plugins/datasette-assignments/datasette_assignments/templates \
         plugins/datasette-assignments/datasette_assignments/static \
         plugins/datasette-assignments/tests
```

`plugins/datasette-assignments/pyproject.toml`:
```toml
[project]
name = "datasette-assignments"
version = "0.1a0"
description = "WYSIWYG builder for crowdsourcing assignments on Datasette"
requires-python = ">=3.11"
dependencies = ["datasette>=1.0a35", "datasette-apps>=0.1a3"]

[project.entry-points.datasette]
assignments = "datasette_assignments"

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["datasette_assignments*"]

[tool.setuptools.package-data]
datasette_assignments = ["templates/*", "static/*"]
```

`plugins/datasette-assignments/datasette_assignments/__init__.py`:
```python
from datasette import hookimpl

PLUGIN_NAME = "datasette-assignments"
DEFAULT_DATABASE = "assignments_data"


def get_data_db_name(datasette):
    config = datasette.plugin_config(PLUGIN_NAME) or {}
    return config.get("database", DEFAULT_DATABASE)
```

`plugins/datasette-assignments/tests/conftest.py`:
```python
import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"
```

`plugins/datasette-assignments/tests/test_schema.py` (just the loading test for now):
```python
import pytest
from datasette.app import Datasette


@pytest.mark.asyncio
async def test_plugin_is_installed():
    ds = Datasette(memory=True)
    response = await ds.client.get("/-/plugins.json")
    assert response.status_code == 200
    names = [p["name"] for p in response.json()]
    assert "datasette-assignments" in names
```

- [ ] **Step 2: Install and verify the test fails, then passes**

```bash
.venv/bin/pip install -e plugins/datasette-assignments
.venv/bin/pip install pytest-asyncio
```
Add `pytest-asyncio==1.1.0` to `requirements-dev.txt`. Add to the repo root a `pytest.ini` section if none exists — create `plugins/datasette-assignments/pytest.ini`:
```ini
[pytest]
asyncio_mode = auto
```
Run: `.venv/bin/pytest plugins/datasette-assignments/tests/test_schema.py -v`
Expected: PASS (`datasette-assignments` present). Also confirm phase-1 tests still pass: `.venv/bin/pytest tests/ -q` → 6 passed.

- [ ] **Step 3: Commit**

```bash
git add plugins/ requirements-dev.txt
git commit -m "feat(plugin): datasette-assignments package scaffold, installable"
```

---

### Task 2: schema.py — validation and sanitization (TDD)

**Files:**
- Create: `plugins/datasette-assignments/datasette_assignments/schema.py`
- Modify: `plugins/datasette-assignments/tests/test_schema.py` (append)

**Interfaces:**
- Produces: `slugify(name) -> str` (best-effort slug from a display name); `SLUG_RE`; `sanitize_identifier(raw, existing=()) -> str` (lowercase, `[a-z0-9_]`, no leading digit, dedupe by `_2` suffixing, max 40 chars, raises `DefinitionError` on empty result); `validate_definition(defn: dict) -> dict` (returns normalized copy or raises `DefinitionError(str)` listing every problem); `DefinitionError(Exception)` with `.errors: list[str]`.

- [ ] **Step 1: Append failing tests**

```python
from datasette_assignments.schema import (
    DefinitionError, sanitize_identifier, slugify, validate_definition,
)


def make_defn(**over):
    base = {
        "slug": "city_survey", "name": "City Survey", "mode": "form",
        "instructions": "Help.", "responses_per_task": 3,
        "task_columns": [], "task_title_column": None, "task_image_column": None,
        "fields": [
            {"kind": "input", "type": "text", "id": "answer", "label": "Answer",
             "help": "", "required": True, "gallery": False,
             "missing_companion": False, "options": []},
        ],
    }
    base.update(over)
    return base


def test_slugify_and_sanitize():
    assert slugify("City Survey 2026!") == "city_survey_2026"
    assert sanitize_identifier("Records Page URL") == "records_page_url"
    assert sanitize_identifier("2fast") == "c_2fast"
    assert sanitize_identifier("city", existing=("city",)) == "city_2"
    with pytest.raises(DefinitionError):
        sanitize_identifier("!!!")


def test_validate_accepts_good_form_definition():
    normalized = validate_definition(make_defn())
    assert normalized["slug"] == "city_survey"


def test_validate_rejects_bad_slug_and_reserved_words():
    with pytest.raises(DefinitionError) as e:
        validate_definition(make_defn(slug="Bad-Slug"))
    assert any("slug" in msg for msg in e.value.errors)


def test_validate_requires_input_field_and_options():
    with pytest.raises(DefinitionError):
        validate_definition(make_defn(fields=[{"kind": "header", "text": "hi"}]))
    bad_select = make_defn(fields=[
        {"kind": "input", "type": "select", "id": "pick", "label": "Pick",
         "help": "", "required": False, "gallery": False,
         "missing_companion": False, "options": []},
    ])
    with pytest.raises(DefinitionError):
        validate_definition(bad_select)


def test_validate_tasks_mode_requirements():
    with pytest.raises(DefinitionError):
        validate_definition(make_defn(mode="tasks", task_columns=[]))
    good = validate_definition(make_defn(
        mode="tasks", task_columns=["city", "state"], task_title_column="city"))
    assert good["responses_per_task"] == 3


def test_validate_rejects_companion_on_wrong_type_and_dupe_ids():
    with pytest.raises(DefinitionError):
        validate_definition(make_defn(fields=[
            {"kind": "input", "type": "date", "id": "d", "label": "D", "help": "",
             "required": False, "gallery": False, "missing_companion": True,
             "options": []}]))
    with pytest.raises(DefinitionError):
        validate_definition(make_defn(fields=[
            {"kind": "input", "type": "text", "id": "x", "label": "A", "help": "",
             "required": False, "gallery": False, "missing_companion": False,
             "options": []},
            {"kind": "input", "type": "text", "id": "x", "label": "B", "help": "",
             "required": False, "gallery": False, "missing_companion": False,
             "options": []}]))
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError`/`ImportError` expected.

- [ ] **Step 3: Implement schema.py (validation half)**

```python
"""Definition validation and identifier sanitization.

Slugs, field ids, and CSV headers all become SQL identifiers. The rule is
whitelist-only: ^[a-z][a-z0-9_]{0,39}$ — we never escape or quote identifiers.
"""
import re

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
INPUT_TYPES = {"text", "textarea", "number", "date", "select",
               "checkbox_group", "checkbox", "url", "email"}
COMPANION_TYPES = {"text", "textarea", "url", "email"}
OPTION_TYPES = {"select", "checkbox_group"}
# id/status/task_id/is_public/submitted_at/created_at are generated columns.
RESERVED_IDS = {"id", "status", "task_id", "is_public", "submitted_at",
                "created_at", "rowid"}
MODES = {"tasks", "form"}


class DefinitionError(Exception):
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def sanitize_identifier(raw, existing=()):
    ident = re.sub(r"[^a-z0-9_]+", "_", str(raw).strip().lower()).strip("_")
    if ident and ident[0].isdigit():
        ident = "c_" + ident
    ident = ident[:40]
    if not ident:
        raise DefinitionError([f"Cannot make an identifier out of {raw!r}"])
    base, n = ident, 1
    while ident in existing:
        n += 1
        ident = f"{base[:37]}_{n}"
    return ident


def slugify(name):
    return sanitize_identifier(name)


def validate_definition(defn):
    errors = []
    d = dict(defn)
    if not SLUG_RE.match(d.get("slug") or ""):
        errors.append("slug must match ^[a-z][a-z0-9_]{0,39}$")
    if not (d.get("name") or "").strip():
        errors.append("name is required")
    if d.get("mode") not in MODES:
        errors.append("mode must be 'tasks' or 'form'")
    try:
        d["responses_per_task"] = int(d.get("responses_per_task") or 3)
        if d["responses_per_task"] < 1:
            errors.append("responses_per_task must be >= 1")
    except (TypeError, ValueError):
        errors.append("responses_per_task must be an integer")

    if d.get("mode") == "tasks":
        cols = d.get("task_columns") or []
        if not cols:
            errors.append("tasks mode requires at least one task column")
        seen = set()
        for col in cols:
            if not SLUG_RE.match(col) or col in RESERVED_IDS or col in seen:
                errors.append(f"bad task column {col!r}")
            seen.add(col)
        if cols and d.get("task_title_column") not in cols:
            errors.append("task_title_column must be one of task_columns")
        if d.get("task_image_column") and d["task_image_column"] not in cols:
            errors.append("task_image_column must be one of task_columns")
    else:
        d["task_columns"] = []
        d["task_title_column"] = None
        d["task_image_column"] = None

    fields = d.get("fields") or []
    input_ids = set()
    n_inputs = 0
    for f in fields:
        kind = f.get("kind")
        if kind in ("header", "paragraph"):
            if not (f.get("text") or "").strip():
                errors.append(f"{kind} block needs text")
            continue
        if kind != "input":
            errors.append(f"unknown field kind {kind!r}")
            continue
        n_inputs += 1
        fid = f.get("id") or ""
        if not SLUG_RE.match(fid) or fid in RESERVED_IDS:
            errors.append(f"bad field id {fid!r}")
        if fid in input_ids:
            errors.append(f"duplicate field id {fid!r}")
        input_ids.add(fid)
        if f.get("type") not in INPUT_TYPES:
            errors.append(f"field {fid!r}: unknown type {f.get('type')!r}")
        if not (f.get("label") or "").strip():
            errors.append(f"field {fid!r}: label is required")
        if f.get("type") in OPTION_TYPES and not f.get("options"):
            errors.append(f"field {fid!r}: options are required for {f.get('type')}")
        if f.get("missing_companion") and f.get("type") not in COMPANION_TYPES:
            errors.append(f"field {fid!r}: 'couldn't find' companion only allowed "
                          f"on text/textarea/url/email")
    if n_inputs == 0:
        errors.append("at least one input field is required")

    if errors:
        raise DefinitionError(errors)
    return d
```

- [ ] **Step 4: Run** — all Task-2 tests PASS (plus the Task-1 loading test).

- [ ] **Step 5: Commit** — `git add plugins/ && git commit -m "feat(plugin): definition validation and identifier sanitization (TDD)"`

---

### Task 3: schema.py — DDL and stored-query SQL generation (TDD)

**Files:**
- Modify: `plugins/datasette-assignments/datasette_assignments/schema.py` (append), `plugins/datasette-assignments/tests/test_schema.py` (append)

**Interfaces:**
- Produces: `build_ddl(defn) -> list[str]` (CREATE TABLE/TRIGGER/VIEW statements, in order); `build_queries(defn, db_name) -> dict` with keys `submit`, `progress`, and (tasks mode) `next_task`, each `{"name": str, "sql": str, "is_write": bool}`; `response_columns(defn) -> list[str]` (data columns in INSERT order, `_missing` companions included); `drop_ddl(slug, mode) -> list[str]`.
- Column typing: number → `REAL`, checkbox → `INTEGER`, everything else `TEXT` (checkbox_group stores a JSON array as TEXT).

- [ ] **Step 1: Append failing tests**

```python
from datasette_assignments.schema import (
    build_ddl, build_queries, drop_ddl, response_columns,
)
import sqlite3


def tasks_defn():
    return validate_definition(make_defn(
        slug="mayors", mode="tasks",
        task_columns=["city", "state"], task_title_column="city",
        fields=[
            {"kind": "header", "text": "Find these"},
            {"kind": "input", "type": "url", "id": "records_page",
             "label": "Records page", "help": "", "required": True,
             "gallery": True, "missing_companion": True, "options": []},
            {"kind": "input", "type": "checkbox_group", "id": "topics",
             "label": "Topics", "help": "", "required": False,
             "gallery": False, "missing_companion": False,
             "options": ["police", "budget"]},
        ]))


def test_ddl_executes_and_trigger_fires():
    defn = tasks_defn()
    conn = sqlite3.connect(":memory:")
    for stmt in build_ddl(defn):
        conn.execute(stmt)
    conn.execute("INSERT INTO a_mayors_tasks (city, state) VALUES ('Boston','MA')")
    conn.execute("INSERT INTO a_mayors_config (key, value) VALUES "
                 "('responses_per_task','2'),('status','open')")
    ins = ("INSERT INTO a_mayors_responses "
           "(task_id, records_page, records_page_missing, topics) "
           "VALUES (1, 'https://x.gov', 0, '[\"police\"]')")
    conn.execute(ins)
    assert conn.execute("SELECT status FROM a_mayors_tasks").fetchone()[0] == "pending"
    conn.execute(ins)
    assert conn.execute("SELECT status FROM a_mayors_tasks").fetchone()[0] == "done"


def test_public_view_exposes_only_gallery_fields_of_public_rows():
    defn = tasks_defn()
    conn = sqlite3.connect(":memory:")
    for stmt in build_ddl(defn):
        conn.execute(stmt)
    conn.execute("INSERT INTO a_mayors_tasks (city, state) VALUES ('Boston','MA')")
    conn.execute("INSERT INTO a_mayors_responses "
                 "(task_id, records_page, records_page_missing, topics, is_public) "
                 "VALUES (1,'https://pub.gov',0,'[]',1), (1,'https://priv.gov',0,'[]',0)")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(a_mayors_public)")]
    assert "records_page" in cols and "topics" not in cols  # topics not gallery
    rows = conn.execute("SELECT records_page FROM a_mayors_public").fetchall()
    assert rows == [("https://pub.gov",)]


def test_form_mode_has_no_tasks_or_trigger():
    defn = validate_definition(make_defn(slug="tips"))
    stmts = "\n".join(build_ddl(defn))
    assert "a_tips_tasks" not in stmts and "TRIGGER" not in stmts
    assert "a_tips_responses" in stmts and "a_tips_public" not in stmts or True
    # gallery=False on the only field -> no public view? No: view always created,
    # selecting only is_public rows with zero gallery cols is useless — assert
    # view exists only when at least one gallery field:
    assert "a_tips_public" not in stmts


def test_queries_shapes():
    defn = tasks_defn()
    q = build_queries(defn, "assignments_data")
    assert q["submit"]["name"] == "submit_mayors" and q["submit"]["is_write"]
    assert ":records_page" in q["submit"]["sql"]
    assert "status = 'open'" in q["submit"]["sql"] or "status='open'" in q["submit"]["sql"]
    assert "instr(" in q["next_task"]["sql"] and ":seen" in q["next_task"]["sql"]
    assert not q["progress"]["is_write"]
    form_q = build_queries(validate_definition(make_defn(slug="tips")), "assignments_data")
    assert "next_task" not in form_q
    assert ":task_id" not in form_q["submit"]["sql"]


def test_drop_ddl_removes_everything():
    defn = tasks_defn()
    conn = sqlite3.connect(":memory:")
    for stmt in build_ddl(defn):
        conn.execute(stmt)
    for stmt in drop_ddl("mayors", "tasks"):
        conn.execute(stmt)
    remaining = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'a_mayors%'")]
    assert remaining == []
```

- [ ] **Step 2: Run to verify failure** — ImportError on `build_ddl`.

- [ ] **Step 3: Implement generation half of schema.py**

```python
def _sql_type(field):
    return {"number": "REAL", "checkbox": "INTEGER"}.get(field["type"], "TEXT")


def _input_fields(defn):
    return [f for f in defn["fields"] if f["kind"] == "input"]


def response_columns(defn):
    cols = []
    for f in _input_fields(defn):
        cols.append(f["id"])
        if f.get("missing_companion"):
            cols.append(f["id"] + "_missing")
    return cols


def build_ddl(defn):
    slug, mode = defn["slug"], defn["mode"]
    stmts = []
    if mode == "tasks":
        task_cols = ",\n    ".join(f"{c} TEXT" for c in defn["task_columns"])
        stmts.append(f"""CREATE TABLE a_{slug}_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    {task_cols},
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now'))
)""")
    resp_cols = []
    if mode == "tasks":
        resp_cols.append(f"task_id INTEGER NOT NULL REFERENCES a_{slug}_tasks(id)")
    for f in _input_fields(defn):
        resp_cols.append(f"{f['id']} {_sql_type(f)}")
        if f.get("missing_companion"):
            resp_cols.append(f"{f['id']}_missing INTEGER NOT NULL DEFAULT 0")
    cols_sql = ",\n    ".join(resp_cols)
    stmts.append(f"""CREATE TABLE a_{slug}_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    {cols_sql},
    is_public INTEGER NOT NULL DEFAULT 0,
    submitted_at TEXT DEFAULT (datetime('now'))
)""")
    stmts.append(f"""CREATE TABLE a_{slug}_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)""")
    if mode == "tasks":
        stmts.append(f"""CREATE TRIGGER a_{slug}_mark_done
AFTER INSERT ON a_{slug}_responses
BEGIN
    UPDATE a_{slug}_tasks SET status = 'done'
    WHERE id = NEW.task_id
      AND (SELECT COUNT(*) FROM a_{slug}_responses
           WHERE task_id = NEW.task_id)
          >= (SELECT CAST(value AS INTEGER) FROM a_{slug}_config
              WHERE key = 'responses_per_task');
END""")
    gallery_cols = [f["id"] for f in _input_fields(defn) if f.get("gallery")]
    if gallery_cols:
        gcols = ", ".join(gallery_cols)
        stmts.append(f"""CREATE VIEW a_{slug}_public AS
SELECT id, {gcols}, submitted_at FROM a_{slug}_responses WHERE is_public = 1""")
    return stmts


def drop_ddl(slug, mode):
    stmts = [f"DROP VIEW IF EXISTS a_{slug}_public"]
    if mode == "tasks":
        stmts.append(f"DROP TRIGGER IF EXISTS a_{slug}_mark_done")
    stmts.append(f"DROP TABLE IF EXISTS a_{slug}_responses")
    stmts.append(f"DROP TABLE IF EXISTS a_{slug}_config")
    if mode == "tasks":
        stmts.append(f"DROP TABLE IF EXISTS a_{slug}_tasks")
    return stmts


def build_queries(defn, db_name):
    slug, mode = defn["slug"], defn["mode"]
    cols = response_columns(defn)
    params = list(cols)
    insert_cols = list(cols)
    if mode == "tasks":
        insert_cols.insert(0, "task_id")
        params.insert(0, "task_id")
    col_list = ", ".join(insert_cols)
    select_list = ", ".join(f":{p}" for p in params)
    # Single statement; refuses rows once the assignment is closed.
    submit_sql = (
        f"INSERT INTO a_{slug}_responses ({col_list})\n"
        f"SELECT {select_list}\n"
        f"WHERE (SELECT value FROM a_{slug}_config WHERE key = 'status') = 'open'"
    )
    queries = {
        "submit": {"name": f"submit_{slug}", "sql": submit_sql, "is_write": True},
    }
    if mode == "tasks":
        # :seen is a comma-joined id list ('' when empty); instr() matching
        # avoids needing SQL array params.
        queries["next_task"] = {
            "name": f"next_task_{slug}",
            "sql": (
                f"SELECT t.id, {', '.join('t.' + c for c in defn['task_columns'])}\n"
                f"FROM a_{slug}_tasks t\n"
                f"WHERE (SELECT COUNT(*) FROM a_{slug}_responses r "
                f"WHERE r.task_id = t.id)\n"
                f"      < (SELECT CAST(value AS INTEGER) FROM a_{slug}_config "
                f"WHERE key = 'responses_per_task')\n"
                f"  AND instr(',' || :seen || ',', ',' || t.id || ',') = 0\n"
                f"ORDER BY RANDOM() LIMIT 1"
            ),
            "is_write": False,
        }
        progress_sql = (
            f"SELECT (SELECT COUNT(*) FROM a_{slug}_tasks) AS total,\n"
            f"  (SELECT COUNT(*) FROM a_{slug}_tasks WHERE status='done') AS done,\n"
            f"  (SELECT COUNT(*) FROM a_{slug}_responses) AS collected,\n"
            f"  (SELECT CAST(value AS INTEGER) FROM a_{slug}_config "
            f"WHERE key='responses_per_task') AS target,\n"
            f"  (SELECT value FROM a_{slug}_config WHERE key='status') AS status"
        )
    else:
        progress_sql = (
            f"SELECT (SELECT COUNT(*) FROM a_{slug}_responses) AS collected,\n"
            f"  (SELECT value FROM a_{slug}_config WHERE key='status') AS status"
        )
    queries["progress"] = {"name": f"progress_{slug}", "sql": progress_sql,
                           "is_write": False}
    return queries
```

- [ ] **Step 4: Run** — all schema tests PASS. Fix `test_form_mode_has_no_tasks_or_trigger` if you wrote the view assertion sloppily: the correct assertions are `"a_tips_tasks" not in stmts`, `"TRIGGER" not in stmts`, `"a_tips_public" not in stmts` (the only field has `gallery: False`).

- [ ] **Step 5: Commit** — `git commit -m "feat(plugin): DDL, trigger, view, and stored-query generation (TDD)"`

---

### Task 4: registry.py — assignments registry in the internal DB (TDD)

**Files:**
- Create: `plugins/datasette-assignments/datasette_assignments/registry.py`, `plugins/datasette-assignments/tests/test_registry.py`
- Modify: `plugins/datasette-assignments/datasette_assignments/__init__.py` (add `startup` hookimpl)

**Interfaces:**
- Produces (all async, all take `datasette` first): `ensure_table(datasette)`; `create(datasette, defn, owner_id, app_id) -> None`; `get(datasette, slug) -> dict | None` (row + parsed `definition`); `list_for(datasette, actor) -> list[dict]` (all for root, own for others, newest first); `delete(datasette, slug)`. Row dict keys: `slug, name, mode, owner_id, app_id, definition, created_at`.
- `__init__.py` gains: `@hookimpl def startup(datasette)` calling `ensure_table`.

- [ ] **Step 1: Write failing tests**

```python
import pytest
from datasette.app import Datasette
from datasette_assignments import registry

DEFN = {
    "slug": "tips", "name": "Tips", "mode": "form", "instructions": "",
    "responses_per_task": 3, "task_columns": [], "task_title_column": None,
    "task_image_column": None,
    "fields": [{"kind": "input", "type": "text", "id": "tip", "label": "Tip",
                "help": "", "required": True, "gallery": False,
                "missing_companion": False, "options": []}],
}


@pytest.mark.asyncio
async def test_create_get_list_delete():
    ds = Datasette(memory=True)
    await ds.invoke_startup()
    await registry.create(ds, DEFN, owner_id="alice", app_id="app123")
    row = await registry.get(ds, "tips")
    assert row["owner_id"] == "alice" and row["definition"]["slug"] == "tips"
    assert row["app_id"] == "app123"
    alice = await registry.list_for(ds, {"id": "alice"})
    bob = await registry.list_for(ds, {"id": "bob"})
    root = await registry.list_for(ds, {"id": "root"})
    assert [r["slug"] for r in alice] == ["tips"]
    assert bob == [] and len(root) == 1
    await registry.delete(ds, "tips")
    assert await registry.get(ds, "tips") is None
```

- [ ] **Step 2: Run to verify failure** — ImportError.

- [ ] **Step 3: Implement**

`registry.py`:
```python
"""assignments_registry lives in the INTERNAL database (like datasette-apps'
own tables) so permission_resources_sql can join against ownership."""
import json

TABLE_SQL = """CREATE TABLE IF NOT EXISTS assignments_registry (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    app_id TEXT NOT NULL,
    definition TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)"""


async def ensure_table(datasette):
    await datasette.get_internal_database().execute_write(TABLE_SQL)


async def create(datasette, defn, owner_id, app_id):
    await datasette.get_internal_database().execute_write(
        "INSERT INTO assignments_registry (slug, name, mode, owner_id, app_id,"
        " definition) VALUES (?, ?, ?, ?, ?, ?)",
        [defn["slug"], defn["name"], defn["mode"], owner_id, app_id,
         json.dumps(defn)],
    )


def _row_to_dict(row):
    d = dict(row)
    d["definition"] = json.loads(d["definition"])
    return d


async def get(datasette, slug):
    result = await datasette.get_internal_database().execute(
        "SELECT * FROM assignments_registry WHERE slug = ?", [slug])
    row = result.first()
    return _row_to_dict(row) if row else None


async def list_for(datasette, actor):
    actor_id = (actor or {}).get("id")
    db = datasette.get_internal_database()
    if actor_id == "root":
        result = await db.execute(
            "SELECT * FROM assignments_registry ORDER BY created_at DESC")
    else:
        result = await db.execute(
            "SELECT * FROM assignments_registry WHERE owner_id = ?"
            " ORDER BY created_at DESC", [actor_id])
    return [_row_to_dict(r) for r in result.rows]


async def delete(datasette, slug):
    await datasette.get_internal_database().execute_write(
        "DELETE FROM assignments_registry WHERE slug = ?", [slug])
```

Append to `__init__.py`:
```python
from . import registry as _registry


@hookimpl
def startup(datasette):
    async def inner():
        await _registry.ensure_table(datasette)
    return inner
```

- [ ] **Step 4: Run** — PASS. (If `datasette.get_internal_database()` has a different name on 1.0a35, check with `python -c "from datasette.app import Datasette; print([m for m in dir(Datasette) if 'internal' in m])"` and use what exists — datasette-apps' `db.py` shows the working pattern.)

- [ ] **Step 5: Commit** — `git commit -m "feat(plugin): assignments registry in internal DB (TDD)"`

---

### Task 5: render.py — definition → app HTML (TDD, structural assertions)

**Files:**
- Create: `plugins/datasette-assignments/datasette_assignments/render.py`, `plugins/datasette-assignments/datasette_assignments/templates/app_template.html`, `plugins/datasette-assignments/tests/test_render.py`

**Interfaces:**
- Produces: `render_app_html(defn, db_name, preview=False) -> str`. With `preview=True` the emitted HTML includes a stub `window.datasette` (defined BEFORE the main script) that serves one sample task built from the definition's task columns / sample progress and resolves `storedQuery` without network.
- Implementer MUST read `apps/census.html` first — the generated app is its generalization: same CSS palette and layout (header, progress bar, card, toast, action bar, `.state` screens, `prefers-reduced-motion`), same UX (sessionStorage seen-tracking with integer coercion, client-side skip, validation before submit, spinner on submit).

Behavioral contract for the template (all data-driven from `defn`):
1. Reads/writes ONLY via `datasette.storedQuery(DB, name, params)` — `datasette.query()` must not appear anywhere.
2. Tasks mode: on load call `progress_<slug>` then `next_task_<slug>` with `{seen: [...ids].join(",")}`; render task card (title column large; other columns as meta line; image column, when set, as `<img>` with the phase-1 skeleton/onerror pattern); progress label "X of N tasks complete"; Skip button (client-side only). Form mode: no task card, no skip; progress label "N contributions so far"; after submit show a "Thank you — submit another?" state with a button that resets the form.
3. `status != 'open'` from progress → full-card closed state ("This assignment is closed"), no form.
4. Field rendering by type: text→`<input type=text>`, textarea→`<textarea>`, number→`<input type=number>`, date→`<input type=date>`, select→`<select>` with prompt option, checkbox_group→checkbox list (collected as JSON array string), checkbox→single checkbox (0/1), url→`<input type=url>` + `https?://` regex check, email→`<input type=email>` + email regex check. header→`<h3>`, paragraph→`<p class="explain">`. Required fields validated non-empty (checkbox_group required = at least one checked). `missing_companion` fields get the phase-1 "I couldn't find this" checkbox that disables/clears the input and satisfies required; submit params include `<id>_missing` 0/1.
5. Submit params: every response column from `response_columns(defn)` (+ `task_id` in tasks mode), missing values as `""`/`0` never undefined. On success: toast, mark seen (tasks), reload progress, next task / thank-you state. On failure: toast with error, re-enable.
6. All user-facing strings from the definition are HTML-escaped at render time (Jinja autoescape) or via the app's `esc()` at runtime — task row values ALWAYS through `esc()`.

- [ ] **Step 1: Write failing tests**

```python
import pytest
from datasette_assignments.schema import validate_definition
from datasette_assignments.render import render_app_html
from tests.test_schema import make_defn, tasks_defn  # reuse builders


def test_tasks_mode_html_structure():
    html = render_app_html(tasks_defn(), "assignments_data")
    assert "datasette.query(" not in html
    for needle in ["storedQuery", "submit_mayors", "next_task_mayors",
                   "progress_mayors", "records_page_missing",
                   "Number.isInteger", "tasks complete", "Skip"]:
        assert needle in html, needle
    assert "topics" in html and "police" in html
    assert "<h3" in html  # header block rendered


def test_form_mode_html_structure():
    html = render_app_html(validate_definition(make_defn(slug="tips")),
                           "assignments_data")
    assert "next_task_tips" not in html and "Skip" not in html
    assert "submit_tips" in html and "contributions so far" in html


def test_escaping_of_creator_strings():
    d = make_defn(name='Evil <script>alert(1)</script>')
    html = render_app_html(validate_definition(d), "assignments_data")
    assert "<script>alert(1)</script>" not in html


def test_preview_stub_precedes_app_script():
    html = render_app_html(tasks_defn(), "assignments_data", preview=True)
    assert "window.datasette = " in html
    assert html.index("window.datasette = ") < html.index("storedQuery(")
```

- [ ] **Step 2: Run to verify failure** — ImportError.

- [ ] **Step 3: Implement render.py + app_template.html**

`render.py` (complete):
```python
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .schema import response_columns

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


def render_app_html(defn, db_name, preview=False):
    template = _env.get_template("app_template.html")
    return template.render(
        defn=defn,
        db_name=db_name,
        preview=preview,
        response_cols=response_columns(defn),
        defn_json=json.dumps(defn),
        sample_task_json=json.dumps(
            {"id": 1, **{c: f"Sample {c}" for c in defn["task_columns"]}}
        ),
    )
```

`app_template.html`: write it by generalizing `apps/census.html` (open and follow it closely — CSS block near-verbatim, plus `.choice-row`/`.scale` styles from TUTORIAL.md Step 6 where they fit the palette). Structure:

```
<!DOCTYPE html> ... <style>census palette + field styles</style>
<header> eyebrow "Assignment" + {{ defn.name }} </header>
progress bar block
<main id="main">loading state</main>
toast div
{% if preview %}
<script>
window.datasette = {
  storedQuery: function(db, name, params) {
    if (name.indexOf("progress_") === 0)
      return Promise.resolve({rows: [{{ "{total: 5, done: 1, collected: 3, target: " ~ defn.responses_per_task ~ ", status: 'open'}" if defn.mode == "tasks" else "{collected: 3, status: 'open'}" }}]});
    if (name.indexOf("next_task_") === 0)
      return Promise.resolve({rows: [{{ sample_task_json }}]});
    return Promise.resolve({rows: []});
  }
};
</script>
{% endif %}
<script>
const DB = {{ db_name | tojson }};
const DEFN = {{ defn_json }};   <-- fields/mode/labels drive rendering
... generalized census.html logic per the behavioral contract ...
</script>
```

The main script renders the form from `DEFN.fields` (a `renderField(f)` function switching on `f.type`, layout blocks rendered inline), validates per the contract (`readField` generalized), and submits `Object` params built from `response_cols`. In tasks mode the stored query result rows come back as `{rows: [...]}` from `storedQuery` — same shape the bridge returns for reads.

- [ ] **Step 4: Run tests** — PASS. Also eyeball once: `python -c "from datasette_assignments.render import render_app_html; from tests..."` piped to a file, open in browser with preview=True and confirm the form renders and fake-submits (note result in report).

- [ ] **Step 5: Commit** — `git commit -m "feat(plugin): app HTML generation from definition (TDD)"`

---

### Task 6: creator.py — orchestration with rollback (TDD)

**Files:**
- Create: `plugins/datasette-assignments/datasette_assignments/creator.py`, `plugins/datasette-assignments/tests/test_creator.py`

**Interfaces:**
- Consumes: `schema.build_ddl/build_queries/drop_ddl`, `render.render_app_html`, `registry`, datasette core `stored_queries.add_query/remove_query`, datasette-apps `Registry(datasette).create_stored_app(...)` and `.delete_app` equivalent (check `registry.py` in the datasette-apps package for the delete/soft-delete method name and use it).
- Produces: `async create_assignment(datasette, defn, actor) -> dict` (registry row; raises `CreationError(str)` after rolling back); `async destroy_assignment(datasette, slug)` (drops artifacts + registry row; used by rollback and by the manage page's delete); `async insert_tasks(datasette, defn, rows: list[dict])` (bulk INSERT into the tasks table); `async seed_config(datasette, defn)` (responses_per_task + status='open'); `CreationError(Exception)`.
- Creation order (reverse order for rollback): DDL → config seed → task rows (tasks mode) → stored queries via `add_query` (each with `is_private=False` so anonymous view-query is allowed — verify the exact param name in `stored_queries.add_query`'s signature and use it) → app via `create_stored_app(actor_id, name=defn["name"], description=first 200 chars of instructions, html=render_app_html(...), is_private=False, sql_databases=[], stored_queries=["<db>/submit_<slug>", ...])` → registry row.

- [ ] **Step 1: Write failing tests**

```python
import pytest
from datasette.app import Datasette
from datasette_assignments import creator, registry
from datasette_assignments.schema import validate_definition
from tests.test_schema import make_defn, tasks_defn
import sqlite3, tempfile, os


def make_ds(tmp_path):
    db_path = str(tmp_path / "assignments_data.db")
    sqlite3.connect(db_path).close()
    return Datasette([db_path])


@pytest.mark.asyncio
async def test_create_assignment_produces_all_artifacts(tmp_path):
    ds = make_ds(tmp_path)
    await ds.invoke_startup()
    defn = tasks_defn()
    row = await creator.create_assignment(ds, defn, {"id": "alice"})
    assert row["slug"] == "mayors"
    db = ds.get_database("assignments_data")
    names = {r[0] for r in (await db.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'a_mayors%'")).rows}
    assert {"a_mayors_tasks", "a_mayors_responses", "a_mayors_config",
            "a_mayors_mark_done", "a_mayors_public"} <= names
    assert await ds.get_query("assignments_data", "submit_mayors") is not None
    assert await ds.get_query("assignments_data", "next_task_mayors") is not None
    reg = await registry.get(ds, "mayors")
    assert reg["owner_id"] == "alice" and reg["app_id"]


@pytest.mark.asyncio
async def test_create_rolls_back_on_failure(tmp_path, monkeypatch):
    ds = make_ds(tmp_path)
    await ds.invoke_startup()

    async def boom(*a, **kw):
        raise RuntimeError("app creation failed")
    monkeypatch.setattr(creator, "_create_app", boom)
    with pytest.raises(creator.CreationError):
        await creator.create_assignment(ds, tasks_defn(), {"id": "alice"})
    db = ds.get_database("assignments_data")
    leftover = (await db.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'a_mayors%'")).rows
    assert leftover == []
    assert await ds.get_query("assignments_data", "submit_mayors") is None
    assert await registry.get(ds, "mayors") is None


@pytest.mark.asyncio
async def test_insert_tasks_and_submit_flow(tmp_path):
    ds = make_ds(tmp_path)
    await ds.invoke_startup()
    defn = tasks_defn()
    await creator.create_assignment(ds, defn, {"id": "alice"})
    await creator.insert_tasks(ds, defn, [
        {"city": "Boston", "state": "MA"}, {"city": "Chicago", "state": "IL"}])
    # anonymous read via the stored query endpoint
    r = await ds.client.get(
        "/assignments_data/next_task_mayors.json?_shape=array&seen=")
    assert r.status_code == 200 and r.json()[0]["city"] in ("Boston", "Chicago")
    # anonymous write
    r = await ds.client.post("/assignments_data/submit_mayors.json?_json=1", json={
        "task_id": 1, "records_page": "https://x.gov",
        "records_page_missing": 0, "topics": "[]"})
    assert r.status_code in (200, 201)
    count = (await ds.get_database("assignments_data").execute(
        "SELECT COUNT(*) FROM a_mayors_responses")).first()[0]
    assert count == 1
```

- [ ] **Step 2: Run to verify failure** — ImportError.

- [ ] **Step 3: Implement creator.py**

```python
"""Create/destroy all artifacts for an assignment. Creation is all-or-nothing:
on any failure, everything already created for that slug is destroyed."""
from datasette import stored_queries

from datasette_apps.registry import Registry as AppsRegistry

from . import registry
from .render import render_app_html
from .schema import build_ddl, build_queries, drop_ddl
from . import get_data_db_name


class CreationError(Exception):
    pass


async def _create_app(datasette, defn, actor_id, db_name, query_names):
    apps = AppsRegistry(datasette)
    app = await apps.create_stored_app(
        actor_id,
        defn["name"],
        (defn.get("instructions") or "")[:200],
        render_app_html(defn, db_name),
        is_private=False,
        sql_databases=[],
        stored_queries=[f"{db_name}/{q}" for q in query_names],
    )
    # create_stored_app returns the app dict or id — inspect the datasette-apps
    # registry source and normalize to the id string here.
    return app["id"] if isinstance(app, dict) else app


async def create_assignment(datasette, defn, actor):
    db_name = get_data_db_name(datasette)
    db = datasette.get_database(db_name)
    slug = defn["slug"]
    if await registry.get(datasette, slug):
        raise CreationError(f"An assignment with slug {slug!r} already exists")
    created_queries, app_id = [], None
    try:
        for stmt in build_ddl(defn):
            await db.execute_write(stmt)
        await seed_config(datasette, defn)
        queries = build_queries(defn, db_name)
        for q in queries.values():
            await stored_queries.add_query(
                datasette, db_name, q["name"], q["sql"],
                is_write=q["is_write"],
            )
            created_queries.append(q["name"])
        app_id = await _create_app(
            datasette, defn, (actor or {}).get("id") or "root",
            db_name, [q["name"] for q in queries.values()])
        await registry.create(datasette, defn, (actor or {}).get("id") or "root",
                              app_id)
        return await registry.get(datasette, slug)
    except Exception as e:
        await _cleanup(datasette, defn, created_queries, app_id)
        raise CreationError(str(e)) from e


async def seed_config(datasette, defn):
    db = datasette.get_database(get_data_db_name(datasette))
    slug = defn["slug"]
    if defn["mode"] == "tasks":
        await db.execute_write(
            f"INSERT INTO a_{slug}_config (key, value) VALUES "
            f"('responses_per_task', ?)", [str(defn["responses_per_task"])])
    await db.execute_write(
        f"INSERT INTO a_{slug}_config (key, value) VALUES ('status', 'open')")


async def insert_tasks(datasette, defn, rows):
    db = datasette.get_database(get_data_db_name(datasette))
    cols = defn["task_columns"]
    col_list = ", ".join(cols)
    placeholders = ", ".join("?" for _ in cols)
    for row in rows:
        await db.execute_write(
            f"INSERT INTO a_{defn['slug']}_tasks ({col_list}) "
            f"VALUES ({placeholders})",
            [row.get(c, "") for c in cols])


async def _cleanup(datasette, defn, created_queries, app_id):
    db_name = get_data_db_name(datasette)
    db = datasette.get_database(db_name)
    for stmt in drop_ddl(defn["slug"], defn["mode"]):
        try:
            await db.execute_write(stmt)
        except Exception:
            pass
    for name in created_queries:
        try:
            await stored_queries.remove_query(datasette, db_name, name)
        except Exception:
            pass
    if app_id:
        try:
            apps = AppsRegistry(datasette)
            await apps.delete_app(app_id, actor_id="root")  # verify method name
        except Exception:
            pass
    try:
        await registry.delete(datasette, defn["slug"])
    except Exception:
        pass


async def destroy_assignment(datasette, slug):
    row = await registry.get(datasette, slug)
    if not row:
        return
    defn = row["definition"]
    queries = build_queries(defn, get_data_db_name(datasette))
    await _cleanup(datasette, defn, [q["name"] for q in queries.values()],
                   row["app_id"])
```

Verify against the actual `stored_queries.add_query` and datasette-apps `Registry` signatures (both named in Global Constraints references) and adjust argument names — the test suite is the arbiter.

- [ ] **Step 4: Run** — PASS (expect 1-2 rounds of signature adjustment; document what the real signatures were in the report).

- [ ] **Step 5: Commit** — `git commit -m "feat(plugin): assignment creation orchestration with rollback (TDD)"`

---

### Task 7: Privacy — permission_resources_sql hook (TDD)

**Files:**
- Modify: `plugins/datasette-assignments/datasette_assignments/__init__.py`
- Create: `plugins/datasette-assignments/tests/test_permissions_views.py` (permissions half)

**Interfaces:**
- Produces: `@hookimpl def permission_resources_sql(datasette, actor, action)` returning deny rows so that: (a) `view-table` on any table named `a_%_responses` in the data DB is denied unless the actor owns the matching registry row or is root; (b) `execute-sql` on the data DB is denied for everyone except root. Implementer MUST read `.venv/lib/python3.11/site-packages/datasette_apps/permissions.py` first and mirror its `PermissionSQL` construction exactly (import path, columns `parent, child, allow, reason`, and how actor id is parameterized).

- [ ] **Step 1: Write failing tests**

```python
import pytest
import sqlite3
from datasette.app import Datasette
from datasette_assignments import creator
from datasette_assignments.schema import validate_definition
from tests.test_schema import tasks_defn


async def build_instance(tmp_path):
    db_path = str(tmp_path / "assignments_data.db")
    sqlite3.connect(db_path).close()
    ds = Datasette([db_path])
    await ds.invoke_startup()
    await creator.create_assignment(ds, tasks_defn(), {"id": "alice"})
    await creator.insert_tasks(ds, tasks_defn(), [{"city": "Boston", "state": "MA"}])
    return ds


@pytest.mark.asyncio
async def test_responses_table_private_tasks_table_public(tmp_path):
    ds = await build_instance(tmp_path)
    anon_resp = await ds.client.get("/assignments_data/a_mayors_responses.json")
    assert anon_resp.status_code == 403
    anon_tasks = await ds.client.get("/assignments_data/a_mayors_tasks.json")
    assert anon_tasks.status_code == 200
    owner_cookie = {"ds_actor": ds.client.actor_cookie({"id": "alice"})}
    other_cookie = {"ds_actor": ds.client.actor_cookie({"id": "bob"})}
    root_cookie = {"ds_actor": ds.client.actor_cookie({"id": "root"})}
    assert (await ds.client.get("/assignments_data/a_mayors_responses.json",
                                cookies=owner_cookie)).status_code == 200
    assert (await ds.client.get("/assignments_data/a_mayors_responses.json",
                                cookies=other_cookie)).status_code == 403
    assert (await ds.client.get("/assignments_data/a_mayors_responses.json",
                                cookies=root_cookie)).status_code == 200


@pytest.mark.asyncio
async def test_raw_sql_denied_on_data_db(tmp_path):
    ds = await build_instance(tmp_path)
    r = await ds.client.get(
        "/assignments_data/-/query.json?sql=SELECT+*+FROM+a_mayors_responses")
    assert r.status_code == 403
    root_cookie = {"ds_actor": ds.client.actor_cookie({"id": "root"})}
    r = await ds.client.get(
        "/assignments_data/-/query.json?sql=SELECT+1",
        cookies=root_cookie)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_stored_queries_still_work_anonymously(tmp_path):
    ds = await build_instance(tmp_path)
    r = await ds.client.get(
        "/assignments_data/progress_mayors.json?_shape=array")
    assert r.status_code == 200 and r.json()[0]["total"] == 1
```

- [ ] **Step 2: Run to verify failure** — the private-table assertions fail (200 where 403 expected).

- [ ] **Step 3: Implement the hook** in `__init__.py`, mirroring datasette-apps' PermissionSQL usage: for `view-table`, emit a deny row (`allow = 0`) for every `a_<slug>_responses` table whose registry owner is NOT the actor (SQL against `assignments_registry`, parameterized actor id; root exempted in Python before building the SQL); for `execute-sql`, emit a deny row for the data DB when actor is not root. Return `None` for all other actions.

- [ ] **Step 4: Run** — full plugin suite PASSES. Also re-run phase-1 tests (`.venv/bin/pytest tests/ -q`) — the hook must not break the census demo instance behavior (its DBs are `census`/`assignments`, not the data DB; nothing matches `a_%_responses` there).

- [ ] **Step 5: Commit** — `git commit -m "feat(plugin): private-by-default responses via permission_resources_sql (TDD)"`

---

### Task 8: Views — list, wizard, preview, manage (TDD integration)

**Files:**
- Create: `plugins/datasette-assignments/datasette_assignments/views.py`, `templates/assignments_list.html`, `templates/assignments_new.html`, `templates/assignments_manage.html`, `static/builder.js`, `static/builder.css`
- Modify: `plugins/datasette-assignments/datasette_assignments/__init__.py` (register_routes, menu_links), `tests/test_permissions_views.py` (append views half)

**Interfaces:**
- Routes (all registered via `register_routes`): `GET /-/assignments` (list, signed-in only → 403 anon); `GET|POST /-/assignments/new` (wizard; POST field `definition` = JSON string + `tasks_csv` = raw CSV text; on success redirect to manage page); `POST /-/assignments/preview` (body: definition JSON → returns rendered preview HTML, signed-in only); `GET /-/assignments/<slug>` (manage; owner/root only); `POST /-/assignments/<slug>/toggle-status` (open↔closed: rewrites the config row); `POST /-/assignments/<slug>/target` (update responses_per_task config); `POST /-/assignments/<slug>/response-public` (params id, public=0|1: updates `is_public`); `POST /-/assignments/<slug>/delete` (destroy_assignment; requires confirm=slug field); `GET /-/assignments/<slug>/export.csv` (owner full-response CSV).
- The wizard flow: browser-side `builder.js` maintains the fields list UI (palette buttons add field editors; per-field label/help/required/gallery/options/companion inputs; remove + move up/down) and serializes to the hidden `definition` JSON input on submit. Server: parse CSV (`csv.DictReader` on submitted text; headers sanitized via `sanitize_identifier` with dedupe; ≤10000 rows else error), inject sanitized headers as `task_columns`, `validate_definition`, `create_assignment`, `insert_tasks`. Validation errors re-render the form with the error list and the user's JSON preserved.
- Manage page shows: progress numbers (query the data DB directly server-side as the owner), open/close button, target form (tasks mode), the app link (`/-/apps/<app_id>`), public view link when it exists, latest 200 responses as a table with per-row public/private toggle buttons, delete form.
- CSV export streams `SELECT * FROM a_<slug>_responses` as CSV with proper text/csv content type.
- `menu_links` hook: "Assignments" → `/-/assignments` for signed-in actors only.
- All POSTs go through datasette's CSRF (use `request.post_vars()`; templates include `{{ csrftoken() }}`).

- [ ] **Step 1: Append failing integration tests**

```python
import json


ALICE = {"id": "alice"}


def defn_payload(slug="wizard_test", mode="form"):
    d = {
        "slug": slug, "name": "Wizard Test", "mode": mode, "instructions": "Go",
        "responses_per_task": 2, "task_columns": [], "task_title_column": None,
        "task_image_column": None,
        "fields": [{"kind": "input", "type": "text", "id": "answer",
                    "label": "Answer", "help": "", "required": True,
                    "gallery": True, "missing_companion": False, "options": []}],
    }
    if mode == "tasks":
        d["task_title_column"] = "city"
    return d


async def signed_in_post(ds, path, data, actor=ALICE):
    cookies = {"ds_actor": ds.client.actor_cookie(actor)}
    # fetch csrftoken from the new page
    page = await ds.client.get("/-/assignments/new", cookies=cookies)
    token = page.cookies.get("ds_csrftoken") or ""
    data = dict(data, csrftoken=token)
    cookies.update(page.cookies)
    return await ds.client.post(path, data=data, cookies=cookies)


@pytest.mark.asyncio
async def test_list_requires_signin(tmp_path):
    ds = await build_instance(tmp_path)
    assert (await ds.client.get("/-/assignments")).status_code == 403
    cookies = {"ds_actor": ds.client.actor_cookie(ALICE)}
    assert (await ds.client.get("/-/assignments", cookies=cookies)).status_code == 200


@pytest.mark.asyncio
async def test_wizard_creates_form_assignment(tmp_path):
    ds = await build_instance(tmp_path)
    r = await signed_in_post(ds, "/-/assignments/new", {
        "definition": json.dumps(defn_payload()), "tasks_csv": ""})
    assert r.status_code in (302, 200)
    from datasette_assignments import registry as reg
    assert (await reg.get(ds, "wizard_test"))["owner_id"] == "alice"


@pytest.mark.asyncio
async def test_wizard_tasks_mode_with_csv(tmp_path):
    ds = await build_instance(tmp_path)
    payload = defn_payload(slug="csv_test", mode="tasks")
    r = await signed_in_post(ds, "/-/assignments/new", {
        "definition": json.dumps(payload),
        "tasks_csv": "City!,State\nBoston,MA\nChicago,IL\n"})
    assert r.status_code in (302, 200)
    db = ds.get_database("assignments_data")
    rows = (await db.execute("SELECT city, state FROM a_csv_test_tasks")).rows
    assert len(rows) == 2  # headers sanitized: City! -> city


@pytest.mark.asyncio
async def test_manage_owner_only_and_toggles(tmp_path):
    ds = await build_instance(tmp_path)  # creates 'mayors' owned by alice
    anon = await ds.client.get("/-/assignments/mayors")
    assert anon.status_code == 403
    bob = {"ds_actor": ds.client.actor_cookie({"id": "bob"})}
    assert (await ds.client.get("/-/assignments/mayors", cookies=bob)).status_code == 403
    alice_c = {"ds_actor": ds.client.actor_cookie(ALICE)}
    assert (await ds.client.get("/-/assignments/mayors", cookies=alice_c)).status_code == 200
    # close it, then anonymous submit must be rejected (0 rows inserted)
    await signed_in_post(ds, "/-/assignments/mayors/toggle-status", {})
    await ds.client.post("/assignments_data/submit_mayors.json?_json=1", json={
        "task_id": 1, "records_page": "https://x.gov",
        "records_page_missing": 0, "topics": "[]"})
    count = (await ds.get_database("assignments_data").execute(
        "SELECT COUNT(*) FROM a_mayors_responses")).first()[0]
    assert count == 0


@pytest.mark.asyncio
async def test_response_public_toggle_and_export(tmp_path):
    ds = await build_instance(tmp_path)
    await ds.client.post("/assignments_data/submit_mayors.json?_json=1", json={
        "task_id": 1, "records_page": "https://x.gov",
        "records_page_missing": 0, "topics": "[]"})
    await signed_in_post(ds, "/-/assignments/mayors/response-public",
                         {"id": "1", "public": "1"})
    pub = await ds.client.get(
        "/assignments_data/a_mayors_public.json?_shape=array")
    assert pub.status_code == 200 and len(pub.json()) == 1
    alice_c = {"ds_actor": ds.client.actor_cookie(ALICE)}
    csv_r = await ds.client.get("/-/assignments/mayors/export.csv",
                                cookies=alice_c)
    assert csv_r.status_code == 200 and "records_page" in csv_r.text
    assert (await ds.client.get("/-/assignments/mayors/export.csv")).status_code == 403
```

- [ ] **Step 2: Run to verify failure** — 404s on the routes.

- [ ] **Step 3: Implement** `views.py` + templates + `builder.js`/`builder.css` + hook registrations. Views use `datasette.render_template` with the plugin's templates; permission checks at the top of every handler (`request.actor` present; manage handlers additionally owner-or-root against the registry row). Templates extend datasette's `base.html`. `builder.js` contract: palette `<button data-type=...>` per type + Header/Paragraph; each added field renders an editor card with inputs named per the definition shape; options editor (Add Option) shown only for select/checkbox_group; gallery + required + companion checkboxes (companion only shown for text/textarea/url/email); serialize on submit into `#definition-json`; "Preview" button POSTs the JSON to `/-/assignments/preview` and srcdoc's the response into a sandboxed iframe (`sandbox="allow-scripts"`). Keep builder.js dependency-free vanilla JS.

- [ ] **Step 4: Run the full plugin suite + phase-1 suite** — all PASS. Manual check: run the demo stack locally with an `assignments_data.db` added, log in as root, click through wizard → create → app loads → submit → manage page shows the response → toggle public → public view shows it. Record results in the report.

```bash
sqlite3 assignments_data.db "VACUUM;"  # create empty file
export DATASETTE_ROOT_PASSWORD_HASH=$(.venv/bin/python -c "from datasette_auth_passwords.utils import hash_password; print(hash_password('localdev'))")
.venv/bin/datasette serve census.db assignments.db assignments_data.db \
  --internal internal.db -c datasette.yaml --secret dev -p 8001
```

- [ ] **Step 5: Commit** — `git commit -m "feat(plugin): builder wizard, list, manage, preview, export views (TDD)"`

---

### Task 9: Demo deployment integration

**Files:**
- Modify: `Dockerfile`, `deploy/entrypoint.sh`, `datasette.yaml`, `requirements.txt` (comment only), `fly.toml` (none expected)
- Create: `assignments_data.db` (empty seed, committed)

**Steps:**

- [ ] **Step 1:** Create and commit the empty seed: `sqlite3 assignments_data.db "VACUUM;"`.
- [ ] **Step 2:** Dockerfile: `COPY plugins/ ./plugins/` before the pip install and change the install line to `RUN pip install --no-cache-dir -r requirements.txt -e ./plugins/datasette-assignments`; add `assignments_data.db` to the seed COPY line. entrypoint.sh: add `assignments_data.db` to the seed loop AND to the `datasette serve` database list (`/data/assignments_data.db`).
- [ ] **Step 3:** Local end-to-end using the production config (same commands as Task 8 Step 4 but with `-c datasette.yaml`); verify: wizard works as root; anonymous 403 on a responses table; anonymous 403 on raw SQL against `assignments_data`; census demo app still works (its DB is unaffected).
- [ ] **Step 4:** Deploy: `fly deploy --ha=false`. The volume already has the phase-1 DBs; `assignments_data.db` seeds fresh. Smoke test on production: create a real assignment as root through the live wizard (a small "Feedback on this demo" form-mode assignment — 1 textarea field, gallery on), submit anonymously, toggle it public, confirm the public view renders, confirm `/-/apps` lists the new app, confirm anonymous 403 on its responses table. Record every URL + status in the report.
- [ ] **Step 5:** Commit — `git commit -m "feat: ship datasette-assignments plugin to the demo deployment"`.

---

### Task 10: Documentation

**Files:**
- Create: `plugins/datasette-assignments/README.md`
- Modify: `NOTES.md`, `README.md`, `TUTORIAL.md`

**Steps:**

- [ ] **Step 1:** Plugin README: what it is, install (`pip install -e`), config (`plugins.datasette-assignments.database`), the two modes, the privacy model (private-by-default, Gallery fields, is_public toggle, public view; execute-sql denial and why), multi-user note (any auth plugin supplying actors works; with datasette-auth-passwords add one `<user>_password_hash` per creator), routes table, "what gets generated" table (so users know the artifacts are theirs), uninstall behavior (assignments keep working; builder/permission enforcement goes away — WARN: removing the plugin removes the privacy denial, so responses tables become visible if instance allow permits; state this prominently).
- [ ] **Step 2:** NOTES.md: new section "The assignments plugin (phase 2)" covering: registry + permission hook live in the internal DB; execute-sql is denied on `assignments_data` by the plugin (root excepted) — this is what makes private responses real; stored-query-only generated apps; the uninstall privacy warning.
- [ ] **Step 3:** Root README: add plugin to the layout table + one paragraph + link to plugin README. TUTORIAL.md: add a short "The no-code way" callout box after the intro pointing readers to the plugin README (the hand-built path remains the tutorial's teaching spine).
- [ ] **Step 4:** Accuracy pass: every path/route/claim in the new docs checked against the shipped code. Commit — `git commit -m "docs: datasette-assignments plugin documentation"`.

---

## Self-Review Notes

- **Spec coverage:** two modes → Tasks 3/5/6/8; palette incl. Header/Paragraph + companions → Tasks 2/5; privacy (private tables, execute-sql denial, Gallery, is_public toggle, public view) → Tasks 3/7/8; generator artifacts via public APIs → Task 6; wizard + preview + list + manage + export → Task 8; registry in internal DB → Task 4; packaging in-repo → Task 1; demo deployment → Task 9; docs incl. uninstall warning → Task 10. Regeneration/editing/PyPI out of scope per spec.
- **Type consistency:** definition dict shape defined once (header) and used by all tasks; `build_queries` return shape consumed by creator Task 6; `response_columns` used by render Task 5 and creator submit params; route list in Task 8 matches tests.
- **Known judgment calls:** `add_query`/`create_stored_app`/`delete_app` exact signatures verified at implementation time against the pinned packages (tests are the arbiter; named as explicit verification steps). `app_template.html` and `builder.js` are specified by behavioral contract + reference files rather than inline code — they are UI generalizations of committed, reviewed phase-1 files (`apps/census.html`, TUTORIAL.md recipes); their correctness is enforced by the structural tests in Tasks 5/8 and the manual click-through in Tasks 8/9.
