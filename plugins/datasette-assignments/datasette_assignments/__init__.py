from datasette import hookimpl
from datasette.permissions import PermissionSQL
from . import registry as _registry

PLUGIN_NAME = "datasette-assignments"
DEFAULT_DATABASE = "assignments_data"


def get_data_db_name(datasette):
    config = datasette.plugin_config(PLUGIN_NAME) or {}
    return config.get("database", DEFAULT_DATABASE)


@hookimpl
def startup(datasette):
    async def inner():
        await _registry.ensure_table(datasette)
    return inner


@hookimpl
def register_routes():
    from . import views
    return [
        (r"^/-/assignments$", views.assignments_list),
        (r"^/-/assignments/new$", views.assignments_new),
        (r"^/-/assignments/preview$", views.assignments_preview),
        (r"^/-/assignments/(?P<slug>[a-z][a-z0-9_]{0,39})/export\.csv$",
         views.assignments_export_csv),
        (r"^/-/assignments/(?P<slug>[a-z][a-z0-9_]{0,39})/toggle-status$",
         views.assignments_toggle_status),
        (r"^/-/assignments/(?P<slug>[a-z][a-z0-9_]{0,39})/target$",
         views.assignments_target),
        (r"^/-/assignments/(?P<slug>[a-z][a-z0-9_]{0,39})/response-public$",
         views.assignments_response_public),
        (r"^/-/assignments/(?P<slug>[a-z][a-z0-9_]{0,39})/delete$",
         views.assignments_delete),
        (r"^/-/assignments/(?P<slug>[a-z][a-z0-9_]{0,39})/edit$",
         views.assignments_edit),
        (r"^/-/assignments/(?P<slug>[a-z][a-z0-9_]{0,39})/gallery$",
         views.assignments_gallery),
        (r"^/-/assignments/(?P<slug>[a-z][a-z0-9_]{0,39})$",
         views.assignments_manage),
    ]


@hookimpl
def menu_links(datasette, actor, request):
    if actor:
        return [{"href": "/-/assignments", "label": "Assignments"}]
    return []


@hookimpl
def permission_resources_sql(datasette, actor, action):
    actor_id = actor.get("id") if actor else None
    data_db = get_data_db_name(datasette)

    # Only handle view-table and execute-sql; return None for everything else.
    if action not in ("view-table", "execute-sql"):
        return None

    # Root can do anything — skip our deny rules.
    if actor_id == "root":
        return None

    if action == "execute-sql":
        # Deny execute-sql on the data DB for all non-root actors.
        sql = """
        SELECT :da_db AS parent,
               NULL   AS child,
               0      AS allow,
               'assignments: execute-sql denied on data DB for non-root' AS reason
        """
        return PermissionSQL(
            source=PLUGIN_NAME,
            sql=sql,
            params={"da_db": data_db},
        )

    # action == "view-table"
    # Deny view-table on every a_<slug>_responses table whose owner is NOT
    # the current actor.  The query runs against the internal DB where
    # assignments_registry lives.
    if actor_id is not None:
        # Authenticated non-owner: deny all response tables not owned by this actor.
        sql = """
        SELECT :da_db                              AS parent,
               'a_' || slug || '_responses'        AS child,
               0                                  AS allow,
               'assignments: responses table is private' AS reason
        FROM assignments_registry
        WHERE owner_id != :da_actor_id
        UNION ALL
        SELECT :da_db                              AS parent,
               'a_' || slug || '_responses'        AS child,
               1                                  AS allow,
               'assignments: responses table visible to owner' AS reason
        FROM assignments_registry
        WHERE owner_id = :da_actor_id
        """
        return PermissionSQL(
            source=PLUGIN_NAME,
            sql=sql,
            params={"da_db": data_db, "da_actor_id": actor_id},
        )
    else:
        # Anonymous actor: deny all response tables.
        sql = """
        SELECT :da_db                              AS parent,
               'a_' || slug || '_responses'        AS child,
               0                                  AS allow,
               'assignments: responses table is private' AS reason
        FROM assignments_registry
        """
        return PermissionSQL(
            source=PLUGIN_NAME,
            sql=sql,
            params={"da_db": data_db},
        )
