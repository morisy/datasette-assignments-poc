"""Route handlers for datasette-assignments views."""
import csv
import io
import json
import re as _re

from datasette import Forbidden, NotFound, Response

from . import get_data_db_name
from . import registry
from .creator import CreationError, create_assignment, destroy_assignment, insert_tasks, seed_config
from .render import render_app_html
from .schema import DefinitionError, extract_image_origins, merge_editable, sanitize_identifier, slugify, validate_definition


def _actor_id(request):
    return (request.actor or {}).get("id")


def _require_actor(request):
    if not request.actor:
        raise Forbidden("Sign in required")
    return request.actor


async def _require_owner_or_root(datasette, request, slug):
    actor = _require_actor(request)
    actor_id = actor.get("id")
    row = await registry.get(datasette, slug)
    if not row:
        raise NotFound(f"Assignment {slug!r} not found")
    if actor_id != "root" and row["owner_id"] != actor_id:
        raise Forbidden("Owner or root access required")
    return row


# ── List ──────────────────────────────────────────────────────────────────────

async def _assignment_progress(db, slug, mode):
    """Fetch per-assignment progress stats; returns a dict (empty on error)."""
    try:
        if mode == "tasks":
            result = await db.execute(
                f"SELECT"
                f" (SELECT COUNT(*) FROM a_{slug}_tasks) AS total,"
                f" (SELECT COUNT(*) FROM a_{slug}_tasks WHERE status='done') AS done"
            )
            r = result.first()
            return dict(r) if r else {}
        else:
            result = await db.execute(
                f"SELECT COUNT(*) AS collected FROM a_{slug}_responses"
            )
            r = result.first()
            return dict(r) if r else {}
    except Exception:
        return {}


async def assignments_list(datasette, request):
    _require_actor(request)
    assignments = await registry.list_for(datasette, request.actor)

    db_name = get_data_db_name(datasette)
    db = datasette.get_database(db_name)

    # Attach per-assignment progress (tasks: done/total; form: collected count)
    enriched = []
    for a in assignments:
        slug = a["slug"]
        mode = (a.get("definition") or {}).get("mode", "form")
        progress = await _assignment_progress(db, slug, mode)
        enriched.append({"assignment": a, "progress": progress, "mode": mode})

    return Response.html(
        await datasette.render_template(
            "assignments_list.html",
            {"enriched": enriched},
            request=request,
        )
    )


# ── Wizard (new) ──────────────────────────────────────────────────────────────

async def assignments_new(datasette, request):
    actor = _require_actor(request)
    db_name = get_data_db_name(datasette)
    errors = []
    definition_json = ""

    if request.method == "POST":
        post = await request.post_vars()
        definition_json = post.get("definition", "")
        tasks_csv_text = post.get("tasks_csv", "")

        try:
            raw_defn = json.loads(definition_json) if definition_json else {}
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(f"Invalid JSON: {exc}")
            raw_defn = {}

        if not errors:
            # Auto-derive slug if blank
            if not raw_defn.get("slug") and raw_defn.get("name"):
                raw_defn["slug"] = slugify(raw_defn["name"])

            # Parse CSV and inject task_columns
            task_rows = []
            if tasks_csv_text.strip():
                reader = csv.DictReader(io.StringIO(tasks_csv_text))
                raw_headers = reader.fieldnames or []
                # Sanitize headers with deduplication
                seen_headers = set()
                sanitized_headers = []
                for h in raw_headers:
                    try:
                        safe = sanitize_identifier(h, existing=tuple(seen_headers))
                    except DefinitionError:
                        safe = f"col_{len(sanitized_headers) + 1}"
                    seen_headers.add(safe)
                    sanitized_headers.append(safe)

                header_map = dict(zip(raw_headers, sanitized_headers))
                raw_defn["task_columns"] = sanitized_headers

                row_count = 0
                for row in reader:
                    if row_count >= 10000:
                        errors.append("CSV exceeds 10,000 row limit")
                        break
                    task_rows.append(
                        {header_map[k]: v for k, v in row.items() if k in header_map}
                    )
                    row_count += 1

                # For tasks mode, set task_title_column to first col if not set
                if raw_defn.get("mode") == "tasks" and sanitized_headers:
                    if not raw_defn.get("task_title_column"):
                        raw_defn["task_title_column"] = sanitized_headers[0]
            else:
                if raw_defn.get("mode") == "tasks":
                    raw_defn.setdefault("task_columns", [])

        if not errors:
            try:
                defn = validate_definition(raw_defn)
                await create_assignment(datasette, defn, actor,
                                        task_rows=task_rows if task_rows else None)
                return Response.redirect(f"/-/assignments/{defn['slug']}")
            except DefinitionError as exc:
                errors = exc.errors
                definition_json = json.dumps(raw_defn, indent=2)
            except CreationError as exc:
                errors = [str(exc)]
                definition_json = json.dumps(raw_defn, indent=2)

    return Response.html(
        await datasette.render_template(
            "assignments_new.html",
            {
                "errors": errors,
                "definition_json": definition_json,
                "db_name": db_name,
            },
            request=request,
        )
    )


# ── Edit (copy-edits only) ────────────────────────────────────────────────────

async def assignments_edit(datasette, request):
    slug = request.url_vars["slug"]
    row = await _require_owner_or_root(datasette, request, slug)
    db_name = get_data_db_name(datasette)
    stored_defn = row["definition"]
    errors = []
    definition_json = ""
    hand_edit_warning = False
    confirm_overwrite_needed = False

    # Detect hand-edit: compare current app HTML to what we'd generate
    app_id = row.get("app_id", "")
    current_html = None
    if app_id:
        try:
            from datasette_apps.registry import Registry as AppsRegistry
            apps_registry = AppsRegistry(datasette)
            version = await apps_registry.get_current_version(app_id)
            if version:
                current_html = version.get("html", "")
        except Exception:
            current_html = None

    if current_html is not None:
        expected_html = render_app_html(stored_defn, db_name)
        if current_html != expected_html:
            hand_edit_warning = True
            confirm_overwrite_needed = True

    if request.method == "POST":
        post = await request.post_vars()
        definition_json = post.get("definition", "")

        # Hand-edit guard: require confirm_overwrite if needed
        if confirm_overwrite_needed and not post.get("confirm_overwrite"):
            errors.append(
                "This app's HTML was customized by hand; check the box to confirm overwrite."
            )

        if not errors:
            try:
                raw_posted = json.loads(definition_json) if definition_json else {}
            except (json.JSONDecodeError, ValueError) as exc:
                errors.append(f"Invalid JSON: {exc}")
                raw_posted = {}

        if not errors:
            try:
                merged = merge_editable(stored_defn, raw_posted)
                validated = validate_definition(merged)
                # Regenerate the app HTML FIRST; if this fails we leave the
                # registry untouched so there is no stranded state.
                new_html = render_app_html(validated, db_name)
                if app_id:
                    from datasette_apps.registry import Registry as AppsRegistry
                    apps_registry = AppsRegistry(datasette)
                    try:
                        await apps_registry.update_stored_app(
                            app_id,
                            validated["name"],
                            (validated.get("instructions") or "")[:200],
                            new_html,
                            actor_id=_actor_id(request),
                        )
                    except Exception as app_exc:
                        errors.append(
                            f"Couldn't update the app: {app_exc}; nothing was saved"
                        )
                if not errors:
                    # App update succeeded (or there was no app); now persist to
                    # registry.  If this internal DB write fails, let it
                    # propagate — datasette will 500, and the next successful
                    # save self-heals the one-off warning.
                    await registry.update_definition(datasette, slug, validated)
                    return Response.redirect(f"/-/assignments/{slug}")
            except DefinitionError as exc:
                errors = exc.errors
            except Exception as exc:
                errors = [str(exc)]

        definition_json = definition_json or json.dumps(stored_defn, indent=2)
    else:
        definition_json = json.dumps(stored_defn, indent=2)

    return Response.html(
        await datasette.render_template(
            "assignments_new.html",
            {
                "errors": errors,
                "definition_json": definition_json,
                "db_name": db_name,
                "edit_mode": True,
                "slug": slug,
                "hand_edit_warning": hand_edit_warning,
                "confirm_overwrite_needed": confirm_overwrite_needed,
            },
            request=request,
        )
    )


# ── Preview ───────────────────────────────────────────────────────────────────

async def assignments_preview(datasette, request):
    _require_actor(request)
    if request.method != "POST":
        return Response.text("POST required", status=405)
    post = await request.post_vars()
    definition_json = post.get("definition", "")
    db_name = get_data_db_name(datasette)
    try:
        defn = json.loads(definition_json) if definition_json else {}
        validated = validate_definition(defn)
        html = render_app_html(validated, db_name, preview=True)
        return Response.html(html)
    except (json.JSONDecodeError, ValueError) as exc:
        return Response.text(f"Invalid JSON: {exc}", status=400)
    except DefinitionError as exc:
        return Response.text("\n".join(exc.errors), status=400)


# ── Manage ────────────────────────────────────────────────────────────────────

async def assignments_manage(datasette, request):
    slug = request.url_vars["slug"]
    row = await _require_owner_or_root(datasette, request, slug)

    db_name = get_data_db_name(datasette)
    db = datasette.get_database(db_name)
    defn = row["definition"]
    mode = defn.get("mode", "form")

    # Compute progress server-side (plugin code bypasses permission gate)
    progress = {}
    try:
        if mode == "tasks":
            result = await db.execute(
                f"SELECT (SELECT COUNT(*) FROM a_{slug}_tasks) AS total,"
                f" (SELECT COUNT(*) FROM a_{slug}_tasks WHERE status='done') AS done,"
                f" (SELECT COUNT(*) FROM a_{slug}_responses) AS collected,"
                f" (SELECT CAST(value AS INTEGER) FROM a_{slug}_config"
                f" WHERE key='responses_per_task') AS target,"
                f" (SELECT value FROM a_{slug}_config WHERE key='status') AS status"
            )
        else:
            result = await db.execute(
                f"SELECT (SELECT COUNT(*) FROM a_{slug}_responses) AS collected,"
                f" (SELECT value FROM a_{slug}_config WHERE key='status') AS status"
            )
        r = result.first()
        progress = dict(r) if r else {}
    except Exception:
        progress = {}

    # Latest 200 responses
    responses = []
    try:
        resp_cols_result = await db.execute(
            f"PRAGMA table_info(a_{slug}_responses)"
        )
        col_names = [r[1] for r in resp_cols_result.rows]
        result = await db.execute(
            f"SELECT * FROM a_{slug}_responses ORDER BY id DESC LIMIT 200"
        )
        responses = [dict(zip(col_names, r)) for r in result.rows]
    except Exception:
        responses = []

    # Check if public view exists
    has_public_view = False
    try:
        result = await db.execute(
            f"SELECT name FROM sqlite_master WHERE type='view' AND name='a_{slug}_public'"
        )
        has_public_view = result.first() is not None
    except Exception:
        pass

    # Check if any gallery fields exist
    has_gallery_fields = any(
        f.get("kind") == "input" and f.get("gallery")
        for f in defn.get("fields", [])
    )

    return Response.html(
        await datasette.render_template(
            "assignments_manage.html",
            {
                "row": row,
                "defn": defn,
                "slug": slug,
                "progress": progress,
                "responses": responses,
                "has_public_view": has_public_view,
                "has_gallery_fields": has_gallery_fields,
                "db_name": db_name,
                "app_id": row.get("app_id", ""),
            },
            request=request,
        )
    )


# ── Toggle status ─────────────────────────────────────────────────────────────

async def assignments_toggle_status(datasette, request):
    slug = request.url_vars["slug"]
    await _require_owner_or_root(datasette, request, slug)
    if request.method != "POST":
        return Response.redirect(f"/-/assignments/{slug}")

    db_name = get_data_db_name(datasette)
    db = datasette.get_database(db_name)
    result = await db.execute(
        f"SELECT value FROM a_{slug}_config WHERE key='status'"
    )
    row = result.first()
    current = row[0] if row else "open"
    new_status = "closed" if current == "open" else "open"
    await db.execute_write(
        f"UPDATE a_{slug}_config SET value=? WHERE key='status'",
        [new_status]
    )
    return Response.redirect(f"/-/assignments/{slug}")


# ── Update target ─────────────────────────────────────────────────────────────

async def assignments_target(datasette, request):
    slug = request.url_vars["slug"]
    await _require_owner_or_root(datasette, request, slug)
    if request.method != "POST":
        return Response.redirect(f"/-/assignments/{slug}")

    post = await request.post_vars()
    try:
        target = int(post.get("responses_per_task", ""))
    except (ValueError, TypeError):
        return Response.text("responses_per_task must be an integer >= 1", status=400)

    if target < 1:
        return Response.text("responses_per_task must be an integer >= 1", status=400)

    db_name = get_data_db_name(datasette)
    db = datasette.get_database(db_name)
    await db.execute_write(
        f"UPDATE a_{slug}_config SET value=? WHERE key='responses_per_task'",
        [str(target)]
    )
    return Response.redirect(f"/-/assignments/{slug}")


# ── Response public toggle ────────────────────────────────────────────────────

async def assignments_response_public(datasette, request):
    slug = request.url_vars["slug"]
    await _require_owner_or_root(datasette, request, slug)
    if request.method != "POST":
        return Response.redirect(f"/-/assignments/{slug}")

    post = await request.post_vars()
    try:
        resp_id = int(post.get("id", ""))
    except (ValueError, TypeError):
        return Response.text("id must be an integer", status=400)
    public = 1 if post.get("public", "0") in ("1", "true", "yes") else 0

    db_name = get_data_db_name(datasette)
    db = datasette.get_database(db_name)
    await db.execute_write(
        f"UPDATE a_{slug}_responses SET is_public=? WHERE id=?",
        [public, resp_id]
    )
    return Response.redirect(f"/-/assignments/{slug}")


# ── Delete ────────────────────────────────────────────────────────────────────

async def assignments_delete(datasette, request):
    slug = request.url_vars["slug"]
    await _require_owner_or_root(datasette, request, slug)
    if request.method != "POST":
        return Response.redirect(f"/-/assignments/{slug}")

    post = await request.post_vars()
    confirm = post.get("confirm", "")
    if confirm != slug:
        return Response.redirect(f"/-/assignments/{slug}")

    await destroy_assignment(datasette, slug)
    return Response.redirect("/-/assignments")


# ── Add tasks ─────────────────────────────────────────────────────────────────

async def assignments_add_tasks(datasette, request):
    slug = request.url_vars["slug"]
    row = await _require_owner_or_root(datasette, request, slug)

    if request.method != "POST":
        return Response.redirect(f"/-/assignments/{slug}")

    defn = row["definition"]
    if defn.get("mode") != "tasks":
        return Response.text("Not a task-list assignment", status=400)

    post = await request.post_vars()
    tasks_csv_text = post.get("tasks_csv", "")

    if not tasks_csv_text.strip():
        return Response.text("tasks_csv is required", status=400)

    reader = csv.DictReader(io.StringIO(tasks_csv_text))
    raw_headers = reader.fieldnames or []

    # Sanitize headers exactly like the wizard
    seen_headers: set = set()
    sanitized_headers = []
    for h in raw_headers:
        try:
            safe = sanitize_identifier(h, existing=tuple(seen_headers))
        except DefinitionError:
            safe = f"col_{len(sanitized_headers) + 1}"
        seen_headers.add(safe)
        sanitized_headers.append(safe)

    # Compare as sets against stored task_columns
    stored_cols = set(defn.get("task_columns") or [])
    posted_cols = set(sanitized_headers)
    if stored_cols != posted_cols:
        missing = stored_cols - posted_cols
        extra = posted_cols - stored_cols
        parts = []
        if missing:
            parts.append(f"missing columns: {', '.join(sorted(missing))}")
        if extra:
            parts.append(f"extra columns: {', '.join(sorted(extra))}")
        return Response.text(f"Column mismatch — {'; '.join(parts)}", status=400)

    header_map = dict(zip(raw_headers, sanitized_headers))
    task_rows = []
    row_count = 0
    for r in reader:
        if row_count >= 10000:
            return Response.text("CSV exceeds 10,000 row limit", status=400)
        task_rows.append({header_map[k]: v for k, v in r.items() if k in header_map})
        row_count += 1

    if task_rows:
        # ── Origin check for new rows ─────────────────────────────────────────
        new_origins = extract_image_origins(defn, task_rows)
        if new_origins:
            from datasette_apps.registry import Registry as AppsRegistry
            apps_reg = AppsRegistry(datasette)
            app_id = row.get("app_id", "")
            existing_csp = set(await apps_reg.get_csp_origins(app_id)) if app_id else set()
            truly_new = new_origins - existing_csp
            if truly_new:
                # Normalize approved list from plugin config
                from urllib.parse import urlsplit as _urlsplit
                def _norm(o):
                    o = o.strip()
                    if "://" not in o:
                        o = f"https://{o}"
                    p = _urlsplit(o)
                    return f"https://{p.netloc.lower()}"
                approved_raw = (
                    (datasette.plugin_config("datasette-apps") or {})
                    .get("allowed_csp_origins") or []
                )
                approved_normalized = {_norm(o) for o in approved_raw}
                unapproved = truly_new - approved_normalized
                if unapproved:
                    approved_list = (
                        ", ".join(sorted(approved_normalized))
                        if approved_normalized else "(none)"
                    )
                    return Response.text(
                        f"Images from {', '.join(sorted(unapproved))} can't be shown "
                        f"until your administrator adds it to allowed_csp_origins in "
                        f"the Datasette config. Currently approved: {approved_list}.",
                        status=400,
                    )
                # All truly new origins are approved — merge into app's CSP
                merged_csp = sorted(existing_csp | truly_new)
                version = await apps_reg.get_current_version(app_id)
                if version and app_id:
                    await apps_reg.update_stored_app(
                        app_id,
                        version["name"],
                        version["description"],
                        version["html"],
                        actor_id=_actor_id(request),
                        csp_origins=merged_csp,
                    )
        await insert_tasks(datasette, defn, task_rows)

    return Response.redirect(f"/-/assignments/{slug}?added={len(task_rows)}")


# ── Gallery (public) ──────────────────────────────────────────────────────────

async def assignments_gallery(datasette, request):
    slug = request.url_vars["slug"]
    row = await registry.get(datasette, slug)
    if not row:
        raise NotFound(f"Assignment {slug!r} not found")

    defn = row["definition"]

    # Collect gallery-flagged input fields (with their labels)
    gallery_fields = [
        f for f in defn.get("fields", [])
        if f.get("kind") == "input" and f.get("gallery")
    ]
    if not gallery_fields:
        raise NotFound(f"Assignment {slug!r} has no gallery fields")

    # Pagination
    try:
        page = max(1, int(request.args.get("page", "1") or 1))
    except (ValueError, TypeError):
        page = 1

    gallery_col_ids = [f["id"] for f in gallery_fields]
    cols_sql = ", ".join(gallery_col_ids)
    offset = (page - 1) * 50

    db_name = get_data_db_name(datasette)
    db = datasette.get_database(db_name)

    # Fetch total public count
    count_result = await db.execute(
        f"SELECT COUNT(*) FROM a_{slug}_responses WHERE is_public = 1"
    )
    total_count = count_result.first()[0]

    # Fetch 51 to detect has-next
    rows_result = await db.execute(
        f"SELECT id, {cols_sql}, submitted_at FROM a_{slug}_responses"
        f" WHERE is_public = 1 ORDER BY id DESC LIMIT 51 OFFSET ?",
        [offset],
    )
    raw_rows = rows_result.rows
    has_next = len(raw_rows) > 50
    raw_rows = raw_rows[:50]

    # Build card dicts: [{label, value, is_url}, ...]
    _url_re = _re.compile(r'^https?://')
    cards = []
    for r in raw_rows:
        fields_out = []
        for i, fld in enumerate(gallery_fields):
            val = r[i + 1]  # offset 0 = id
            val_str = str(val) if val is not None else ""
            fields_out.append({
                "label": fld["label"],
                "value": val_str,
                "is_url": bool(_url_re.match(val_str)),
            })
        cards.append({
            "id": r[0],
            "fields": fields_out,
            "submitted_at": r[-1],
        })

    app_id = row.get("app_id", "")

    return Response.html(
        await datasette.render_template(
            "assignments_gallery.html",
            {
                "defn": defn,
                "slug": slug,
                "gallery_fields": gallery_fields,
                "cards": cards,
                "page": page,
                "has_next": has_next,
                "total_count": total_count,
                "app_id": app_id,
            },
            request=request,
        )
    )


# ── CSV Export ────────────────────────────────────────────────────────────────

async def assignments_export_csv(datasette, request):
    slug = request.url_vars["slug"]
    await _require_owner_or_root(datasette, request, slug)

    db_name = get_data_db_name(datasette)
    db = datasette.get_database(db_name)

    # Get column names
    col_result = await db.execute(f"PRAGMA table_info(a_{slug}_responses)")
    col_names = [r[1] for r in col_result.rows]

    rows_result = await db.execute(f"SELECT * FROM a_{slug}_responses ORDER BY id")
    rows = rows_result.rows

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(col_names)
    for row in rows:
        writer.writerow(list(row))

    csv_body = output.getvalue()
    return Response(
        body=csv_body,
        status=200,
        headers={
            "content-type": "text/csv; charset=utf-8",
            "Content-Disposition": f'attachment; filename="a_{slug}_responses.csv"',
        },
    )
