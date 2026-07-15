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

## Quick start

    python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/python scripts/setup_census.py
    export DATASETTE_ROOT_PASSWORD_HASH=$(.venv/bin/python -c "from datasette_auth_passwords.utils import hash_password; print(hash_password('localdev'))")
    .venv/bin/datasette serve census.db assignments.db --internal internal.db -c datasette.yaml --secret dev -p 8001

Then open http://127.0.0.1:8001 (log in as `root` / `localdev` for admin).

## Running the tests

    .venv/bin/pytest
