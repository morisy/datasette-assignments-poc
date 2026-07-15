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
