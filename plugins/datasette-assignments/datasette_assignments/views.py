"""Route handlers for datasette-assignments views."""
import csv
import io
import json

from datasette import Forbidden, NotFound, Response

from . import get_data_db_name
from . import registry
from .creator import CreationError, create_assignment, destroy_assignment, insert_tasks, seed_config
from .render import render_app_html
from .schema import DefinitionError, merge_editable, sanitize_identifier, slugify, validate_definition


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

async def assignments_list(datasette, request):
    _require_actor(request)
    assignments = await registry.list_for(datasette, request.actor)
    return Response.html(
        await datasette.render_template(
            "assignments_list.html",
            {"assignments": assignments},
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
                # Update registry
                await registry.update_definition(datasette, slug, validated)
                # Regenerate the app HTML
                new_html = render_app_html(validated, db_name)
                if app_id:
                    try:
                        from datasette_apps.registry import Registry as AppsRegistry
                        apps_registry = AppsRegistry(datasette)
                        await apps_registry.update_stored_app(
                            app_id,
                            validated["name"],
                            (validated.get("instructions") or "")[:200],
                            new_html,
                            actor_id=_actor_id(request),
                        )
                    except Exception:
                        pass  # best-effort; registry already updated
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
