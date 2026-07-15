import pytest
from datasette.app import Datasette
from datasette_assignments import creator, registry
from datasette_assignments.schema import validate_definition
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from test_schema import make_defn, tasks_defn
import sqlite3, tempfile, os


def make_ds(tmp_path):
    db_path = str(tmp_path / "assignments_data.db")
    sqlite3.connect(db_path).close()
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
    assert await registry.get(ds, "mayors") is None


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
