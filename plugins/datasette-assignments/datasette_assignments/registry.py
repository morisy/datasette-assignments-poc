"""assignments_registry lives in the INTERNAL database (like datasette-apps'
own tables) so permission_resources_sql can join against ownership."""
import json

TABLE_SQL = """CREATE TABLE IF NOT EXISTS assignments_registry (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    app_id TEXT NOT NULL,
    definition TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)"""


async def ensure_table(datasette):
    await datasette.get_internal_database().execute_write(TABLE_SQL)


async def create(datasette, defn, owner_id, app_id):
    await datasette.get_internal_database().execute_write(
        "INSERT INTO assignments_registry (slug, name, mode, owner_id, app_id,"
        " definition) VALUES (?, ?, ?, ?, ?, ?)",
        [defn["slug"], defn["name"], defn["mode"], owner_id, app_id,
         json.dumps(defn)],
    )


def _row_to_dict(row):
    d = dict(row)
    d["definition"] = json.loads(d["definition"])
    return d


async def get(datasette, slug):
    result = await datasette.get_internal_database().execute(
        "SELECT * FROM assignments_registry WHERE slug = ?", [slug])
    row = result.first()
    return _row_to_dict(row) if row else None


async def list_for(datasette, actor):
    actor_id = (actor or {}).get("id")
    db = datasette.get_internal_database()
    if actor_id == "root":
        result = await db.execute(
            "SELECT * FROM assignments_registry ORDER BY created_at DESC")
    else:
        result = await db.execute(
            "SELECT * FROM assignments_registry WHERE owner_id = ?"
            " ORDER BY created_at DESC", [actor_id])
    return [_row_to_dict(r) for r in result.rows]


async def update_definition(datasette, slug, defn):
    """Update the stored definition and name for an existing assignment."""
    await datasette.get_internal_database().execute_write(
        "UPDATE assignments_registry SET definition=?, name=? WHERE slug=?",
        [json.dumps(defn), defn["name"], slug],
    )


async def delete(datasette, slug):
    await datasette.get_internal_database().execute_write(
        "DELETE FROM assignments_registry WHERE slug = ?", [slug])
