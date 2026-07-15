import pytest
import sqlite3
from datasette.app import Datasette
from datasette_assignments import creator
from datasette_assignments.schema import validate_definition
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from test_schema import tasks_defn, make_defn


async def build_instance(tmp_path):
    db_path = str(tmp_path / "assignments_data.db")
    sqlite3.connect(db_path).close()
    ds = Datasette([db_path])
    await ds.invoke_startup()
    await creator.create_assignment(ds, tasks_defn(), {"id": "alice"})
    await creator.insert_tasks(ds, tasks_defn(), [{"city": "Boston", "state": "MA"}])
    return ds


@pytest.mark.asyncio
async def test_responses_table_private_tasks_table_public(tmp_path):
    ds = await build_instance(tmp_path)
    anon_resp = await ds.client.get("/assignments_data/a_mayors_responses.json")
    assert anon_resp.status_code == 403
    anon_tasks = await ds.client.get("/assignments_data/a_mayors_tasks.json")
    assert anon_tasks.status_code == 200
    owner_cookie = {"ds_actor": ds.client.actor_cookie({"id": "alice"})}
    other_cookie = {"ds_actor": ds.client.actor_cookie({"id": "bob"})}
    root_cookie = {"ds_actor": ds.client.actor_cookie({"id": "root"})}
    assert (await ds.client.get("/assignments_data/a_mayors_responses.json",
                                cookies=owner_cookie)).status_code == 200
    assert (await ds.client.get("/assignments_data/a_mayors_responses.json",
                                cookies=other_cookie)).status_code == 403
    assert (await ds.client.get("/assignments_data/a_mayors_responses.json",
                                cookies=root_cookie)).status_code == 200


@pytest.mark.asyncio
async def test_raw_sql_denied_on_data_db(tmp_path):
    ds = await build_instance(tmp_path)
    r = await ds.client.get(
        "/assignments_data/-/query.json?sql=SELECT+*+FROM+a_mayors_responses")
    assert r.status_code == 403
    root_cookie = {"ds_actor": ds.client.actor_cookie({"id": "root"})}
    r = await ds.client.get(
        "/assignments_data/-/query.json?sql=SELECT+1",
        cookies=root_cookie)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_stored_queries_still_work_anonymously(tmp_path):
    ds = await build_instance(tmp_path)
    r = await ds.client.get(
        "/assignments_data/progress_mayors.json?_shape=array")
    assert r.status_code == 200 and r.json()[0]["total"] == 1


@pytest.mark.asyncio
async def test_owners_cannot_cross_read_other_assignments(tmp_path):
    ds = await build_instance(tmp_path)  # creates 'mayors' owned by alice
    council = validate_definition(make_defn(slug="council"))
    await creator.create_assignment(ds, council, {"id": "bob"})
    alice = {"ds_actor": ds.client.actor_cookie({"id": "alice"})}
    bob = {"ds_actor": ds.client.actor_cookie({"id": "bob"})}
    # each owner reads their own
    assert (await ds.client.get("/assignments_data/a_mayors_responses.json",
                                cookies=alice)).status_code == 200
    assert (await ds.client.get("/assignments_data/a_council_responses.json",
                                cookies=bob)).status_code == 200
    # and is denied on the other's
    assert (await ds.client.get("/assignments_data/a_council_responses.json",
                                cookies=alice)).status_code == 403
    assert (await ds.client.get("/assignments_data/a_mayors_responses.json",
                                cookies=bob)).status_code == 403
