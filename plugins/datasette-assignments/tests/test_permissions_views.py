import json
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


# ── Views tests (Task 8) ──────────────────────────────────────────────────────

ALICE = {"id": "alice"}


def defn_payload(slug="wizard_test", mode="form"):
    d = {
        "slug": slug, "name": "Wizard Test", "mode": mode, "instructions": "Go",
        "responses_per_task": 2, "task_columns": [], "task_title_column": None,
        "task_image_column": None,
        "fields": [{"kind": "input", "type": "text", "id": "answer",
                    "label": "Answer", "help": "", "required": True,
                    "gallery": True, "missing_companion": False, "options": []}],
    }
    if mode == "tasks":
        d["task_title_column"] = "city"
    return d


async def signed_in_post(ds, path, data, actor=ALICE):
    cookies = {"ds_actor": ds.client.actor_cookie(actor)}
    # fetch csrftoken from the new page
    page = await ds.client.get("/-/assignments/new", cookies=cookies)
    token = page.cookies.get("ds_csrftoken") or ""
    data = dict(data, csrftoken=token)
    cookies.update(page.cookies)
    return await ds.client.post(path, data=data, cookies=cookies)


@pytest.mark.asyncio
async def test_list_requires_signin(tmp_path):
    ds = await build_instance(tmp_path)
    assert (await ds.client.get("/-/assignments")).status_code == 403
    cookies = {"ds_actor": ds.client.actor_cookie(ALICE)}
    assert (await ds.client.get("/-/assignments", cookies=cookies)).status_code == 200


@pytest.mark.asyncio
async def test_wizard_creates_form_assignment(tmp_path):
    ds = await build_instance(tmp_path)
    r = await signed_in_post(ds, "/-/assignments/new", {
        "definition": json.dumps(defn_payload()), "tasks_csv": ""})
    assert r.status_code in (302, 200)
    from datasette_assignments import registry as reg
    assert (await reg.get(ds, "wizard_test"))["owner_id"] == "alice"


@pytest.mark.asyncio
async def test_wizard_tasks_mode_with_csv(tmp_path):
    ds = await build_instance(tmp_path)
    payload = defn_payload(slug="csv_test", mode="tasks")
    r = await signed_in_post(ds, "/-/assignments/new", {
        "definition": json.dumps(payload),
        "tasks_csv": "City!,State\nBoston,MA\nChicago,IL\n"})
    assert r.status_code in (302, 200)
    db = ds.get_database("assignments_data")
    rows = (await db.execute("SELECT city, state FROM a_csv_test_tasks")).rows
    assert len(rows) == 2  # headers sanitized: City! -> city


@pytest.mark.asyncio
async def test_manage_owner_only_and_toggles(tmp_path):
    ds = await build_instance(tmp_path)  # creates 'mayors' owned by alice
    anon = await ds.client.get("/-/assignments/mayors")
    assert anon.status_code == 403
    bob = {"ds_actor": ds.client.actor_cookie({"id": "bob"})}
    assert (await ds.client.get("/-/assignments/mayors", cookies=bob)).status_code == 403
    alice_c = {"ds_actor": ds.client.actor_cookie(ALICE)}
    assert (await ds.client.get("/-/assignments/mayors", cookies=alice_c)).status_code == 200
    # close it, then anonymous submit must be rejected (0 rows inserted)
    await signed_in_post(ds, "/-/assignments/mayors/toggle-status", {})
    await ds.client.post("/assignments_data/submit_mayors.json?_json=1", json={
        "task_id": 1, "records_page": "https://x.gov",
        "records_page_missing": 0, "topics": "[]"})
    count = (await ds.get_database("assignments_data").execute(
        "SELECT COUNT(*) FROM a_mayors_responses")).first()[0]
    assert count == 0


@pytest.mark.asyncio
async def test_response_public_toggle_and_export(tmp_path):
    ds = await build_instance(tmp_path)
    await ds.client.post("/assignments_data/submit_mayors.json?_json=1", json={
        "task_id": 1, "records_page": "https://x.gov",
        "records_page_missing": 0, "topics": "[]"})
    await signed_in_post(ds, "/-/assignments/mayors/response-public",
                         {"id": "1", "public": "1"})
    pub = await ds.client.get(
        "/assignments_data/a_mayors_public.json?_shape=array")
    assert pub.status_code == 200 and len(pub.json()) == 1
    alice_c = {"ds_actor": ds.client.actor_cookie(ALICE)}
    csv_r = await ds.client.get("/-/assignments/mayors/export.csv",
                                cookies=alice_c)
    assert csv_r.status_code == 200 and "records_page" in csv_r.text
    assert (await ds.client.get("/-/assignments/mayors/export.csv")).status_code == 403


@pytest.mark.asyncio
async def test_mutation_endpoints_reject_non_owner_and_anon(tmp_path):
    ds = await build_instance(tmp_path)  # creates 'mayors' owned by alice
    # Insert a response for testing response-public endpoint
    await ds.client.post("/assignments_data/submit_mayors.json?_json=1", json={
        "task_id": 1, "records_page": "https://x.gov",
        "records_page_missing": 0, "topics": "[]"})

    bob = {"ds_actor": ds.client.actor_cookie({"id": "bob"})}

    # Test toggle-status endpoint
    # Anonymous
    anon_toggle = await ds.client.post("/-/assignments/mayors/toggle-status", data={})
    assert anon_toggle.status_code == 403
    # Bob (non-owner)
    bob_toggle = await ds.client.post("/-/assignments/mayors/toggle-status", data={}, cookies=bob)
    assert bob_toggle.status_code == 403

    # Test response-public endpoint
    # Anonymous
    anon_public = await ds.client.post("/-/assignments/mayors/response-public",
                                       data={"id": "1", "public": "1"})
    assert anon_public.status_code == 403
    # Bob (non-owner)
    bob_public = await ds.client.post("/-/assignments/mayors/response-public",
                                      data={"id": "1", "public": "1"}, cookies=bob)
    assert bob_public.status_code == 403

    # Test delete endpoint
    # Anonymous
    anon_delete = await ds.client.post("/-/assignments/mayors/delete",
                                       data={"confirm": "mayors"})
    assert anon_delete.status_code == 403
    # Bob (non-owner)
    bob_delete = await ds.client.post("/-/assignments/mayors/delete",
                                      data={"confirm": "mayors"}, cookies=bob)
    assert bob_delete.status_code == 403

    # Verify assignment still exists and status is still 'open'
    from datasette_assignments import registry as reg
    row = await reg.get(ds, "mayors")
    assert row is not None
    db = ds.get_database("assignments_data")
    status_result = await db.execute(
        "SELECT value FROM a_mayors_config WHERE key='status'")
    status = status_result.first()[0] if status_result.first() else None
    assert status == "open"
