"""Tests for the public gallery page (Task 2, v0.3 wave)."""
import json
import pytest
import sqlite3
from datasette.app import Datasette
from datasette_assignments import creator, registry as reg
from datasette_assignments.schema import validate_definition


# ── Helpers ───────────────────────────────────────────────────────────────────

def gallery_defn(slug="demo_survey"):
    """Definition with one gallery field and one non-gallery field."""
    return validate_definition({
        "slug": slug,
        "name": "Demo Survey",
        "mode": "form",
        "instructions": "Please fill this in.",
        "responses_per_task": 3,
        "task_columns": [],
        "task_title_column": None,
        "task_image_column": None,
        "fields": [
            {
                "kind": "input", "type": "text", "id": "public_note",
                "label": "Public Note", "help": "", "required": True,
                "gallery": True, "missing_companion": False, "options": [],
            },
            {
                "kind": "input", "type": "text", "id": "private_detail",
                "label": "Private Detail", "help": "", "required": False,
                "gallery": False, "missing_companion": False, "options": [],
            },
        ],
    })


def no_gallery_defn(slug="no_gal"):
    """Definition with NO gallery fields."""
    return validate_definition({
        "slug": slug,
        "name": "No Gallery",
        "mode": "form",
        "instructions": "Nothing is public here.",
        "responses_per_task": 3,
        "task_columns": [],
        "task_title_column": None,
        "task_image_column": None,
        "fields": [
            {
                "kind": "input", "type": "text", "id": "secret",
                "label": "Secret", "help": "", "required": True,
                "gallery": False, "missing_companion": False, "options": [],
            },
        ],
    })


async def build_gallery_instance(tmp_path):
    db_path = str(tmp_path / "assignments_data.db")
    sqlite3.connect(db_path).close()
    ds = Datasette([db_path])
    await ds.invoke_startup()
    defn = gallery_defn()
    await creator.create_assignment(ds, defn, {"id": "alice"})
    return ds


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gallery_anon_200_shows_public_gallery_value(tmp_path):
    """Anonymous GET /-/assignments/<slug>/gallery returns 200 and shows
    gallery field value from is_public=1 rows."""
    ds = await build_gallery_instance(tmp_path)
    db = ds.get_database("assignments_data")
    # Insert a public row
    await db.execute_write(
        "INSERT INTO a_demo_survey_responses"
        " (public_note, private_detail, is_public, submitted_at)"
        " VALUES (?, ?, ?, datetime('now'))",
        ["Hello world", "secret stuff", 1],
    )
    r = await ds.client.get("/-/assignments/demo_survey/gallery")
    assert r.status_code == 200
    assert "Hello world" in r.text       # gallery field value present
    assert "Public Note" in r.text       # gallery field label present


@pytest.mark.asyncio
async def test_gallery_non_gallery_value_absent(tmp_path):
    """Non-gallery field value must NOT appear in gallery page."""
    ds = await build_gallery_instance(tmp_path)
    db = ds.get_database("assignments_data")
    await db.execute_write(
        "INSERT INTO a_demo_survey_responses"
        " (public_note, private_detail, is_public, submitted_at)"
        " VALUES (?, ?, ?, datetime('now'))",
        ["Visible value", "TOP SECRET", 1],
    )
    r = await ds.client.get("/-/assignments/demo_survey/gallery")
    assert r.status_code == 200
    assert "TOP SECRET" not in r.text
    assert "Private Detail" not in r.text


@pytest.mark.asyncio
async def test_gallery_private_rows_absent(tmp_path):
    """is_public=0 rows must NOT appear in gallery."""
    ds = await build_gallery_instance(tmp_path)
    db = ds.get_database("assignments_data")
    # Public row
    await db.execute_write(
        "INSERT INTO a_demo_survey_responses"
        " (public_note, private_detail, is_public, submitted_at)"
        " VALUES (?, ?, ?, datetime('now'))",
        ["I am public", "x", 1],
    )
    # Private row
    await db.execute_write(
        "INSERT INTO a_demo_survey_responses"
        " (public_note, private_detail, is_public, submitted_at)"
        " VALUES (?, ?, ?, datetime('now'))",
        ["SHOULD NOT APPEAR", "y", 0],
    )
    r = await ds.client.get("/-/assignments/demo_survey/gallery")
    assert r.status_code == 200
    assert "I am public" in r.text
    assert "SHOULD NOT APPEAR" not in r.text


@pytest.mark.asyncio
async def test_gallery_404_unknown_slug(tmp_path):
    """Unknown slug returns 404."""
    ds = await build_gallery_instance(tmp_path)
    r = await ds.client.get("/-/assignments/does_not_exist/gallery")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_gallery_404_no_gallery_fields(tmp_path):
    """Assignment with no gallery-flagged fields returns 404."""
    db_path = str(tmp_path / "assignments_data.db")
    sqlite3.connect(db_path).close()
    ds = Datasette([db_path])
    await ds.invoke_startup()
    defn = no_gallery_defn()
    await creator.create_assignment(ds, defn, {"id": "alice"})
    r = await ds.client.get("/-/assignments/no_gal/gallery")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_gallery_empty_state(tmp_path):
    """Gallery with no public rows shows empty-state message."""
    ds = await build_gallery_instance(tmp_path)
    r = await ds.client.get("/-/assignments/demo_survey/gallery")
    assert r.status_code == 200
    assert "Nothing published yet" in r.text


@pytest.mark.asyncio
async def test_gallery_pagination_page2(tmp_path):
    """Page 2 returns 200 and shows the overflow row."""
    ds = await build_gallery_instance(tmp_path)
    db = ds.get_database("assignments_data")
    # Insert 51 public rows — page 1 shows 50, page 2 shows 1
    for i in range(51):
        await db.execute_write(
            "INSERT INTO a_demo_survey_responses"
            " (public_note, private_detail, is_public, submitted_at)"
            " VALUES (?, ?, ?, datetime('now'))",
            [f"Note {i}", "x", 1],
        )
    r1 = await ds.client.get("/-/assignments/demo_survey/gallery")
    assert r1.status_code == 200
    r2 = await ds.client.get("/-/assignments/demo_survey/gallery?page=2")
    assert r2.status_code == 200
    # Page 2 should have exactly one item: "Note 0" (oldest, since ORDER BY id DESC)
    assert "Note 0" in r2.text


@pytest.mark.asyncio
async def test_gallery_url_values_rendered_as_links(tmp_path):
    """Values that look like URLs are rendered as <a> tags."""
    ds = await build_gallery_instance(tmp_path)
    db = ds.get_database("assignments_data")
    await db.execute_write(
        "INSERT INTO a_demo_survey_responses"
        " (public_note, private_detail, is_public, submitted_at)"
        " VALUES (?, ?, ?, datetime('now'))",
        ["https://example.com/foo", "x", 1],
    )
    r = await ds.client.get("/-/assignments/demo_survey/gallery")
    assert r.status_code == 200
    assert 'href="https://example.com/foo"' in r.text
    assert 'rel="noopener nofollow"' in r.text


@pytest.mark.asyncio
async def test_gallery_manage_page_has_gallery_link(tmp_path):
    """Manage page shows 'View public gallery' link when gallery fields exist."""
    ds = await build_gallery_instance(tmp_path)
    alice_c = {"ds_actor": ds.client.actor_cookie({"id": "alice"})}
    r = await ds.client.get("/-/assignments/demo_survey", cookies=alice_c)
    assert r.status_code == 200
    assert "gallery" in r.text.lower()
    assert "demo_survey/gallery" in r.text
