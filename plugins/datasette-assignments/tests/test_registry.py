import pytest
from datasette.app import Datasette
from datasette_assignments import registry

DEFN = {
    "slug": "tips", "name": "Tips", "mode": "form", "instructions": "",
    "responses_per_task": 3, "task_columns": [], "task_title_column": None,
    "task_image_column": None,
    "fields": [{"kind": "input", "type": "text", "id": "tip", "label": "Tip",
                "help": "", "required": True, "gallery": False,
                "missing_companion": False, "options": []}],
}


@pytest.mark.asyncio
async def test_create_get_list_delete():
    ds = Datasette(memory=True)
    await ds.invoke_startup()
    await registry.create(ds, DEFN, owner_id="alice", app_id="app123")
    row = await registry.get(ds, "tips")
    assert row["owner_id"] == "alice" and row["definition"]["slug"] == "tips"
    assert row["app_id"] == "app123"
    alice = await registry.list_for(ds, {"id": "alice"})
    bob = await registry.list_for(ds, {"id": "bob"})
    root = await registry.list_for(ds, {"id": "root"})
    assert [r["slug"] for r in alice] == ["tips"]
    assert bob == [] and len(root) == 1
    await registry.delete(ds, "tips")
    assert await registry.get(ds, "tips") is None
