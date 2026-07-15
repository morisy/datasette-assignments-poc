"""Tests for append-tasks feature — Task 3 of v0.3 wave.

Covers:
- Owner posts matching CSV → rows added (count check via direct db), redirect contains added=2
- Header mismatch → 400 text naming the offending column
- Non-owner/anon → 403
- Form-mode assignment → 400 ("not a task-list assignment")
"""
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

async def build_tasks_instance(tmp_path):
    """Create a Datasette instance with a tasks-mode assignment 'mayors'."""
    db_path = str(tmp_path / "assignments_data.db")
    sqlite3.connect(db_path).close()
    ds = Datasette([db_path])
    await ds.invoke_startup()
    defn = validate_definition(tasks_defn())
    # Insert two seed tasks
    await creator.create_assignment(
        ds, defn, {"id": "alice"},
        task_rows=[{"city": "Springfield", "state": "IL"}],
    )
    return ds


async def build_form_instance(tmp_path):
    """Create a Datasette instance with a form-mode assignment 'survey'."""
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


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_tasks_success_rows_added_and_redirect(tmp_path):
    """Owner posts matching CSV → rows added, redirect contains added=2."""
    ds = await build_tasks_instance(tmp_path)
    csv_text = "city,state\nChicago,IL\nRockford,IL"
    r = await signed_in_post(
        ds,
        "/-/assignments/mayors/add-tasks",
        {"tasks_csv": csv_text},
    )
    # Should redirect to manage page with ?added=2
    assert r.status_code == 302
    location = r.headers.get("location", "")
    assert "added=2" in location

    # Verify rows actually in DB (started with 1 seed + 2 new = 3 total)
    db = ds.get_database("assignments_data")
    result = await db.execute("SELECT COUNT(*) FROM a_mayors_tasks")
    count = result.first()[0]
    assert count == 3


@pytest.mark.asyncio
async def test_add_tasks_header_mismatch_400(tmp_path):
    """Header mismatch → 400 naming the bad column."""
    ds = await build_tasks_instance(tmp_path)
    # 'county' is not in task_columns (which are city, state)
    csv_text = "city,county\nChicago,Cook"
    r = await signed_in_post(
        ds,
        "/-/assignments/mayors/add-tasks",
        {"tasks_csv": csv_text},
    )
    assert r.status_code == 400
    assert "state" in r.text or "county" in r.text


@pytest.mark.asyncio
async def test_add_tasks_anon_forbidden(tmp_path):
    """Anonymous user → 403."""
    ds = await build_tasks_instance(tmp_path)
    r = await ds.client.post(
        "/-/assignments/mayors/add-tasks",
        data={"tasks_csv": "city,state\nChicago,IL", "csrftoken": "x"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_add_tasks_non_owner_forbidden(tmp_path):
    """Non-owner → 403."""
    ds = await build_tasks_instance(tmp_path)
    r = await signed_in_post(
        ds,
        "/-/assignments/mayors/add-tasks",
        {"tasks_csv": "city,state\nChicago,IL"},
        actor_id="bob",
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_add_tasks_form_mode_400(tmp_path):
    """Form-mode assignment → 400 'not a task-list assignment'."""
    ds = await build_form_instance(tmp_path)
    r = await signed_in_post(
        ds,
        "/-/assignments/survey/add-tasks",
        {"tasks_csv": "answer\nhello"},
    )
    assert r.status_code == 400
    assert "task" in r.text.lower()
