import json
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from sync_apps import sync_app

REPO = Path(__file__).parent.parent

def fresh_internal(tmp_path):
    dst = tmp_path / "internal.db"
    shutil.copy(REPO / "internal.db", dst)
    return dst

DEF = {
    "name": "Test App",
    "description": "A test",
    "html": "<html><body>v1</body></html>",
    "sql_databases": ["census"],
    "stored_queries": ["census/submit_response"],
    "is_private": 0,
}

def test_creates_new_app(tmp_path):
    db = fresh_internal(tmp_path)
    app_id = sync_app(db, DEF)
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT name, is_private, current_version, path, stored_queries"
        " FROM apps WHERE id = ?", (app_id,)).fetchone()
    assert row[0] == "Test App"
    assert row[1] == 0
    assert row[2] == 1
    assert row[3] == f"/-/apps/{app_id}"
    assert json.loads(row[4]) == ["census/submit_response"]
    html = conn.execute(
        "SELECT html FROM app_revisions WHERE app_id = ? AND version = 1",
        (app_id,)).fetchone()[0]
    assert html == DEF["html"]
    dbs = [r[0] for r in conn.execute(
        "SELECT database_name FROM app_sql_databases WHERE app_id = ?", (app_id,))]
    assert dbs == ["census"]

def test_sync_is_idempotent(tmp_path):
    db = fresh_internal(tmp_path)
    id1 = sync_app(db, DEF)
    id2 = sync_app(db, DEF)  # unchanged -> no new revision
    assert id1 == id2
    conn = sqlite3.connect(db)
    assert conn.execute(
        "SELECT COUNT(*) FROM app_revisions WHERE app_id = ?", (id1,)).fetchone()[0] == 1

def test_changed_html_appends_revision(tmp_path):
    db = fresh_internal(tmp_path)
    app_id = sync_app(db, DEF)
    changed = dict(DEF, html="<html><body>v2</body></html>")
    sync_app(db, changed)
    conn = sqlite3.connect(db)
    assert conn.execute(
        "SELECT current_version FROM apps WHERE id = ?", (app_id,)).fetchone()[0] == 2
    html = conn.execute(
        "SELECT html FROM app_revisions WHERE app_id = ? AND version = 2",
        (app_id,)).fetchone()[0]
    assert "v2" in html
