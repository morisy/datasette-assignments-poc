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
