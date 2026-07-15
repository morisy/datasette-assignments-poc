# Builder "Live Studio" UI Pass — Design

**Date:** 2026-07-15
**Status:** Approved by user (approach chosen from three mockups; design confirmed verbatim)
**Scope:** Presentation and flow of `/-/assignments/new` only. No changes to the definition JSON shape, routes, request/response contracts, server validation, or generated artifacts. All 38 existing tests stay green.
**Fallback:** tag `v0.1.0-working` (pushed) is the known-good version.

## Layout

Two-column grid on wide screens (single column stacked below ~980px): left = builder controls, right = sticky live preview. The preview reuses the existing `POST /-/assignments/preview` endpoint and sandboxed iframe (`sandbox="allow-scripts"`), auto-refreshed with a ~600ms debounce on any definition change. When the current definition is invalid, keep the last good preview and show a slim "Preview paused: <first error>" note above it — never flash errors. Remove the manual Preview button.

## Basics section

- Name input prominent at top; typing updates the auto-slug placeholder live.
- Mode = two selectable radio cards: "Open form — people just submit; responses accumulate" / "Task list — contributors work through items from a CSV". Tasks mode reveals the CSV paste/upload area plus title-column and image-column dropdowns populated live by parsing the pasted CSV header row.
- Instructions textarea.
- `▸ Advanced` `<details>` disclosure holds: slug (auto-generated value as placeholder) and responses-per-task (tasks mode).

## Field cards & palette

- Field cards styled with the contributor-app design language (same CSS variable palette as `apps/census.html`: --ink/--accent/--rule/--paper etc.) so builder and product feel like one family: uppercase type badge, label input as title row, help input, toggles (Required / Gallery with "may be made public" hint / "couldn't find" companion where type-eligible) as compact labeled controls, styled up/down/remove buttons, cleaned-up options editor for select/checkbox_group.
- Palette: one "Add" bar grouped **Questions** (Text, Long text, Number, Date, URL, Email) · **Choices** (Dropdown, Checkboxes, Single checkbox) · **Layout** (Header, Paragraph) with + affordances and hover states.
- Empty state: dashed panel "No questions yet — add your first below."

## Contract invariants (tests enforce)

- Hidden `#definition-json`, form `#assignment-form`, palette buttons keep `data-type`/`data-kind` attributes; serialization and POST flow unchanged.
- Add a structural template test asserting the contract ids/attributes exist.

## Checkpoints

Pushed commit after each stage: (1) template+CSS layout, (2) interaction behavior, (3) live preview, (4) verified + deployed. Each stage screenshot-verified locally (authenticated capture → headless Chrome) before its commit.
