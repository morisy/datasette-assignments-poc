"""Upsert this repo's app HTML files into datasette-apps' internal.db tables.

The repo files under apps/ are the source of truth; the datasette-apps web
editor is treated as a preview surface. Run after editing any app HTML:

    python scripts/sync_apps.py [--internal internal.db]

Matches apps by name. Appends a new app_revisions row (and bumps
apps.current_version) only when the HTML actually changed, mirroring how
the plugin's own editor saves revisions. Restart Datasette afterwards.
"""
import argparse
import json
import os
import secrets
import sqlite3
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..")

# Crockford base32, lowercased — matches the ULID-style ids datasette-apps generates.
ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


def make_ulid():
    ts = int(time.time() * 1000)
    chars = []
    for _ in range(10):
        chars.append(ALPHABET[ts & 31])
        ts >>= 5
    head = "".join(reversed(chars))
    tail = "".join(secrets.choice(ALPHABET) for _ in range(16))
    return head + tail


def now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def sync_app(internal_db, definition):
    """Create or update one app. Returns the app id."""
    conn = sqlite3.connect(internal_db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM apps WHERE name = ? AND deleted_at IS NULL",
            (definition["name"],)).fetchone()
        ts = now()
        stored_queries = json.dumps(definition["stored_queries"])
        sql_databases = json.dumps(definition["sql_databases"])

        if row is None:
            app_id = make_ulid()
            conn.execute(
                "INSERT INTO apps (id, external, name, description, path, source,"
                " metadata, actor_id, is_private, stored_queries, current_version,"
                " created_at, updated_at)"
                " VALUES (?, 0, ?, ?, ?, 'datasette-apps', '{}', 'root', ?, ?, 1, ?, ?)",
                (app_id, definition["name"], definition["description"],
                 f"/-/apps/{app_id}", definition["is_private"], stored_queries, ts, ts))
            conn.execute(
                "INSERT INTO app_revisions (app_id, version, actor_id, name,"
                " description, html, is_private, sql_databases, stored_queries,"
                " csp_origins, changed_fields, created_at)"
                " VALUES (?, 1, 'root', ?, ?, ?, ?, ?, ?, '[]', ?, ?)",
                (app_id, definition["name"], definition["description"],
                 definition["html"], definition["is_private"], sql_databases,
                 stored_queries,
                 json.dumps(["name", "description", "html", "is_private",
                             "sql_databases", "stored_queries"]), ts))
            print(f"created app {definition['name']!r} -> {app_id}")
        else:
            app_id = row["id"]
            current_html = conn.execute(
                "SELECT html FROM app_revisions WHERE app_id = ? AND version = ?",
                (app_id, row["current_version"])).fetchone()
            if current_html and current_html["html"] == definition["html"]:
                print(f"unchanged: {definition['name']!r} (version {row['current_version']})")
            else:
                new_version = row["current_version"] + 1
                conn.execute(
                    "INSERT INTO app_revisions (app_id, version, actor_id, name,"
                    " description, html, is_private, sql_databases, stored_queries,"
                    " csp_origins, changed_fields, created_at)"
                    " VALUES (?, ?, 'root', ?, ?, ?, ?, ?, ?, '[]', ?, ?)",
                    (app_id, new_version, definition["name"],
                     definition["description"], definition["html"],
                     definition["is_private"], sql_databases, stored_queries,
                     json.dumps(["html"]), ts))
                conn.execute(
                    "UPDATE apps SET current_version = ?, description = ?,"
                    " is_private = ?, stored_queries = ?, updated_at = ?"
                    " WHERE id = ?",
                    (new_version, definition["description"],
                     definition["is_private"], stored_queries, ts, app_id))
                print(f"updated {definition['name']!r} -> version {new_version}")

        for db_name in definition["sql_databases"]:
            conn.execute(
                "INSERT OR IGNORE INTO app_sql_databases"
                " (app_id, database_name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (app_id, db_name, ts, ts))
        conn.commit()
        return app_id
    finally:
        conn.close()


def read(path):
    with open(os.path.join(REPO, path), encoding="utf-8") as f:
        return f.read()


DEFINITIONS = [
    {
        "name": "City Public Records Census",
        "description": "Help build a public dataset: find each city's public "
                       "records page, records email, and open data portal.",
        "html": None,  # filled from apps/census.html below
        "html_path": "apps/census.html",
        "sql_databases": ["census"],
        "stored_queries": ["census/submit_response"],
        "is_private": 0,
    },
    {
        "name": "Document Review",
        "description": "Read one page of a public document and describe or "
                       "transcribe what's on it.",
        "html": None,
        "html_path": "apps/document_review.html",
        "sql_databases": ["assignments"],
        "stored_queries": ["assignments/submit_response"],
        "is_private": 0,
    },
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--internal", default=os.path.join(REPO, "internal.db"))
    args = parser.parse_args()
    for definition in DEFINITIONS:
        definition = dict(definition, html=read(definition.pop("html_path")))
        sync_app(args.internal, definition)
    print("Done. Restart Datasette to pick up changes.")


if __name__ == "__main__":
    main()
