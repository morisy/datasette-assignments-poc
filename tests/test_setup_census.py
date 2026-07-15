import csv
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from setup_census import build

CITIES = [("Boston", "MA"), ("Chicago", "IL")]

def make_csv(tmp_path):
    p = tmp_path / "cities.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["city", "state"])
        w.writerows(CITIES)
    return p

def test_build_creates_tasks(tmp_path):
    db = tmp_path / "census.db"
    build(db, make_csv(tmp_path))
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 2
    row = conn.execute(
        "SELECT city, state, status FROM tasks ORDER BY id LIMIT 1"
    ).fetchone()
    assert row == ("Boston", "MA", "pending")
    assert conn.execute(
        "SELECT value FROM config WHERE key='responses_per_task'"
    ).fetchone()[0] == "3"

def test_build_is_idempotent(tmp_path):
    db = tmp_path / "census.db"
    csv_path = make_csv(tmp_path)
    build(db, csv_path)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO responses (task_id, records_page_url, records_page_missing,"
        " records_email, records_email_missing, data_portal_url,"
        " data_portal_missing, notes) VALUES (1, 'https://x.gov/foia', 0,"
        " '', 1, '', 1, 'test')")
    conn.commit()
    conn.close()
    build(db, csv_path)  # rerun must not duplicate tasks or delete responses
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0] == 1

def test_trigger_marks_done_at_target(tmp_path):
    db = tmp_path / "census.db"
    build(db, make_csv(tmp_path), responses_per_task=2)
    conn = sqlite3.connect(db)
    ins = ("INSERT INTO responses (task_id, records_page_url, records_page_missing,"
           " records_email, records_email_missing, data_portal_url,"
           " data_portal_missing, notes) VALUES (1, 'https://x.gov', 0, '', 1, '', 1, '')")
    conn.execute(ins)
    conn.commit()
    assert conn.execute("SELECT status FROM tasks WHERE id=1").fetchone()[0] == "pending"
    conn.execute(ins)
    conn.commit()
    assert conn.execute("SELECT status FROM tasks WHERE id=1").fetchone()[0] == "done"
