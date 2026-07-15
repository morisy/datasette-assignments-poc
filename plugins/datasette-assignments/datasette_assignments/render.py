import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .schema import response_columns

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


def _safe_json(obj):
    """JSON-encode obj with < > & Unicode-escaped so it embeds safely in <script>.

    \\u003c / \\u003e / \\u0026 are valid JSON string escapes and are decoded
    transparently by JS — they never appear as literal HTML angle brackets.
    """
    return (json.dumps(obj)
            .replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e"))


def render_app_html(defn, db_name, preview=False):
    slug = defn["slug"]
    has_gallery = any(
        f.get("gallery") for f in defn.get("fields", []) if f.get("kind") == "input"
    )
    template = _env.get_template("app_template.html")
    return template.render(
        defn=defn,
        db_name=db_name,
        preview=preview,
        has_gallery=has_gallery,
        response_cols=response_columns(defn),
        defn_json=_safe_json(defn),
        sample_task_json=_safe_json(
            {"id": 1, **{c: f"Sample {c}" for c in defn["task_columns"]}}
        ),
        # Pre-built query names so they appear as literals in the HTML
        q_submit=f"submit_{slug}",
        q_progress=f"progress_{slug}",
        q_next_task=f"next_task_{slug}" if defn["mode"] == "tasks" else None,
    )
