import pytest
from datasette.app import Datasette

from datasette_assignments.schema import (
    DefinitionError, sanitize_identifier, slugify, validate_definition,
    build_ddl, build_queries, drop_ddl, response_columns, merge_editable,
)
import sqlite3


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


def tasks_defn():
    return validate_definition(make_defn(
        slug="mayors", mode="tasks",
        task_columns=["city", "state"], task_title_column="city",
        fields=[
            {"kind": "header", "text": "Find these"},
            {"kind": "input", "type": "url", "id": "records_page",
             "label": "Records page", "help": "", "required": True,
             "gallery": True, "missing_companion": True, "options": []},
            {"kind": "input", "type": "checkbox_group", "id": "topics",
             "label": "Topics", "help": "", "required": False,
             "gallery": False, "missing_companion": False,
             "options": ["police", "budget"]},
        ]))


def test_ddl_executes_and_trigger_fires():
    defn = tasks_defn()
    conn = sqlite3.connect(":memory:")
    for stmt in build_ddl(defn):
        conn.execute(stmt)
    conn.execute("INSERT INTO a_mayors_tasks (city, state) VALUES ('Boston','MA')")
    conn.execute("INSERT INTO a_mayors_config (key, value) VALUES "
                 "('responses_per_task','2'),('status','open')")
    ins = ("INSERT INTO a_mayors_responses "
           "(task_id, records_page, records_page_missing, topics) "
           "VALUES (1, 'https://x.gov', 0, '[\"police\"]')")
    conn.execute(ins)
    assert conn.execute("SELECT status FROM a_mayors_tasks").fetchone()[0] == "pending"
    conn.execute(ins)
    assert conn.execute("SELECT status FROM a_mayors_tasks").fetchone()[0] == "done"


def test_public_view_exposes_only_gallery_fields_of_public_rows():
    defn = tasks_defn()
    conn = sqlite3.connect(":memory:")
    for stmt in build_ddl(defn):
        conn.execute(stmt)
    conn.execute("INSERT INTO a_mayors_tasks (city, state) VALUES ('Boston','MA')")
    conn.execute("INSERT INTO a_mayors_responses "
                 "(task_id, records_page, records_page_missing, topics, is_public) "
                 "VALUES (1,'https://pub.gov',0,'[]',1), (1,'https://priv.gov',0,'[]',0)")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(a_mayors_public)")]
    assert "records_page" in cols and "topics" not in cols  # topics not gallery
    rows = conn.execute("SELECT records_page FROM a_mayors_public").fetchall()
    assert rows == [("https://pub.gov",)]


def test_form_mode_has_no_tasks_or_trigger():
    defn = validate_definition(make_defn(slug="tips"))
    stmts = "\n".join(build_ddl(defn))
    assert "a_tips_tasks" not in stmts
    assert "TRIGGER" not in stmts
    assert "a_tips_responses" in stmts
    assert "a_tips_public" not in stmts  # only field has gallery=False


def test_queries_shapes():
    defn = tasks_defn()
    q = build_queries(defn, "assignments_data")
    assert q["submit"]["name"] == "submit_mayors" and q["submit"]["is_write"]
    assert ":records_page" in q["submit"]["sql"]
    assert " = 'open'" in q["submit"]["sql"]
    assert "instr(" in q["next_task"]["sql"] and ":seen" in q["next_task"]["sql"]
    assert not q["progress"]["is_write"]
    form_q = build_queries(validate_definition(make_defn(slug="tips")), "assignments_data")
    assert "next_task" not in form_q
    assert ":task_id" not in form_q["submit"]["sql"]


def test_drop_ddl_removes_everything():
    defn = tasks_defn()
    conn = sqlite3.connect(":memory:")
    for stmt in build_ddl(defn):
        conn.execute(stmt)
    for stmt in drop_ddl("mayors", "tasks"):
        conn.execute(stmt)
    remaining = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'a_mayors%'")]
    assert remaining == []


# ── merge_editable tests ──────────────────────────────────────────────────────

def test_merge_editable_accepts_label_and_help_changes():
    """merge_editable allows updating label, help, and name/instructions."""
    stored = make_defn(slug="survey", name="Old Name")
    stored["fields"] = [
        {"kind": "input", "type": "text", "id": "answer", "label": "Old Label",
         "help": "", "required": True, "gallery": False,
         "missing_companion": False, "options": []},
    ]
    posted = dict(stored)
    posted["name"] = "New Name"
    posted["instructions"] = "New instructions"
    posted["fields"] = [
        {"kind": "input", "type": "text", "id": "answer", "label": "New Label",
         "help": "Some help", "required": True, "gallery": False,
         "missing_companion": False, "options": []},
    ]
    merged = merge_editable(stored, posted)
    assert merged["name"] == "New Name"
    assert merged["instructions"] == "New instructions"
    assert merged["fields"][0]["label"] == "New Label"
    assert merged["fields"][0]["help"] == "Some help"
    # Structural fields unchanged
    assert merged["slug"] == "survey"
    assert merged["fields"][0]["id"] == "answer"
    assert merged["fields"][0]["type"] == "text"


def test_merge_editable_rejects_field_id_rename():
    """merge_editable raises DefinitionError when posted field id differs."""
    stored = make_defn(slug="survey")
    stored["fields"] = [
        {"kind": "input", "type": "text", "id": "answer", "label": "Label",
         "help": "", "required": True, "gallery": False,
         "missing_companion": False, "options": []},
    ]
    posted = dict(stored)
    posted["fields"] = [
        {"kind": "input", "type": "text", "id": "renamed", "label": "Label",
         "help": "", "required": True, "gallery": False,
         "missing_companion": False, "options": []},
    ]
    with pytest.raises(DefinitionError):
        merge_editable(stored, posted)


def test_merge_editable_rejects_mode_change():
    """merge_editable raises DefinitionError when mode is different."""
    stored = make_defn(slug="survey", mode="form")
    posted = dict(stored)
    posted["mode"] = "tasks"
    with pytest.raises(DefinitionError):
        merge_editable(stored, posted)


def test_merge_editable_allows_adding_options():
    """merge_editable allows new options to be added to select/checkbox_group."""
    stored = make_defn(slug="survey")
    stored["fields"] = [
        {"kind": "input", "type": "select", "id": "pick", "label": "Pick",
         "help": "", "required": False, "gallery": False,
         "missing_companion": False, "options": ["a", "b"]},
    ]
    posted = dict(stored)
    posted["fields"] = [
        {"kind": "input", "type": "select", "id": "pick", "label": "Pick",
         "help": "", "required": False, "gallery": False,
         "missing_companion": False, "options": ["a", "b", "c"]},
    ]
    merged = merge_editable(stored, posted)
    assert merged["fields"][0]["options"] == ["a", "b", "c"]


# ── Three verbatim tests from task-1-brief ────────────────────────────────────

def test_merge_editable_accepts_copy_changes():
    """Name, instructions, and field labels/help are all editable."""
    stored = make_defn(slug="survey", name="Old Name")
    stored["fields"] = [
        {"kind": "input", "type": "text", "id": "answer", "label": "Old",
         "help": "", "required": True, "gallery": False,
         "missing_companion": False, "options": []},
    ]
    posted = dict(stored)
    posted["name"] = "New Name"
    posted["instructions"] = "New instructions"
    posted["fields"] = [
        {"kind": "input", "type": "text", "id": "answer", "label": "New",
         "help": "hint", "required": True, "gallery": False,
         "missing_companion": False, "options": []},
    ]
    merged = merge_editable(stored, posted)
    assert merged["name"] == "New Name"
    assert merged["instructions"] == "New instructions"
    assert merged["fields"][0]["label"] == "New"
    assert merged["fields"][0]["help"] == "hint"
    assert merged["slug"] == "survey"          # structural: unchanged
    assert merged["fields"][0]["id"] == "answer"  # structural: unchanged


def test_merge_editable_rejects_structural_changes():
    """mode, slug, field id, and field type changes raise DefinitionError."""
    stored = make_defn(slug="survey")
    stored["fields"] = [
        {"kind": "input", "type": "text", "id": "answer", "label": "Label",
         "help": "", "required": True, "gallery": False,
         "missing_companion": False, "options": []},
    ]

    # mode change
    posted = dict(stored)
    posted["mode"] = "tasks"
    with pytest.raises(DefinitionError):
        merge_editable(stored, posted)

    # slug change
    posted = dict(stored)
    posted["slug"] = "other"
    with pytest.raises(DefinitionError):
        merge_editable(stored, posted)

    # field id rename
    posted = dict(stored)
    posted["fields"] = [
        {"kind": "input", "type": "text", "id": "renamed", "label": "Label",
         "help": "", "required": True, "gallery": False,
         "missing_companion": False, "options": []},
    ]
    with pytest.raises(DefinitionError):
        merge_editable(stored, posted)

    # field type change
    posted = dict(stored)
    posted["fields"] = [
        {"kind": "input", "type": "number", "id": "answer", "label": "Label",
         "help": "", "required": True, "gallery": False,
         "missing_companion": False, "options": []},
    ]
    with pytest.raises(DefinitionError):
        merge_editable(stored, posted)


def test_merge_editable_options_append_only():
    """Options must start with stored options in order; reorder/rename/remove raises."""
    stored = make_defn(slug="survey")
    stored["fields"] = [
        {"kind": "input", "type": "select", "id": "pick", "label": "Pick",
         "help": "", "required": False, "gallery": False,
         "missing_companion": False, "options": ["a", "b"]},
    ]

    # append is fine
    posted = dict(stored)
    posted["fields"] = [
        {"kind": "input", "type": "select", "id": "pick", "label": "Pick",
         "help": "", "required": False, "gallery": False,
         "missing_companion": False, "options": ["a", "b", "c"]},
    ]
    merged = merge_editable(stored, posted)
    assert merged["fields"][0]["options"] == ["a", "b", "c"]

    # rename existing option -> error
    posted = dict(stored)
    posted["fields"] = [dict(stored["fields"][0])]
    posted["fields"][0]["options"] = ["a", "x", "c"]   # rename -> error
    with pytest.raises(DefinitionError):
        merge_editable(stored, posted)

    # reorder -> error
    posted = dict(stored)
    posted["fields"] = [dict(stored["fields"][0])]
    posted["fields"][0]["options"] = ["b", "a"]   # reorder -> error
    with pytest.raises(DefinitionError):
        merge_editable(stored, posted)

    # removal -> error
    posted = dict(stored)
    posted["fields"] = [dict(stored["fields"][0])]
    posted["fields"][0]["options"] = ["a"]   # removal -> error
    with pytest.raises(DefinitionError):
        merge_editable(stored, posted)

    # duplicate append -> error
    posted = dict(stored)
    posted["fields"] = [dict(stored["fields"][0])]
    posted["fields"][0]["options"] = ["a", "b", "b"]   # duplicate "b" -> error
    with pytest.raises(DefinitionError):
        merge_editable(stored, posted)

    # non-string (int) append -> error
    posted = dict(stored)
    posted["fields"] = [dict(stored["fields"][0])]
    posted["fields"][0]["options"] = ["a", "b", 123]   # non-string -> error
    with pytest.raises(DefinitionError):
        merge_editable(stored, posted)


# ── Agreement view tests (Task 4) ─────────────────────────────────────────────

def test_agreement_view_exists_for_tasks_mode():
    """build_ddl in tasks mode emits a CREATE VIEW a_<slug>_agreement statement."""
    defn = tasks_defn()
    stmts = build_ddl(defn)
    joined = "\n".join(stmts)
    assert "CREATE VIEW a_mayors_agreement" in joined
    assert "task_id" in joined
    assert "task_title" in joined
    assert "response_count" in joined
    # Primary input fields only (no _missing companions)
    assert "records_page_majority" in joined
    assert "records_page_distinct" in joined
    assert "topics_majority" in joined
    assert "topics_distinct" in joined
    # _missing companion columns must NOT appear as majority/distinct targets
    assert "records_page_missing_majority" not in joined
    assert "records_page_missing_distinct" not in joined


def test_agreement_view_absent_for_form_mode():
    """build_ddl in form mode must NOT emit an agreement view."""
    defn = validate_definition(make_defn(slug="tips"))
    stmts = build_ddl(defn)
    joined = "\n".join(stmts)
    assert "a_tips_agreement" not in joined


def test_agreement_majority_math():
    """2 responses with 'x' + 1 with 'y' → majority 'x', distinct count 2."""
    defn = tasks_defn()
    conn = sqlite3.connect(":memory:")
    for stmt in build_ddl(defn):
        conn.execute(stmt)
    conn.execute("INSERT INTO a_mayors_tasks (city, state) VALUES ('Boston', 'MA')")
    conn.execute("INSERT INTO a_mayors_config (key, value) VALUES "
                 "('responses_per_task','3'),('status','open')")
    # Insert 2 responses with topics='x', 1 with topics='y'
    for val in ("x", "x", "y"):
        conn.execute(
            "INSERT INTO a_mayors_responses "
            "(task_id, records_page, records_page_missing, topics) "
            "VALUES (1, 'https://a.gov', 0, ?)",
            (val,),
        )
    row = conn.execute(
        "SELECT response_count, topics_majority, topics_distinct "
        "FROM a_mayors_agreement WHERE task_id = 1"
    ).fetchone()
    assert row is not None
    response_count, topics_majority, topics_distinct = row
    assert response_count == 3
    assert topics_majority == "x"
    assert topics_distinct == 2


def test_drop_ddl_removes_agreement_view():
    """drop_ddl removes the agreement view for tasks mode."""
    defn = tasks_defn()
    conn = sqlite3.connect(":memory:")
    for stmt in build_ddl(defn):
        conn.execute(stmt)
    # Verify view exists before drop
    views_before = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='view' AND name='a_mayors_agreement'")]
    assert "a_mayors_agreement" in views_before
    for stmt in drop_ddl("mayors", "tasks"):
        conn.execute(stmt)
    views_after = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'a_mayors%'")]
    assert "a_mayors_agreement" not in views_after
