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
