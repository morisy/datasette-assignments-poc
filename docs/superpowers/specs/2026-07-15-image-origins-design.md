# Automatic Image-Origin Handling — Design

**Date:** 2026-07-15
**Status:** Approved by user; demo allow-list hosts confirmed: DocumentCloud, cdn.muckrock.com, Wikimedia.
**Scope:** creator/append enforcement + auto opt-in, builder origin-status indicator, demo config hosts. Tag `v0.3.2`.

## Server behavior

- Origin extraction: for tasks-mode definitions with `task_image_column`, collect `scheme://netloc` (lowercased, via `urllib.parse.urlsplit`) from that column's values across the task rows. Ignore values not starting `https?://` (mirrors the render-time guard). `http://` origins are rejected outright with "image hosts must use https".
- Admin allow-list read at runtime: `datasette.plugin_config("datasette-apps").get("allowed_csp_origins")` (empty list when unset). Comparison on normalized `https://host` form.
- `create_assignment`: all extracted origins allow-listed → pass them as `csp_origins=` to `create_stored_app` (auto opt-in). Any origin missing → `CreationError`: "Images from <origin> can't be shown until your administrator adds it to allowed_csp_origins in the Datasette config. Currently approved: <list or '(none)'>." Enforced in creator (single point); wizard surfaces the error like other CreationErrors.
- `add-tasks`: same extraction on the NEW rows; origins not yet opted-in on the app: allow-listed → merge into the app's opt-ins via `update_stored_app(..., csp_origins=merged)` (name/description/html passed through unchanged from current version); non-approved → 400 with the same message shape. No HTML regeneration.

## Builder indicator

- Template passes the admin allow-list as JSON (`window.__allowedCspOrigins`).
- When an Image column is selected and CSV parsed: builder.js extracts origins from that column's values and renders under the column picker: per-origin chip with ✓ (approved) or ⚠ "needs admin approval". Cleared when no image column/no rows.

## Demo config

`datasette.yaml` `allowed_csp_origins` becomes: `https://s3.documentcloud.org`, `https://cdn.muckrock.com`, `https://upload.wikimedia.org` (Wikimedia's image CDN; commons page URLs are not image URLs).

## Tests

Creator: approved origin → app created with csp_origins set (verify via datasette-apps registry read); unapproved → CreationError naming origin + approved list; http origin → rejected; no image column → no origins, unchanged behavior. Append: new approved origin merged into opt-ins; unapproved → 400; no-image-column assignment unaffected. Builder: structural needle for the indicator element.

## Out of scope

Editing the image column post-create (column choice is structural); instance allow-list self-service; the Image layout block (separate future feature).
