# Notes & Caveats: Assignments on Datasette Apps

What we learned building a MuckRock Assignments-style crowdsourcing tool on
[Datasette Apps](https://datasette.io/blog/2026/datasette-apps/). Read this
before changing anything.

## Version pinning is load-bearing

Everything runs on **alpha software**: `datasette==1.0a35`,
`datasette-apps==0.1a3`, `datasette-auth-passwords==1.1.1` (see
`requirements.txt`). Datasette 1.0 alphas break plugin APIs between releases —
`datasette-upload-csvs` crashes the 1.0a35 homepage with
`AttributeError: 'Datasette' object has no attribute 'permission_allowed'`.
Test any plugin addition or version bump locally before deploying.

## No embeds: images yes, iframes/oEmbed no

The datasette-apps sandbox (`<iframe sandbox="allow-scripts allow-forms">` +
strict CSP) blocks all external content by default. Administrators can
allow-list origins via `plugins.datasette-apps.allowed_csp_origins`, and each
app must also opt in. Allowed origins map onto `img-src`, `script-src-elem`,
`style-src-elem`, and `connect-src` — **there is no `frame-src`**, so:

- You cannot embed a DocumentCloud viewer, YouTube video, map iframe, or any
  oEmbed content. This is a deliberate security restriction, not a bug.
- You CAN show documents as **page images**. DocumentCloud serves every page as
  an image: `https://s3.documentcloud.org/documents/{id}/pages/{slug}-p{page}-{size}.gif`
  (sizes: small, normal, large, xlarge). The Document Review app does this.
- Task images are rendered only when the URL starts with `http://` or `https://` (case-insensitive). Malformed or protocol-relative URLs are silently skipped.

## Permission gotchas (each of these bit us)

- **`allow: true`, never `{unauthenticated: true}`.** An allow block denies
  everyone who doesn't match. `{unauthenticated: true}` matches only logged-out
  users, so it silently locks out the signed-in admin — symptoms ranged from
  403s on stored queries to the app builder claiming "No databases are visible
  to you."
- **`permissions: {view-app: true}` is required** for anonymous visitors.
  datasette-apps auto-grants view-app only to an app's owner; without the
  instance-wide grant, logged-out users get 403 on public apps. Private apps
  stay owner-only regardless.
- Contributors never get write access to tables. The only write path is a
  stored query with `write: true`.

## Stored queries are single-statement → use triggers

Datasette stored write queries execute exactly one SQL statement. Any side
effect ("mark the task done when it has enough responses") must be a SQLite
**trigger** (see `mark_task_done` in `scripts/setup_census.py`). The
`responses_per_task` value lives in the `config` table so the app, the
task-selection SQL, and the trigger all read one number.

## Next task selection respects assignment status

The `next_task` query includes a guard: `AND (SELECT value FROM a_{slug}_config WHERE key='status') = 'open'`. No new tasks are offered once the assignment is closed, preventing submissions after the collection window ends.

## Contributors are anonymous — design for it

- Duplicate prevention is per-browser-session (`sessionStorage`). The same
  person in two browsers (or after closing the tab) can answer the same task
  again. Mitigation: collect `responses_per_task` (default 3) independent
  answers per task and reconcile afterwards in SQL.
- "Skip" is client-side only, so one person skipping never hides a task from
  everyone else.
- There is no spam protection beyond redundancy. For a public launch beyond a
  demo, consider rate limiting at the proxy or requiring login.
- Benign race: two simultaneous submitters can both land the Nth response for
  a task. Harmless — extra data, and the trigger still marks it done.

## Apps live in internal.db — treat it as data

App HTML, revisions, and settings live in the **internal database**
(`--internal internal.db` locally, `--internal /data/internal.db` in
production — see `deploy/entrypoint.sh`), not in `datasette.yaml`. Under version control here,
the repo's `apps/*.html` files are the source of truth and
`scripts/sync_apps.py` upserts them (idempotently, as new revisions) into
`internal.db`. If you edit an app in the datasette-apps web editor instead,
copy the HTML back into `apps/` or the next sync will overwrite it. Note:
`scripts/sync_apps.py` matches apps by NAME — renaming an app in the web editor
breaks the match and the next sync will create a duplicate instead of updating.

Updating the **production** app HTML: deploys never touch the live
`/data/internal.db` (by design), so after changing `apps/*.html` either log in
as root and paste the new HTML in the app editor, or run the sync against the
volume from an ssh console.

## Write paths and app submission

Two distinct write paths exist and behave differently: apps write through the
datasette-apps bridge endpoint `POST /-/apps/<id>/query` with JSON `{database,
query, params}`, which returns `{"ok": true, ...}` — while a direct browser/curl
POST to `/census/submit_response` returns HTTP 302 (form-redirect semantics).
Test the bridge endpoint when debugging the app; the 302 on the direct endpoint
is not a bug.

## Deployment invariants (Fly.io)

- All three databases live on the persistent volume (`/data`). The Docker
  image carries seed copies; `deploy/entrypoint.sh` installs them **only if
  the file doesn't exist** — a deploy must never overwrite live responses.
- Single machine only (`fly deploy --ha=false`): SQLite on a volume cannot be
  shared across machines.
- `DATASETTE_SECRET` must be a stable Fly secret, or every restart invalidates
  signed cookies (admin logins).
- Admin login: datasette-auth-passwords with the hash in the
  `DATASETTE_ROOT_PASSWORD_HASH` secret. Config shape that works on 1.0a35:
  `root_password_hash: {$env: DATASETTE_ROOT_PASSWORD_HASH}`.
- `auto_stop_machines`/`auto_start_machines` keep cost ≈ $2–4/month; cold
  start is ~1s.
- Fly.io has no `bos` region; this instance runs in `iad` (Ashburn). Check
  `fly platform regions` before assuming a region.

## The assignments plugin (phase 2)

`plugins/datasette-assignments` is a Datasette plugin that replaces the
hand-crafted census workflow with a no-code wizard. Key internals worth
knowing before you change anything:

- **Registry lives in the internal DB.** `assignments_registry` in
  `internal.db` tracks every assignment (slug, owner, app_id, definition
  JSON). The plugin's `startup` hook creates it if absent.

- **The execute-sql denial is what makes private responses real.** The plugin
  registers a `permission_resources_sql` hook that (a) denies `execute-sql`
  on the data DB for all non-root actors and (b) denies `view-table` on
  `a_<slug>_responses` tables to anyone other than the assignment owner and
  root. Without (a), any logged-in user could bypass (b) by running raw SQL.
  Root is exempted in both cases so the admin can always inspect data.

- **Apps are stored-query-only.** Each generated app can call only the
  queries explicitly listed when the app was created (`submit_<slug>`,
  `next_task_<slug>` if tasks mode, `progress_<slug>`). This is enforced by
  datasette-apps; the app cannot issue arbitrary SQL.

- **Stored queries are `is_trusted`.** `is_trusted=True` bypasses the
  execute-sql permission check for that specific query when the app calls it.
  This is what lets the progress and next_task read queries work for anonymous
  contributors on an instance that denies raw SQL. The SQL is plugin-generated
  and immutable, so the trust is safe.

- **Uninstall removes all permission enforcement.** The
  `permission_resources_sql` hook is only active while the plugin is
  installed. If you uninstall, the `a_<slug>_responses` tables revert to
  whatever the instance-level permissions allow — potentially public.
  Always delete assignments through the plugin UI before uninstalling, or add
  explicit deny blocks to `datasette.yaml`.

## Misc

- DocumentCloud's API rejects Python's default urllib User-Agent — send a
  custom one (see `scripts/setup_documents.py`).
- The `datasette.query()` JS API is read-only; writes go through
  `datasette.storedQuery(db, name, params)`.
- App task-selection uses `ORDER BY RANDOM()` — fine at this scale (50–10k
  tasks); revisit if you load hundreds of thousands.
