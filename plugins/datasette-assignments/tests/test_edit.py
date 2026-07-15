"""Tests for the edit assignment (copy-edits only) feature — Task 1 of v0.3 wave."""
import json
import sqlite3
import pytest
from datasette.app import Datasette

from datasette_assignments import creator
from datasette_assignments.schema import validate_definition

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from test_schema import tasks_defn, make_defn


# ── Helpers ────────────────────────────────────────────────────────────────────

async def build_instance(tmp_path):
    db_path = str(tmp_path / "assignments_data.db")
    sqlite3.connect(db_path).close()
    ds = Datasette([db_path])
    await ds.invoke_startup()
    defn = validate_definition(make_defn(slug="survey", name="City Survey"))
    await creator.create_assignment(ds, defn, {"id": "alice"})
    return ds


async def signed_in_post(ds, path, data, actor_id="alice"):
    cookies = {"ds_actor": ds.client.actor_cookie({"id": actor_id})}
    page = await ds.client.get("/-/assignments/new", cookies=cookies)
    token = page.cookies.get("ds_csrftoken") or ""
    data = dict(data, csrftoken=token)
    cookies.update(page.cookies)
    return await ds.client.post(path, data=data, cookies=cookies)


def edited_defn():
    """Return a definition suitable for edit POST (only editable fields changed)."""
    return {
        "slug": "survey",
        "name": "City Survey Updated",
        "mode": "form",
        "instructions": "Updated instructions.",
        "responses_per_task": 3,
        "task_columns": [],
        "task_title_column": None,
        "task_image_column": None,
        "fields": [
            {
                "kind": "input", "type": "text", "id": "answer",
                "label": "Updated Label", "help": "new help text",
                "required": True, "gallery": False,
                "missing_companion": False, "options": []
            }
        ],
    }


# ── Route tests ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_edit_get_requires_auth(tmp_path):
    """GET /-/assignments/<slug>/edit requires sign-in."""
    ds = await build_instance(tmp_path)
    r = await ds.client.get("/-/assignments/survey/edit")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_edit_get_requires_owner_or_root(tmp_path):
    """GET /-/assignments/<slug>/edit denies non-owners."""
    ds = await build_instance(tmp_path)
    bob = {"ds_actor": ds.client.actor_cookie({"id": "bob"})}
    r = await ds.client.get("/-/assignments/survey/edit", cookies=bob)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_edit_get_returns_200_for_owner(tmp_path):
    """GET /-/assignments/<slug>/edit returns 200 for the owner."""
    ds = await build_instance(tmp_path)
    alice = {"ds_actor": ds.client.actor_cookie({"id": "alice"})}
    r = await ds.client.get("/-/assignments/survey/edit", cookies=alice)
    assert r.status_code == 200
    # Page should contain edit mode signals
    assert b"survey" in r.content


@pytest.mark.asyncio
async def test_edit_get_returns_200_for_root(tmp_path):
    """GET /-/assignments/<slug>/edit returns 200 for root."""
    ds = await build_instance(tmp_path)
    root = {"ds_actor": ds.client.actor_cookie({"id": "root"})}
    r = await ds.client.get("/-/assignments/survey/edit", cookies=root)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_edit_get_404_for_unknown_slug(tmp_path):
    """GET /-/assignments/<slug>/edit returns 404 for unknown slug."""
    ds = await build_instance(tmp_path)
    alice = {"ds_actor": ds.client.actor_cookie({"id": "alice"})}
    r = await ds.client.get("/-/assignments/nonexistent/edit", cookies=alice)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_edit_post_updates_name_and_label(tmp_path):
    """POST /-/assignments/<slug>/edit updates editable fields in registry."""
    ds = await build_instance(tmp_path)
    r = await signed_in_post(ds, "/-/assignments/survey/edit", {
        "definition": json.dumps(edited_defn()),
    })
    # Expect redirect back to manage page
    assert r.status_code in (302, 200)

    from datasette_assignments import registry as reg
    row = await reg.get(ds, "survey")
    assert row["name"] == "City Survey Updated"
    defn = row["definition"]
    assert defn["fields"][0]["label"] == "Updated Label"


@pytest.mark.asyncio
async def test_edit_post_rejects_structural_changes(tmp_path):
    """POST that changes field id or type is rejected with 400."""
    ds = await build_instance(tmp_path)
    bad = edited_defn()
    bad["fields"][0]["id"] = "renamed_id"  # structural change: id rename
    r = await signed_in_post(ds, "/-/assignments/survey/edit", {
        "definition": json.dumps(bad),
    })
    # Server should return 400 or re-render form with errors
    assert r.status_code in (400, 200)
    # Should NOT have updated the registry
    from datasette_assignments import registry as reg
    row = await reg.get(ds, "survey")
    assert row["definition"]["fields"][0]["id"] == "answer"  # unchanged


@pytest.mark.asyncio
async def test_edit_post_rejects_mode_change(tmp_path):
    """POST that changes mode is rejected."""
    ds = await build_instance(tmp_path)
    bad = edited_defn()
    bad["mode"] = "tasks"
    r = await signed_in_post(ds, "/-/assignments/survey/edit", {
        "definition": json.dumps(bad),
    })
    assert r.status_code in (400, 200)
    from datasette_assignments import registry as reg
    row = await reg.get(ds, "survey")
    assert row["definition"]["mode"] == "form"  # unchanged


@pytest.mark.asyncio
async def test_edit_post_requires_owner(tmp_path):
    """POST by non-owner is rejected."""
    ds = await build_instance(tmp_path)
    r = await signed_in_post(ds, "/-/assignments/survey/edit", {
        "definition": json.dumps(edited_defn()),
    }, actor_id="bob")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_edit_manage_page_has_edit_link(tmp_path):
    """Manage page includes a link to the edit page."""
    ds = await build_instance(tmp_path)
    alice = {"ds_actor": ds.client.actor_cookie({"id": "alice"})}
    r = await ds.client.get("/-/assignments/survey", cookies=alice)
    assert r.status_code == 200
    assert b"/edit" in r.content or b"Edit" in r.content
