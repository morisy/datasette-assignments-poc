import pytest
import sqlite3
from datasette.app import Datasette
from datasette_assignments import creator, registry
from datasette_assignments.schema import validate_definition


async def new_page_html(tmp_path):
    db_path = str(tmp_path / "assignments_data.db")
    sqlite3.connect(db_path).close()
    ds = Datasette([db_path])
    await ds.invoke_startup()
    cookies = {"ds_actor": ds.client.actor_cookie({"id": "root"})}
    r = await ds.client.get("/-/assignments/new", cookies=cookies)
    assert r.status_code == 200
    return r.text


@pytest.mark.asyncio
async def test_builder_contract_ids_survive_restyle(tmp_path):
    html = await new_page_html(tmp_path)
    for needle in [
        'id="assignment-form"', 'id="definition-json"', 'name="definition"',
        'id="assignment-name"', 'id="assignment-slug"',
        'id="assignment-instructions"', 'name="tasks_csv"',
        'data-type="text"', 'data-type="select"', 'data-kind="header"',
    ]:
        assert needle in html, needle


@pytest.mark.asyncio
async def test_builder_studio_structure(tmp_path):
    html = await new_page_html(tmp_path)
    for needle in [
        'class="studio', 'studio-builder', 'studio-preview',
        'id="preview-frame"', 'id="preview-note"',
        'type="radio" name="mode"', 'id="advanced"',
        'id="fields-empty"', 'palette-group',
        'id="task-title-col"', 'id="task-image-col"',
        'id="tasks-csv-file"', 'type="file"',
        'id="csv-detected"',
    ]:
        assert needle in html, needle
    assert 'id="preview-btn"' not in html  # manual preview button removed


# ── List progress tests ───────────────────────────────────────────────────────

def _make_ds(tmp_path):
    db_path = str(tmp_path / "assignments_data.db")
    sqlite3.connect(db_path).close()
    return Datasette([db_path])


def _tasks_defn():
    return validate_definition({
        "slug": "test_tasks", "name": "Test Tasks", "mode": "tasks",
        "instructions": "", "responses_per_task": 2,
        "task_columns": ["title"], "task_title_column": "title",
        "task_image_column": None,
        "fields": [
            {"kind": "input", "type": "text", "id": "answer", "label": "Answer",
             "help": "", "required": True, "gallery": False,
             "missing_companion": False, "options": []},
        ],
    })


def _form_defn():
    return validate_definition({
        "slug": "test_form", "name": "Test Form", "mode": "form",
        "instructions": "", "responses_per_task": 3,
        "task_columns": [], "task_title_column": None, "task_image_column": None,
        "fields": [
            {"kind": "input", "type": "text", "id": "name", "label": "Name",
             "help": "", "required": True, "gallery": False,
             "missing_companion": False, "options": []},
        ],
    })


@pytest.mark.asyncio
async def test_list_progress_tasks_mode(tmp_path):
    """Tasks-mode assignment: list page shows progress-track and '1 of 2' text."""
    ds = _make_ds(tmp_path)
    await ds.invoke_startup()
    actor = {"id": "root"}
    defn = _tasks_defn()
    await creator.create_assignment(ds, defn, actor,
                                    task_rows=[{"title": "Task A"}, {"title": "Task B"}])

    # Insert 2 responses for Task A to mark it done (responses_per_task=2)
    db = ds.get_database("assignments_data")
    slug = defn["slug"]
    await db.execute_write(
        f"INSERT INTO a_{slug}_responses (task_id, answer) VALUES (1, 'ans1'), (1, 'ans2')"
    )

    cookies = {"ds_actor": ds.client.actor_cookie(actor)}
    r = await ds.client.get("/-/assignments", cookies=cookies)
    assert r.status_code == 200
    html = r.text
    assert "progress-track" in html, "progress-track class not found"
    assert "1 of 2" in html, "'1 of 2' not found in list page"


@pytest.mark.asyncio
async def test_list_progress_form_mode(tmp_path):
    """Form-mode assignment: list page shows 'contributions' text."""
    ds = _make_ds(tmp_path)
    await ds.invoke_startup()
    actor = {"id": "root"}
    defn = _form_defn()
    await creator.create_assignment(ds, defn, actor)

    # Insert a response
    db = ds.get_database("assignments_data")
    slug = defn["slug"]
    await db.execute_write(
        f"INSERT INTO a_{slug}_responses (name) VALUES ('Alice')"
    )

    cookies = {"ds_actor": ds.client.actor_cookie(actor)}
    r = await ds.client.get("/-/assignments", cookies=cookies)
    assert r.status_code == 200
    html = r.text
    assert "contributions" in html, "'contributions' not found in list page"
