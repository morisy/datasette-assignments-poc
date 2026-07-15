"""Set up the assignments SQLite database for DocumentCloud page review.

Reads document IDs from documents.csv, looks up each document's metadata from
the DocumentCloud API, and creates one task per page. Each task points at a
single page of a document, which the app renders as a page image.

Run with: python setup.py
"""

import csv
import json
import os
import sqlite3
import urllib.request

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "assignments.db")
CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "documents.csv")
API = "https://api.www.documentcloud.org/api/documents/{id}/"

# How many independent answers to collect for each page before it drops out of
# rotation. Change this one value to make the assignment more/less redundant.
RESPONSES_PER_TASK = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER NOT NULL,      -- DocumentCloud document id
    slug TEXT NOT NULL,           -- used to build the page image URL
    title TEXT,                   -- document title, for display
    page INTEGER NOT NULL,        -- 1-based page number
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'done'
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    answer TEXT NOT NULL,
    notes TEXT,
    submitted_at TEXT DEFAULT (datetime('now'))
);

-- Single source of truth for tunable settings. The app and the trigger below
-- both read responses_per_task from here, so there is one number to change.
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Datasette stored write queries can only run a single statement, so the
-- "mark this task done" step lives in a trigger. A page is only 'done' once it
-- has collected responses_per_task answers (multiple people review each page).
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


def fetch_document(doc_id):
    """Look up a DocumentCloud document's slug, title, and page count."""
    url = API.format(id=doc_id)
    # DocumentCloud's CDN rejects the default Python-urllib User-Agent.
    req = urllib.request.Request(url, headers={"User-Agent": "datasette-assignments/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    return {
        "doc_id": int(data["id"]),
        "slug": data["slug"],
        "title": data.get("title"),
        "page_count": int(data["page_count"]),
    }


def main():
    fresh = not os.path.exists(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)

        # Seed / refresh the tunable settings.
        conn.execute(
            "INSERT INTO config (key, value) VALUES ('responses_per_task', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(RESPONSES_PER_TASK),),
        )

        # Only load tasks if the table is empty, so re-running is safe.
        already = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        if already:
            print(f"tasks table already has {already} rows; skipping document load.")
        else:
            with open(CSV_PATH, newline="", encoding="utf-8") as f:
                doc_ids = [row["document_id"].strip() for row in csv.DictReader(f)]

            total_pages = 0
            for doc_id in doc_ids:
                doc = fetch_document(doc_id)
                rows = [
                    (doc["doc_id"], doc["slug"], doc["title"], page)
                    for page in range(1, doc["page_count"] + 1)
                ]
                conn.executemany(
                    "INSERT INTO tasks (doc_id, slug, title, page) VALUES (?, ?, ?, ?)",
                    rows,
                )
                total_pages += len(rows)
                print(f"  {doc['title']}: {doc['page_count']} pages")
            print(f"Loaded {total_pages} page tasks from {len(doc_ids)} document(s).")

        conn.commit()
    finally:
        conn.close()

    print(f"Database {'created' if fresh else 'updated'}: {DB_PATH}")


if __name__ == "__main__":
    main()
