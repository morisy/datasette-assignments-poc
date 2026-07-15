"""Build census.db for the City Public Records Census assignment.

Each row of cities.csv becomes one task. Contributors submit the city's
public records page URL, public records email, and open data portal URL —
or flag each as not found. A task is 'done' once it has collected
responses_per_task submissions (the mark_task_done trigger handles this,
because Datasette stored write queries are limited to one statement).

Run with: python scripts/setup_census.py   (safe to re-run; never wipes data)
"""
import csv
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "..", "census.db")
CSV_PATH = os.path.join(HERE, "..", "cities.csv")
RESPONSES_PER_TASK = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- 'pending' | 'done'
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    records_page_url TEXT,
    records_page_missing INTEGER NOT NULL DEFAULT 0,
    records_email TEXT,
    records_email_missing INTEGER NOT NULL DEFAULT 0,
    data_portal_url TEXT,
    data_portal_missing INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    submitted_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

DROP TRIGGER IF EXISTS mark_task_done;
CREATE TRIGGER mark_task_done
AFTER INSERT ON responses
BEGIN
    UPDATE tasks SET status = 'done'
    WHERE id = NEW.task_id
      AND (SELECT COUNT(*) FROM responses WHERE task_id = NEW.task_id)
          >= (SELECT CAST(value AS INTEGER) FROM config WHERE key = 'responses_per_task');
END;
"""


def build(db_path, csv_path, responses_per_task=RESPONSES_PER_TASK):
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO config (key, value) VALUES ('responses_per_task', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(responses_per_task),),
        )
        already = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        if already:
            print(f"tasks table already has {already} rows; skipping city load.")
        else:
            with open(csv_path, newline="", encoding="utf-8") as f:
                rows = [(r["city"].strip(), r["state"].strip())
                        for r in csv.DictReader(f)]
            conn.executemany(
                "INSERT INTO tasks (city, state) VALUES (?, ?)", rows)
            print(f"Loaded {len(rows)} city tasks.")
        conn.commit()
    finally:
        conn.close()
    print(f"Database ready: {db_path}")


if __name__ == "__main__":
    build(DB_PATH, CSV_PATH)
