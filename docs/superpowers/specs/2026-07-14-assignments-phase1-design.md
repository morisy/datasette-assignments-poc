# Datasette Assignments — Phase 1 Design

**Date:** 2026-07-14
**Status:** Approved by user (hosting, domain, audience, demo content, city count confirmed via Q&A)
**Phase 2 (separate spec, after phase 1 ships):** a Datasette plugin providing a WYSIWYG builder for Assignment-style crowdsourcing apps.

## Goal

Turn the working local prototype (a MuckRock Assignments-style crowdsourcing tool built on Datasette Apps) into:

1. `NOTES.md` — important notes, caveats, and institutional knowledge.
2. `TUTORIAL.md` — a friendly, user-facing tutorial for setting up an Assignments-like crowdsourcing tool. Two tracks: a plain-language main path for journalists/nonprofits, with collapsible "under the hood" asides for developers.
3. A production demo on Fly.io: full Datasette instance + the Assignments app, with persistent contributor data.

## Background: the prototype

- Datasette **1.0a35** + **datasette-apps 0.1a3** (both alphas; exact pinning is load-bearing).
- `assignments.db`: `tasks`, `responses`, `config` tables. A SQL trigger (`mark_task_done`) flips a task to `done` once it has `responses_per_task` (default 3) responses — needed because Datasette stored write queries are single-statement.
- `app.html`: single-file app rendered in a sandboxed iframe by datasette-apps; reads via `datasette.query()`, writes only via the `submit_response` stored query.
- `datasette.yaml`: `allow: true`, `allow_sql: true`, `permissions: {view-app: true}`, CSP origin allow-list.
- One app saved in `internal.db`: "Assignment Tool Test" (Document Review — DocumentCloud page-image transcription, 42 page tasks).
- Known breakage: `datasette-upload-csvs` crashes Datasette 1.0a35 homepage (`permission_allowed` removed in the alpha); it and other experimental plugins stay out of production.

## Demo assignment: "City Public Records Census"

Each task is one of the **top 50 US cities by population**, pre-seeded with the city's official website URL (so contributors aren't googling blind). A contributor is shown one city and asked to find, on the city's official site:

1. **Public records request page** — URL, or flag "couldn't find one"
2. **Public records email address** — email, or flag "couldn't find one"
3. **Open data portal** — URL, or flag "couldn't find one"

Plus optional free-text **notes**. Each of the three items must have either a value or its "couldn't find" checkbox checked before submit — a flagged absence is data, not a skipped field. Client-side validation: URL shape for the two URL fields, email shape for the email field. A "Skip" button is session-local only (sessionStorage), so one person skipping never removes a city for everyone.

**Contributor-facing progress bar** (carried over from prototype): "X of 50 cities fully verified" plus a fill bar of total responses collected toward the goal (50 × responses_per_task).

The existing **Document Review** app stays on the instance as a second example — it demonstrates the image-embedding technique (documents can be shown as page *images* from CSP-allow-listed origins; iframes/oEmbed are impossible under the datasette-apps sandbox).

### Schema

`tasks`: `id`, `city`, `state`, `website` (official .gov URL), `status` ('pending'|'done'), `created_at`.

`responses`: `id`, `task_id → tasks.id`, `records_page_url`, `records_page_missing` (0/1), `records_email`, `records_email_missing` (0/1), `data_portal_url`, `data_portal_missing` (0/1), `notes`, `submitted_at`.

`config`: `key`, `value` — holds `responses_per_task` (default 3). The app, the task-selection SQL, and the `mark_task_done` trigger all read this one value.

Built by `setup_census.py` from `cities.csv` (expanded to 50 rows: `city,state,website`). Idempotent: re-running never duplicates tasks or wipes responses.

### App (`app.html`, adapted from prototype)

- City card: city name, state, link to official website (opens new tab).
- Three field groups, each: text input + "couldn't find one" checkbox that disables/clears the input.
- Notes textarea, Submit, Skip, progress bar, toast feedback, "all done / all caught up" end states.
- Task selection SQL: random task with response count < `responses_per_task`, excluding sessionStorage-seen ids.
- Submit via stored query `submit_response` (write: true, allow: true — NOT `{unauthenticated: true}`, which locks out the admin).

## Deployment (Fly.io)

- **Dockerfile**: `python:3.12-slim`, pinned `datasette==1.0a35`, `datasette-apps==0.1a3`, auth plugin. Nothing else.
- **fly.toml**: single machine, 1GB volume at `/data` holding `assignments.db` + `internal.db`; `--internal /data/internal.db`. `auto_stop`/`auto_start` enabled (cold start ~1s; keeps cost ≈ $2–4/month). `DATASETTE_SECRET` as a Fly secret so signed cookies survive restarts.
- **Data seeding**: entrypoint script copies the repo's baked-in seed databases to `/data` **only if absent** — deploys never overwrite live contributor responses.
- **Admin auth**: `datasette-auth-passwords` with a password hash stored as a Fly secret; verify compatibility with 1.0a35 locally first. Fallback if incompatible: `datasette-auth-tokens`, or a signed root cookie via `datasette create-token`-style flow. Admin (root actor) gets the full Datasette experience: browse/facet/SQL/CSV-export over `tasks` and `responses`, plus the datasette-apps editor.
- **Anonymous visitors**: read everything, run read-only SQL, use the app; the only write path is the stored query.
- **URL**: `https://<app-name>.fly.dev` (no custom domain).
- **User-side steps** (Michael): create Fly.io account, add card, `fly auth login`. Everything else scripted.
- **Post-deploy smoke test**: submit a response via the live app, `fly machine restart`, confirm the response survived; confirm anonymous 200s on `/`, the app page, and a read SQL query; confirm admin login works.

## NOTES.md coverage

- **No oEmbed / no iframes** in apps — the sandbox CSP has no `frame-src`. Documents can only be embedded as images from admin-allow-listed origins (`allowed_csp_origins` + per-app opt-in). The `s3.documentcloud.org` page-image URL pattern as the worked example.
- **`allow: true` vs `{unauthenticated: true}`** — allow blocks deny everyone who doesn't match, so `{unauthenticated: true}` silently locks out the logged-in admin (bit this prototype twice: instance `allow` and the stored query).
- **`view-app` permission** — datasette-apps only auto-grants to the owner; without `permissions: {view-app: true}` anonymous visitors get 403 on public apps.
- **Single-statement stored queries** — side effects (marking tasks done) must live in SQL triggers.
- **Anonymous contributors** — dedup is per-browser-session (sessionStorage): no accounts, no strong protection against one person answering the same task twice from two browsers, or spam. `responses_per_task` redundancy is the mitigation. Benign race: two simultaneous submitters can both land the Nth response — harmless (extra data), documented.
- **Alpha churn** — 1.0a35 broke plugins (`datasette-upload-csvs` homepage 500 via removed `permission_allowed`); pin exact versions; test any plugin addition locally before deploying.
- **DocumentCloud API quirk** — rejects default urllib User-Agent; send a custom one.
- Anything else discovered during implementation gets appended.

## TUTORIAL.md shape

Main path (friendly, terminal-comfortable non-developer): install → describe your task as a CSV → run setup script → run Datasette locally → paste/create the app → try it → publish to Fly. Collapsible `<details>` asides per section for developers: the SQL, the trigger pattern, permission model, customizing the app HTML, the DocumentCloud image-embed variant, adapting to other task types.

## Testing

- Local before deploy: run the full stack exactly as production will (same pins, same `datasette.yaml`), curl the read/write paths, submit through the real app in a browser.
- Deploy-time: the smoke test above, including the restart-persistence check.
- `setup_census.py`: idempotency check (run twice, counts identical).

## Out of scope for phase 1

- The WYSIWYG plugin (phase 2, own design cycle).
- Contributor accounts/auth, anti-spam beyond redundancy, moderation UI.
- Custom domain, email notifications, multi-assignment routing UI (the Datasette homepage listing both apps is enough).
