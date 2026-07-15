from datasette import hookimpl

PLUGIN_NAME = "datasette-assignments"
DEFAULT_DATABASE = "assignments_data"


def get_data_db_name(datasette):
    config = datasette.plugin_config(PLUGIN_NAME) or {}
    return config.get("database", DEFAULT_DATABASE)
