# Datasette Assignments

A [MuckRock Assignments](https://www.muckrock.com/assignment/)-style
crowdsourcing tool built on [Datasette Apps](https://datasette.io/blog/2026/datasette-apps/).
Contributors work through small tasks one at a time; every response lands in a
SQLite database you can browse, query, and export through Datasette.

**Live demo:** https://records-census-demo.fly.dev — help build a census of
each big US city's public records page, records email, and open data portal.

- **[TUTORIAL.md](TUTORIAL.md)** — build and publish your own assignment
- **[NOTES.md](NOTES.md)** — caveats and lessons learned (read before hacking)

## Layout

| Path | What it is |
|---|---|
| `apps/*.html` | Assignment app source (synced into Datasette by `scripts/sync_apps.py`) |
| `scripts/setup_census.py` | Builds `census.db` from `cities.csv` |
| `scripts/setup_documents.py` | Builds `assignments.db` from DocumentCloud docs |
| `datasette.yaml` | Permissions + stored write queries |
| `Dockerfile`, `fly.toml`, `deploy/` | Fly.io deployment |
| `plugins/datasette-assignments/` | No-code assignment builder plugin ([README](plugins/datasette-assignments/README.md)) |

The `plugins/datasette-assignments` directory contains a Datasette plugin that
lets you create and manage assignments through a point-and-click wizard rather
than writing SQL and HTML by hand. Install it with
`pip install -e plugins/datasette-assignments`, log in as any authenticated
user, and visit `/-/assignments/new`. Every assignment gets its own responses
table, stored queries, and datasette-apps app — all artifacts are yours to
browse, query, and export. See the [plugin README](plugins/datasette-assignments/README.md)
for the full route list, privacy model, and uninstall warning.

## Quick start

    python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/python scripts/setup_census.py
    export DATASETTE_ROOT_PASSWORD_HASH=$(.venv/bin/python -c "from datasette_auth_passwords.utils import hash_password; print(hash_password('localdev'))")
    .venv/bin/datasette serve census.db assignments.db --internal internal.db -c datasette.yaml --secret dev -p 8001

Then open http://127.0.0.1:8001 (log in as `root` / `localdev` for admin).

## Running the tests

    .venv/bin/pytest
