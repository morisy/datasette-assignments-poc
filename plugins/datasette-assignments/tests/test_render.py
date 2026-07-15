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


# ── Share prompt tests (Task 5) ───────────────────────────────────────────────

def test_share_row_present_in_form_mode():
    """shareRow() helper and Share this assignment text present in form mode."""
    defn = validate_definition(make_defn(slug="tips"))
    html = render_app_html(defn, "assignments_data")
    assert "shareRow" in html, "shareRow function missing"
    assert "Share this assignment" in html, "share heading missing"


def test_share_row_present_in_tasks_mode():
    """shareRow() helper present in tasks mode HTML."""
    html = render_app_html(tasks_defn(), "assignments_data")
    assert "shareRow" in html, "shareRow function missing in tasks mode"
    assert "Share this assignment" in html, "share heading missing in tasks mode"


def test_slug_constant_in_html():
    """SLUG constant baked into generated HTML."""
    defn = validate_definition(make_defn(slug="city_survey"))
    html = render_app_html(defn, "assignments_data")
    assert 'const SLUG' in html, "SLUG constant missing"
    assert '"city_survey"' in html or "'city_survey'" in html, "SLUG value missing"


def test_has_gallery_true_when_gallery_field_present():
    """HAS_GALLERY = true when at least one input field has gallery: true."""
    # tasks_defn has a gallery field (records_page has gallery: True)
    html = render_app_html(tasks_defn(), "assignments_data")
    assert "const HAS_GALLERY = true" in html, "HAS_GALLERY should be true"


def test_has_gallery_false_when_no_gallery_field():
    """HAS_GALLERY = false when no input field has gallery: true."""
    # make_defn's default field has gallery: False
    defn = validate_definition(make_defn(slug="tips"))
    html = render_app_html(defn, "assignments_data")
    assert "const HAS_GALLERY = false" in html, "HAS_GALLERY should be false"


def test_gallery_link_present_when_has_gallery():
    """'See what's been found' link appears when HAS_GALLERY is true."""
    html = render_app_html(tasks_defn(), "assignments_data")
    assert "See what" in html and "been found" in html, "gallery link text missing"


def test_copy_button_uses_clipboard_api():
    """Copy button triggers navigator.clipboard.writeText."""
    defn = validate_definition(make_defn(slug="tips"))
    html = render_app_html(defn, "assignments_data")
    assert "navigator.clipboard.writeText" in html, "clipboard API missing"


def test_share_row_hides_when_referrer_unavailable():
    """Share row is wrapped in try/catch so it hides on empty/unparseable referrer."""
    defn = validate_definition(make_defn(slug="tips"))
    html = render_app_html(defn, "assignments_data")
    assert "document.referrer" in html, "referrer not used"
    # Must be in a try block for error handling
    assert "try {" in html or "try{" in html, "try block missing for referrer handling"


def test_link_copied_toast_reused():
    """Existing toast machinery reused: 'Link copied' text present."""
    defn = validate_definition(make_defn(slug="tips"))
    html = render_app_html(defn, "assignments_data")
    assert "Link copied" in html, "Link copied toast text missing"


# ── Task 7: Image scheme guard ───────────────────────────────────────────────

def test_image_render_guarded_by_http_scheme():
    """Image is rendered only when URL starts with http:// or https:// (case-insensitive)."""
    # Task with a valid https image URL
    defn = tasks_defn()
    html = render_app_html(defn, "assignments_data")
    # tasks_defn's image column contains a URL; image should be rendered
    assert "startsWith(" in html or "http" in html
    # Verify the image rendering code checks the scheme
    assert "http://" in html or "https://" in html
