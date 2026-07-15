import pytest
from datasette.app import Datasette

from datasette_assignments.schema import (
    DefinitionError, sanitize_identifier, slugify, validate_definition,
)


@pytest.mark.asyncio
async def test_plugin_is_installed():
    ds = Datasette(memory=True)
    response = await ds.client.get("/-/plugins.json")
    assert response.status_code == 200
    names = [p["name"] for p in response.json()]
    assert "datasette-assignments" in names


def make_defn(**over):
    base = {
        "slug": "city_survey", "name": "City Survey", "mode": "form",
        "instructions": "Help.", "responses_per_task": 3,
        "task_columns": [], "task_title_column": None, "task_image_column": None,
        "fields": [
            {"kind": "input", "type": "text", "id": "answer", "label": "Answer",
             "help": "", "required": True, "gallery": False,
             "missing_companion": False, "options": []},
        ],
    }
    base.update(over)
    return base


def test_slugify_and_sanitize():
    assert slugify("City Survey 2026!") == "city_survey_2026"
    assert sanitize_identifier("Records Page URL") == "records_page_url"
    assert sanitize_identifier("2fast") == "c_2fast"
    assert sanitize_identifier("city", existing=("city",)) == "city_2"
    with pytest.raises(DefinitionError):
        sanitize_identifier("!!!")


def test_validate_accepts_good_form_definition():
    normalized = validate_definition(make_defn())
    assert normalized["slug"] == "city_survey"


def test_validate_rejects_bad_slug_and_reserved_words():
    with pytest.raises(DefinitionError) as e:
        validate_definition(make_defn(slug="Bad-Slug"))
    assert any("slug" in msg for msg in e.value.errors)


def test_validate_requires_input_field_and_options():
    with pytest.raises(DefinitionError):
        validate_definition(make_defn(fields=[{"kind": "header", "text": "hi"}]))
    bad_select = make_defn(fields=[
        {"kind": "input", "type": "select", "id": "pick", "label": "Pick",
         "help": "", "required": False, "gallery": False,
         "missing_companion": False, "options": []},
    ])
    with pytest.raises(DefinitionError):
        validate_definition(bad_select)


def test_validate_tasks_mode_requirements():
    with pytest.raises(DefinitionError):
        validate_definition(make_defn(mode="tasks", task_columns=[]))
    good = validate_definition(make_defn(
        mode="tasks", task_columns=["city", "state"], task_title_column="city"))
    assert good["responses_per_task"] == 3


def test_validate_rejects_companion_on_wrong_type_and_dupe_ids():
    with pytest.raises(DefinitionError):
        validate_definition(make_defn(fields=[
            {"kind": "input", "type": "date", "id": "d", "label": "D", "help": "",
             "required": False, "gallery": False, "missing_companion": True,
             "options": []}]))
    with pytest.raises(DefinitionError):
        validate_definition(make_defn(fields=[
            {"kind": "input", "type": "text", "id": "x", "label": "A", "help": "",
             "required": False, "gallery": False, "missing_companion": False,
             "options": []},
            {"kind": "input", "type": "text", "id": "x", "label": "B", "help": "",
             "required": False, "gallery": False, "missing_companion": False,
             "options": []}]))
