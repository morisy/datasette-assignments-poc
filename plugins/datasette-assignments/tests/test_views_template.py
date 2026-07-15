import pytest
import sqlite3
from datasette.app import Datasette


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
    ]:
        assert needle in html, needle
    assert 'id="preview-btn"' not in html  # manual preview button removed
