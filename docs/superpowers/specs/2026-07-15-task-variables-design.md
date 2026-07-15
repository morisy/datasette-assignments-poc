# Task Variables ({{column}}) + CSV Header Clarity — Design

**Date:** 2026-07-15
**Status:** Approved by user (design presented and approved verbatim)
**Scope:** definition validation + generated-app template + builder affordance. No schema/storage/route changes. Tag `v0.3.1` after deploy.

## Interpolation

- Tasks mode only. Token syntax `{{column}}`, whitespace-tolerant (`{{ city }}`), column = sanitized CSV header name, regex `\{\{\s*([a-z][a-z0-9_]*)\s*\}\}`.
- Interpolated surfaces (exactly four): assignment `instructions`, input-field `label`, input-field `help`, header/paragraph `text`.
- Runtime, in the generated app: tasks mode re-renders the form per task; `interp(text, task)` substitutes tokens with the current task's value, unknown-at-runtime tokens render literally (defense; validation prevents them). Interpolate FIRST, then escape through `esc()` — hostile CSV cell values cannot inject HTML. Preview: works automatically (sample task supplies `Sample <col>` values).
- Validation (`validate_definition`): scan the four surfaces for tokens. Tasks mode: token not in `task_columns` → error listing available columns. Form mode: any token → error "variables need a task list ({{...}} found in <where>)". `merge_editable` output re-validates, so edits adding bad tokens are caught.

## Builder affordance

- After CSV parse (same debounced handler that fills the column pickers): render under the textarea — "Detected columns: <code chips> — first row is treated as headers. Use {{<first col>}} in your questions to insert each task's value." Element `#csv-detected`, cleared when CSV empty/unparseable.
- Tighten the Tasks CSV section hint to mention headers-first-row explicitly.

## Tests

Validator: happy path (tasks mode, known token, whitespace variant); unknown token error lists columns; form-mode token error; edit-path (merge_editable then validate) catches introduced bad token. Renderer/app: rendered app JS contains interp machinery; structural test that a label with `{{city}}` survives into DEFN JSON un-mangled; escaping test — a task value like `<script>` interpolated into a label renders escaped (drive via preview + dump-dom or unit-level string check on the emitted interp+esc composition order).

## Out of scope

Autocomplete of tokens while typing; tokens in choice options; form-mode variables.
