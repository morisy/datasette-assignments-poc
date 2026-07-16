import pytest
from datasette.app import Datasette
from datasette_assignments import creator, registry
from datasette_assignments.schema import validate_definition
from datasette_apps.registry import Registry as AppsRegistry
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from test_schema import make_defn, tasks_defn
import sqlite3, tempfile, os


def make_ds(tmp_path, plugin_config=None):
    db_path = str(tmp_path / "assignments_data.db")
    sqlite3.connect(db_path).close()
    if plugin_config:
        return Datasette([db_path], config={"plugins": plugin_config})
    return Datasette([db_path])


@pytest.mark.asyncio
async def test_create_assignment_produces_all_artifacts(tmp_path):
    ds = make_ds(tmp_path)
    await ds.invoke_startup()
    defn = tasks_defn()
    row = await creator.create_assignment(ds, defn, {"id": "alice"})
    assert row["slug"] == "mayors"
    db = ds.get_database("assignments_data")
    names = {r[0] for r in (await db.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'a_mayors%'")).rows}
    assert {"a_mayors_tasks", "a_mayors_responses", "a_mayors_config",
            "a_mayors_mark_done", "a_mayors_public"} <= names
    assert await ds.get_query("assignments_data", "submit_mayors") is not None
    assert await ds.get_query("assignments_data", "next_task_mayors") is not None
    reg = await registry.get(ds, "mayors")
    assert reg["owner_id"] == "alice" and reg["app_id"]


@pytest.mark.asyncio
async def test_create_rolls_back_on_failure(tmp_path, monkeypatch):
    ds = make_ds(tmp_path)
    await ds.invoke_startup()

    async def boom(*a, **kw):
        raise RuntimeError("app creation failed")
    monkeypatch.setattr(creator, "_create_app", boom)
    with pytest.raises(creator.CreationError):
        await creator.create_assignment(ds, tasks_defn(), {"id": "alice"})
    db = ds.get_database("assignments_data")
    leftover = (await db.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'a_mayors%'")).rows
    assert leftover == []
    assert await ds.get_query("assignments_data", "submit_mayors") is None
    assert await ds.get_query("assignments_data", "next_task_mayors") is None
    assert await ds.get_query("assignments_data", "progress_mayors") is None
    assert await registry.get(ds, "mayors") is None


@pytest.mark.asyncio
async def test_create_rolls_back_when_task_insert_fails(tmp_path, monkeypatch):
    ds = make_ds(tmp_path)
    await ds.invoke_startup()

    async def boom(*a, **kw):
        raise RuntimeError("task insert failed")
    monkeypatch.setattr(creator, "insert_tasks", boom)

    with pytest.raises(creator.CreationError):
        await creator.create_assignment(
            ds, tasks_defn(), {"id": "alice"},
            task_rows=[{"city": "X", "state": "Y"}])

    db = ds.get_database("assignments_data")
    leftover = (await db.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'a_mayors%'")).rows
    assert leftover == []
    assert await ds.get_query("assignments_data", "submit_mayors") is None
    assert await ds.get_query("assignments_data", "next_task_mayors") is None
    assert await ds.get_query("assignments_data", "progress_mayors") is None
    assert await registry.get(ds, "mayors") is None


def image_tasks_defn():
    """A tasks-mode definition with task_image_column='photo'."""
    return validate_definition(make_defn(
        slug="photos", mode="tasks",
        task_columns=["city", "photo"], task_title_column="city",
        task_image_column="photo",
        fields=[
            {"kind": "input", "type": "text", "id": "answer", "label": "Answer",
             "help": "", "required": True, "gallery": False,
             "missing_companion": False, "options": []},
        ]))


@pytest.mark.asyncio
async def test_create_opts_in_approved_image_origin(tmp_path):
    """Creating with approved image origin → csp_origins set on the app."""
    ds = make_ds(tmp_path, plugin_config={
        "datasette-apps": {"allowed_csp_origins": ["https://cdn.muckrock.com"]}
    })
    await ds.invoke_startup()
    defn = image_tasks_defn()
    task_rows = [
        {"city": "Boston", "photo": "https://cdn.muckrock.com/img/a.jpg"},
        {"city": "Chicago", "photo": "https://cdn.muckrock.com/img/b.jpg"},
    ]
    row = await creator.create_assignment(ds, defn, {"id": "alice"},
                                          task_rows=task_rows)
    assert row["slug"] == "photos"
    app_id = row["app_id"]
    apps = AppsRegistry(ds)
    csp = await apps.get_csp_origins(app_id)
    assert "https://cdn.muckrock.com" in csp


@pytest.mark.asyncio
async def test_create_rejects_unapproved_image_origin(tmp_path):
    """Creating with unapproved image origin → CreationError, no artifacts remain."""
    ds = make_ds(tmp_path, plugin_config={
        "datasette-apps": {"allowed_csp_origins": ["https://cdn.muckrock.com"]}
    })
    await ds.invoke_startup()
    defn = image_tasks_defn()
    task_rows = [
        {"city": "Evil", "photo": "https://evil.example/img.jpg"},
    ]
    with pytest.raises(creator.CreationError) as exc_info:
        await creator.create_assignment(ds, defn, {"id": "alice"},
                                        task_rows=task_rows)
    msg = str(exc_info.value)
    assert "evil.example" in msg
    assert "allowed_csp_origins" in msg
    assert "cdn.muckrock.com" in msg
    # No artifacts remain
    db = ds.get_database("assignments_data")
    leftover = (await db.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'a_photos%'")).rows
    assert leftover == []
    assert await registry.get(ds, "photos") is None


@pytest.mark.asyncio
async def test_insert_tasks_and_submit_flow(tmp_path):
    ds = make_ds(tmp_path)
    await ds.invoke_startup()
    defn = tasks_defn()
    await creator.create_assignment(ds, defn, {"id": "alice"})
    await creator.insert_tasks(ds, defn, [
        {"city": "Boston", "state": "MA"}, {"city": "Chicago", "state": "IL"}])
    # anonymous read via the stored query endpoint
    r = await ds.client.get(
        "/assignments_data/next_task_mayors.json?_shape=array&seen=")
    assert r.status_code == 200 and r.json()[0]["city"] in ("Boston", "Chicago")
    # anonymous write
    r = await ds.client.post("/assignments_data/submit_mayors.json?_json=1", json={
        "task_id": 1, "records_page": "https://x.gov",
        "records_page_missing": 0, "topics": "[]"})
    assert r.status_code in (200, 201)
    count = (await ds.get_database("assignments_data").execute(
        "SELECT COUNT(*) FROM a_mayors_responses")).first()[0]
    assert count == 1
