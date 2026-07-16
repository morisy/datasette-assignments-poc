"""Definition validation and identifier sanitization.

Slugs, field ids, and CSV headers all become SQL identifiers. The rule is
whitelist-only: ^[a-z][a-z0-9_]{0,39}$ — we never escape or quote identifiers.
"""
import re
from urllib.parse import urlsplit

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
TOKEN_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")
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
    # responses_per_task: ABSENT/None → 3; PRESENT but invalid → error listed
    rpt = d.get("responses_per_task")
    if rpt is None:
        d["responses_per_task"] = 3
    else:
        try:
            d["responses_per_task"] = int(rpt)
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

    # ── Token ({{column}}) validation ────────────────────────────────────────
    task_columns = d.get("task_columns") or []
    mode = d.get("mode")
    # Collect (surface_name, text) pairs
    surfaces = [("instructions", d.get("instructions") or "")]
    for f in fields:
        kind = f.get("kind")
        if kind in ("header", "paragraph"):
            surfaces.append((f"{kind} block", f.get("text") or ""))
        elif kind == "input":
            fid = f.get("id") or ""
            surfaces.append((f"label of {fid}", f.get("label") or ""))
            surfaces.append((f"help of {fid}", f.get("help") or ""))
    for surface, text in surfaces:
        for tok in TOKEN_RE.findall(text):
            if mode == "tasks":
                if tok not in task_columns:
                    avail = ", ".join(task_columns) if task_columns else "(none)"
                    errors.append(
                        f"unknown variable {{{{{tok}}}}} in {surface} "
                        f"— available: {avail}"
                    )
            else:
                errors.append(
                    f"variables like {{{{{tok}}}}} only work in task-list "
                    f"assignments (found in {surface})"
                )

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
    if mode == "tasks":
        title_col = defn.get("task_title_column") or defn["task_columns"][0]
        # Primary input-field columns only — exclude _missing companions
        input_col_ids = [f["id"] for f in _input_fields(defn)]
        per_col_exprs = []
        for col in input_col_ids:
            per_col_exprs.append(
                f"  (SELECT r.{col} FROM a_{slug}_responses r"
                f" WHERE r.task_id = t.id"
                f" GROUP BY r.{col} ORDER BY COUNT(*) DESC, r.{col} LIMIT 1)"
                f" AS {col}_majority"
            )
            per_col_exprs.append(
                f"  (SELECT COUNT(DISTINCT r.{col}) FROM a_{slug}_responses r"
                f" WHERE r.task_id = t.id)"
                f" AS {col}_distinct"
            )
        exprs_sql = ",\n".join(per_col_exprs)
        stmts.append(
            f"CREATE VIEW a_{slug}_agreement AS\n"
            f"SELECT t.id AS task_id, t.{title_col} AS task_title,\n"
            f"  (SELECT COUNT(*) FROM a_{slug}_responses r WHERE r.task_id = t.id)"
            f" AS response_count,\n"
            f"{exprs_sql}\n"
            f"FROM a_{slug}_tasks t"
        )
    return stmts


def drop_ddl(slug, mode):
    stmts = [f"DROP VIEW IF EXISTS a_{slug}_public"]
    if mode == "tasks":
        stmts.append(f"DROP VIEW IF EXISTS a_{slug}_agreement")
        stmts.append(f"DROP TRIGGER IF EXISTS a_{slug}_mark_done")
    stmts.append(f"DROP TABLE IF EXISTS a_{slug}_responses")
    stmts.append(f"DROP TABLE IF EXISTS a_{slug}_config")
    if mode == "tasks":
        stmts.append(f"DROP TABLE IF EXISTS a_{slug}_tasks")
    return stmts


def merge_editable(stored, posted):
    """Merge only editable fields from posted definition into stored definition.

    Editable: name, instructions, field labels, help text, header/paragraph text,
    and adding options to select/checkbox_group (existing options are preserved).

    Raises DefinitionError if posted contains structural changes:
    - different mode
    - different slug
    - different field count or field ids/types do not match stored
    """
    errors = []

    # Structural checks
    if posted.get("mode") != stored.get("mode"):
        errors.append("mode cannot be changed in edit mode")
    if posted.get("slug") != stored.get("slug"):
        errors.append("slug cannot be changed in edit mode")

    stored_fields = stored.get("fields") or []
    posted_fields = posted.get("fields") or []

    if len(stored_fields) != len(posted_fields):
        errors.append(
            f"field count cannot change in edit mode "
            f"(stored {len(stored_fields)}, posted {len(posted_fields)})"
        )

    if errors:
        raise DefinitionError(errors)

    # Validate field-level structural immutability
    for i, (sf, pf) in enumerate(zip(stored_fields, posted_fields)):
        if sf.get("kind") != pf.get("kind"):
            errors.append(f"field[{i}] kind cannot change in edit mode")
        if sf.get("kind") == "input":
            if sf.get("id") != pf.get("id"):
                errors.append(
                    f"field id cannot change in edit mode "
                    f"(stored {sf.get('id')!r}, posted {pf.get('id')!r})"
                )
            if sf.get("type") != pf.get("type"):
                errors.append(
                    f"field {sf.get('id')!r} type cannot change in edit mode"
                )

    if errors:
        raise DefinitionError(errors)

    # Build merged definition: start from stored, apply editable fields
    merged = dict(stored)
    merged["name"] = posted.get("name") or stored.get("name")
    merged["instructions"] = posted.get("instructions", stored.get("instructions", ""))

    merged_fields = []
    for sf, pf in zip(stored_fields, posted_fields):
        mf = dict(sf)
        if sf.get("kind") in ("header", "paragraph"):
            # Allow updating text of header/paragraph blocks
            mf["text"] = pf.get("text", sf.get("text", ""))
        else:
            # input field: allow label and help updates
            mf["label"] = pf.get("label", sf.get("label", ""))
            mf["help"] = pf.get("help", sf.get("help", ""))
            # For option-based types: allow ADDING options (not removing existing)
            if sf.get("type") in OPTION_TYPES:
                stored_opts = sf.get("options") or []
                posted_opts = pf.get("options") or []
                # posted options must START WITH stored options in order
                # (only appends accepted; reorder/rename/removal is forbidden)
                if posted_opts[:len(stored_opts)] != stored_opts:
                    errors.append(
                        f"field {sf.get('id')!r}: existing options cannot be "
                        f"reordered, renamed, or removed (only appending new "
                        f"options is allowed)"
                    )
                else:
                    appended = posted_opts[len(stored_opts):]
                    seen_opts = set(stored_opts)
                    opt_errors = []
                    for opt in appended:
                        if not isinstance(opt, str) or not opt:
                            opt_errors.append(
                                f"field {sf.get('id')!r}: appended options must "
                                f"be non-empty strings (got {opt!r})"
                            )
                        elif opt in seen_opts:
                            opt_errors.append(
                                f"field {sf.get('id')!r}: duplicate option {opt!r}"
                            )
                        else:
                            seen_opts.add(opt)
                    if opt_errors:
                        errors.extend(opt_errors)
                    else:
                        mf["options"] = list(posted_opts)
        merged_fields.append(mf)

    if errors:
        raise DefinitionError(errors)

    merged["fields"] = merged_fields
    return merged


def extract_image_origins(defn, rows):
    """Return a set of normalized https origins from task_image_column values.

    Skips values that don't start with http:// or https://.
    Raises DefinitionError (accumulated) if any http:// origins are found.
    Returns empty set when there is no task_image_column.
    """
    image_col = defn.get("task_image_column")
    if not image_col:
        return set()
    errors = []
    origins = set()
    for row in rows:
        val = row.get(image_col) or ""
        val = val.strip()
        if not val.startswith("http://") and not val.startswith("https://"):
            continue
        parsed = urlsplit(val)
        if parsed.scheme == "http":
            errors.append(
                f"image hosts must use https (got {parsed.scheme}://{parsed.netloc})"
            )
            continue
        # https origin
        netloc = parsed.netloc.lower()
        origins.add(f"https://{netloc}")
    if errors:
        raise DefinitionError(errors)
    return origins


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
                f"  AND (SELECT value FROM a_{slug}_config WHERE key='status') = 'open'\n"
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
