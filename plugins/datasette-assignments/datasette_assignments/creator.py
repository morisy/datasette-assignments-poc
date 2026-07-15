"""Create/destroy all artifacts for an assignment. Creation is all-or-nothing:
on any failure, everything already created for that slug is destroyed."""
from datasette import stored_queries

from datasette_apps.registry import Registry as AppsRegistry

from . import registry
from .render import render_app_html
from .schema import build_ddl, build_queries, drop_ddl
from . import get_data_db_name


class CreationError(Exception):
    pass


async def _create_app(datasette, defn, actor_id, db_name, query_names):
    apps = AppsRegistry(datasette)
    app = await apps.create_stored_app(
        actor_id,
        defn["name"],
        (defn.get("instructions") or "")[:200],
        render_app_html(defn, db_name),
        is_private=False,
        sql_databases=[],
        stored_queries=[f"{db_name}/{q}" for q in query_names],
    )
    # create_stored_app returns the app dict from get_app() — normalize to id string
    return app["id"] if isinstance(app, dict) else app


async def create_assignment(datasette, defn, actor):
    db_name = get_data_db_name(datasette)
    db = datasette.get_database(db_name)
    slug = defn["slug"]
    if await registry.get(datasette, slug):
        raise CreationError(f"An assignment with slug {slug!r} already exists")
    created_queries, app_id = [], None
    try:
        for stmt in build_ddl(defn):
            await db.execute_write(stmt)
        await seed_config(datasette, defn)
        queries = build_queries(defn, db_name)
        for q in queries.values():
            await stored_queries.add_query(
                datasette, db_name, q["name"], q["sql"],
                is_write=q["is_write"],
                is_private=False,
                # is_trusted=True bypasses execute-write-sql permission checks,
                # enabling anonymous submissions (the intended UX for assignments).
                is_trusted=q["is_write"],
            )
            created_queries.append(q["name"])
        app_id = await _create_app(
            datasette, defn, (actor or {}).get("id") or "root",
            db_name, [q["name"] for q in queries.values()])
        await registry.create(datasette, defn, (actor or {}).get("id") or "root",
                              app_id)
        return await registry.get(datasette, slug)
    except Exception as e:
        await _cleanup(datasette, defn, created_queries, app_id)
        raise CreationError(str(e)) from e


async def seed_config(datasette, defn):
    db = datasette.get_database(get_data_db_name(datasette))
    slug = defn["slug"]
    if defn["mode"] == "tasks":
        await db.execute_write(
            f"INSERT INTO a_{slug}_config (key, value) VALUES "
            f"('responses_per_task', ?)", [str(defn["responses_per_task"])])
    await db.execute_write(
        f"INSERT INTO a_{slug}_config (key, value) VALUES ('status', 'open')")


async def insert_tasks(datasette, defn, rows):
    db = datasette.get_database(get_data_db_name(datasette))
    cols = defn["task_columns"]
    col_list = ", ".join(cols)
    placeholders = ", ".join("?" for _ in cols)
    for row in rows:
        await db.execute_write(
            f"INSERT INTO a_{defn['slug']}_tasks ({col_list}) "
            f"VALUES ({placeholders})",
            [row.get(c, "") for c in cols])


async def _cleanup(datasette, defn, created_queries, app_id):
    db_name = get_data_db_name(datasette)
    db = datasette.get_database(db_name)
    for stmt in drop_ddl(defn["slug"], defn["mode"]):
        try:
            await db.execute_write(stmt)
        except Exception:
            pass
    for name in created_queries:
        try:
            await stored_queries.remove_query(datasette, db_name, name)
        except Exception:
            pass
    if app_id:
        try:
            apps = AppsRegistry(datasette)
            await apps.delete_stored_app(app_id, actor_id="root")
        except Exception:
            pass
    try:
        await registry.delete(datasette, defn["slug"])
    except Exception:
        pass


async def destroy_assignment(datasette, slug):
    row = await registry.get(datasette, slug)
    if not row:
        return
    defn = row["definition"]
    queries = build_queries(defn, get_data_db_name(datasette))
    await _cleanup(datasette, defn, [q["name"] for q in queries.values()],
                   row["app_id"])
