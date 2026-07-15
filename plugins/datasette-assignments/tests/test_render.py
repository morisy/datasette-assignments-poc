import pytest
import sys
import os

# Import helpers from test_schema — shared builders, not duplicated.
sys.path.insert(0, os.path.dirname(__file__))
from test_schema import make_defn, tasks_defn

from datasette_assignments.schema import validate_definition
from datasette_assignments.render import render_app_html


def test_tasks_mode_html_structure():
    html = render_app_html(tasks_defn(), "assignments_data")
    assert "datasette.query(" not in html
    for needle in ["storedQuery", "submit_mayors", "next_task_mayors",
                   "progress_mayors", "records_page_missing",
                   "Number.isInteger", "tasks complete", "Skip"]:
        assert needle in html, needle
    assert "topics" in html and "police" in html
    assert "<h3" in html  # header block rendered
    # required fields carry the red-asterisk marker in the rendering code
    assert "req-mark" in html


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


def test_preview_stub_is_valid_javascript():
    # Autoescape artifacts (&#34; etc.) or leftover Jinja syntax inside the
    # stub script are JS syntax errors — the stub then silently never runs
    # and the app dies at runtime with "datasette is not defined".
    for defn in (tasks_defn(), validate_definition(make_defn(slug="tips"))):
        html = render_app_html(defn, "assignments_data", preview=True)
        assert "{{" not in html and "{%" not in html
        start = html.index("window.datasette = ")
        stub = html[start:html.index("</script>", start)]
        assert "&#34;" not in stub and "&quot;" not in stub and "&amp;" not in stub
        if defn["mode"] == "tasks":
            # sample task JSON must be raw JSON, not HTML-entity-escaped
            assert '{"id": 1' in stub
