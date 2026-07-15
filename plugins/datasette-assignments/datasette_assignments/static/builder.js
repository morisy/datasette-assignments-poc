/* datasette-assignments builder.js — dependency-free vanilla JS */
(function () {
  "use strict";

  var fields = [];
  var fieldIdCounter = 0;

  // ── Utility ────────────────────────────────────────────────────────────────

  function slugify(s) {
    return s.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
  }

  function generateId(label) {
    var base = slugify(label) || ("field" + (++fieldIdCounter));
    var existing = fields.map(function (f) { return f.id; });
    if (existing.indexOf(base) === -1) return base;
    var n = 2;
    while (existing.indexOf(base + "_" + n) !== -1) n++;
    return base + "_" + n;
  }

  // ── notifyChanged ─────────────────────────────────────────────────────────
  // Called on EVERY definition-affecting change (field edits, mode change,
  // name/slug/instructions input, CSV input, option edits, reorder/remove).
  // Task 3 subscribes its debounced preview render to this function.

  var _previewDebounceTimer = null;
  var _previewRequestCounter = 0;

  function notifyChanged() {
    clearTimeout(_previewDebounceTimer);
    _previewDebounceTimer = setTimeout(fetchPreview, 600);
  }

  function fetchPreview() {
    var previewUrl = window.__previewUrl;
    if (!previewUrl) return;

    var defnObj = buildDefinition();
    // Pristine form: nothing typed and no fields yet — keep the friendly
    // placeholder note instead of surfacing a validation error.
    if (!defnObj.name && !defnObj.fields.length) {
      var pristineNote = document.getElementById("preview-note");
      if (pristineNote) pristineNote.textContent = "Preview loads as you build.";
      return;
    }

    var csrfInput = document.querySelector('#assignment-form input[name="csrftoken"]');
    var csrftoken = csrfInput ? csrfInput.value : "";
    var definition = JSON.stringify(defnObj);

    var counter = ++_previewRequestCounter;
    var body = "csrftoken=" + encodeURIComponent(csrftoken) +
               "&definition=" + encodeURIComponent(definition);

    fetch(previewUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body,
      credentials: "same-origin",
    }).then(function (resp) {
      if (counter !== _previewRequestCounter) return; // out-of-order
      return resp.text().then(function (text) {
        if (counter !== _previewRequestCounter) return; // check again after async
        var frame = document.getElementById("preview-frame");
        var note = document.getElementById("preview-note");
        if (resp.ok) {
          if (frame) {
            frame.srcdoc = text;
            frame.style.display = "";
          }
          if (note) note.textContent = "";
        } else {
          // Keep existing srcdoc; update note with first line of error
          var firstLine = text.split("\n")[0].trim() || ("HTTP " + resp.status);
          if (note) note.textContent = "Preview paused: " + firstLine;
        }
      });
    }).catch(function (err) {
      if (counter !== _previewRequestCounter) return;
      var note = document.getElementById("preview-note");
      if (note) note.textContent = "Preview paused: " + (err.message || "network error");
    });
  }

  // ── Field factory ──────────────────────────────────────────────────────────

  function makeInputField(type) {
    return {
      kind: "input",
      type: type,
      id: "",
      label: "",
      help: "",
      required: false,
      gallery: false,
      missing_companion: false,
      options: [],
    };
  }

  function makeBlock(kind) {
    return { kind: kind, text: "" };
  }

  // ── Render a field card ────────────────────────────────────────────────────

  var COMPANION_TYPES = ["text", "textarea", "url", "email"];
  var OPTION_TYPES = ["select", "checkbox_group"];

  function renderFieldCard(field, index) {
    var editMode = !!window.__editMode;
    var card = document.createElement("div");
    card.className = "field-card";
    card.dataset.index = index;

    var header = document.createElement("div");
    header.className = "field-header";

    // Type badge / static type+id display
    if (editMode && field.kind === "input") {
      // In edit mode, show type and id as static text (not editable)
      var staticInfo = document.createElement("span");
      staticInfo.className = "field-type-badge";
      staticInfo.textContent = field.type + " · id: " + field.id;
      header.appendChild(staticInfo);
    } else {
      var badge = document.createElement("span");
      badge.className = "field-type-badge";
      if (field.kind === "input") {
        badge.textContent = field.type;
      } else {
        badge.textContent = field.kind;
      }
      header.appendChild(badge);
    }

    if (!editMode) {
      // Controls: move up / move down / remove (hidden in edit mode)
      var controls = document.createElement("div");
      controls.className = "field-controls";

      var btnUp = document.createElement("button");
      btnUp.type = "button";
      btnUp.textContent = "↑";
      btnUp.title = "Move up";
      btnUp.addEventListener("click", function () { moveField(index, -1); });

      var btnDown = document.createElement("button");
      btnDown.type = "button";
      btnDown.textContent = "↓";
      btnDown.title = "Move down";
      btnDown.addEventListener("click", function () { moveField(index, 1); });

      var btnRemove = document.createElement("button");
      btnRemove.type = "button";
      btnRemove.textContent = "✕";
      btnRemove.title = "Remove";
      btnRemove.addEventListener("click", function () { removeField(index); });

      controls.appendChild(btnUp);
      controls.appendChild(btnDown);
      controls.appendChild(btnRemove);
      header.appendChild(controls);
    }

    card.appendChild(header);

    if (field.kind === "header" || field.kind === "paragraph") {
      // Just a text field
      var row = document.createElement("div");
      row.className = "field-row";
      var lbl = document.createElement("label");
      lbl.textContent = "Text";
      var inp = document.createElement("textarea");
      inp.value = field.text || "";
      inp.rows = 2;
      inp.style.width = "100%";
      inp.addEventListener("input", function () {
        fields[index].text = inp.value;
        notifyChanged();
      });
      lbl.appendChild(inp);
      row.appendChild(lbl);
      card.appendChild(row);
      return card;
    }

    // Input field rows
    var row1 = document.createElement("div");
    row1.className = "field-row";

    // Label
    var lblLabel = document.createElement("label");
    lblLabel.textContent = "Label";
    var inpLabel = document.createElement("input");
    inpLabel.type = "text";
    inpLabel.value = field.label || "";
    inpLabel.placeholder = "Field label";
    inpLabel.addEventListener("input", function () {
      fields[index].label = inpLabel.value;
      // Auto-set id from label if id is empty or was auto-generated (new mode only)
      if (!editMode && !fields[index]._idManuallySet) {
        fields[index].id = generateIdForIndex(inpLabel.value, index);
        if (inpId) inpId.value = fields[index].id;
      }
      notifyChanged();
    });
    lblLabel.appendChild(inpLabel);
    row1.appendChild(lblLabel);

    var inpId = null;
    if (!editMode) {
      // ID (editable in new mode only)
      var lblId = document.createElement("label");
      lblId.textContent = "ID (column name)";
      inpId = document.createElement("input");
      inpId.type = "text";
      inpId.value = field.id || "";
      inpId.placeholder = "field_id";
      inpId.addEventListener("input", function () {
        fields[index].id = inpId.value;
        fields[index]._idManuallySet = true;
        notifyChanged();
      });
      lblId.appendChild(inpId);
      row1.appendChild(lblId);
    }

    card.appendChild(row1);

    // Help
    var row2 = document.createElement("div");
    row2.className = "field-row";
    var lblHelp = document.createElement("label");
    lblHelp.textContent = "Help text";
    var inpHelp = document.createElement("input");
    inpHelp.type = "text";
    inpHelp.value = field.help || "";
    inpHelp.style.minWidth = "24em";
    inpHelp.addEventListener("input", function () {
      fields[index].help = inpHelp.value;
      notifyChanged();
    });
    lblHelp.appendChild(inpHelp);
    row2.appendChild(lblHelp);
    card.appendChild(row2);

    // Checkboxes: required / gallery / companion
    var row3 = document.createElement("div");
    row3.className = "field-row";

    function makeCheck(labelText, propName, hint) {
      var lbl = document.createElement("label");
      lbl.className = "inline";
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = !!field[propName];
      if (editMode) {
        cb.disabled = true;
      } else {
        cb.addEventListener("change", function () {
          fields[index][propName] = cb.checked;
          notifyChanged();
        });
      }
      lbl.appendChild(cb);
      lbl.appendChild(document.createTextNode(" " + labelText));
      if (hint) {
        var hintSpan = document.createElement("span");
        hintSpan.className = "field-toggle-hint";
        hintSpan.textContent = "— " + hint;
        lbl.appendChild(hintSpan);
      }
      return lbl;
    }

    row3.appendChild(makeCheck("Required", "required"));
    row3.appendChild(makeCheck("Gallery", "gallery", "may be made public"));

    if (COMPANION_TYPES.indexOf(field.type) !== -1) {
      row3.appendChild(makeCheck("Couldn't find", "missing_companion"));
    }

    card.appendChild(row3);

    // Options editor (for select / checkbox_group)
    if (OPTION_TYPES.indexOf(field.type) !== -1) {
      // Track the number of "stored" options (pre-existing in edit mode)
      var storedOptionCount = editMode ? (field.options || []).length : 0;

      var optDiv = document.createElement("div");
      optDiv.className = "options-editor";
      var optTitle = document.createElement("strong");
      optTitle.textContent = "Options";
      optDiv.appendChild(optTitle);

      var optList = document.createElement("div");
      optDiv.appendChild(optList);

      function renderOptions() {
        optList.innerHTML = "";
        (fields[index].options || []).forEach(function (opt, oi) {
          var isExisting = editMode && oi < storedOptionCount;
          var oRow = document.createElement("div");
          oRow.className = "option-row";
          var oInp = document.createElement("input");
          oInp.type = "text";
          oInp.value = opt;
          if (isExisting) {
            // Existing options are read-only in edit mode
            oInp.readOnly = true;
            oInp.style.background = "#f5f5f5";
            oInp.style.color = "#666";
          } else {
            oInp.addEventListener("input", function () {
              fields[index].options[oi] = oInp.value;
              notifyChanged();
            });
          }
          oRow.appendChild(oInp);
          if (!isExisting) {
            var oRemove = document.createElement("button");
            oRemove.type = "button";
            oRemove.textContent = "✕";
            oRemove.addEventListener("click", function () {
              fields[index].options.splice(oi, 1);
              renderOptions();
              notifyChanged();
            });
            oRow.appendChild(oRemove);
          }
          optList.appendChild(oRow);
        });
      }

      renderOptions();

      var addOptBtn = document.createElement("button");
      addOptBtn.type = "button";
      addOptBtn.textContent = "Add option";
      addOptBtn.addEventListener("click", function () {
        if (!fields[index].options) fields[index].options = [];
        fields[index].options.push("");
        renderOptions();
        notifyChanged();
      });
      optDiv.appendChild(addOptBtn);
      card.appendChild(optDiv);
    }

    return card;
  }

  function generateIdForIndex(label, index) {
    var base = slugify(label) || ("field" + (index + 1));
    var existing = fields
      .map(function (f, i) { return i !== index ? f.id : null; })
      .filter(function (id) { return id !== null; });
    if (existing.indexOf(base) === -1) return base;
    var n = 2;
    while (existing.indexOf(base + "_" + n) !== -1) n++;
    return base + "_" + n;
  }

  // ── Render all fields ──────────────────────────────────────────────────────

  function renderFields() {
    var container = document.getElementById("fields-container");
    var emptyState = document.getElementById("fields-empty");
    if (!container) return;
    container.innerHTML = "";
    fields.forEach(function (f, i) {
      container.appendChild(renderFieldCard(f, i));
    });
    // #fields-empty: visible exactly when fields array is empty
    if (emptyState) {
      emptyState.style.display = fields.length === 0 ? "" : "none";
    }
    notifyChanged();
  }

  function moveField(index, direction) {
    var newIndex = index + direction;
    if (newIndex < 0 || newIndex >= fields.length) return;
    var tmp = fields[index];
    fields[index] = fields[newIndex];
    fields[newIndex] = tmp;
    renderFields();
  }

  function removeField(index) {
    fields.splice(index, 1);
    renderFields();
  }

  // ── CSV column pickers ────────────────────────────────────────────────────

  function sanitizeColumnName(h) {
    return h.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
  }

  function populateColumnSelects(columns) {
    var titleSel = document.getElementById("task-title-col");
    var imageSel = document.getElementById("task-image-col");
    if (!titleSel || !imageSel) return;

    // Remember prior selections
    var prevTitle = titleSel.value;
    var prevImage = imageSel.value;

    // Rebuild title select: options are the column names
    titleSel.innerHTML = "";
    columns.forEach(function (col) {
      var opt = document.createElement("option");
      opt.value = col;
      opt.textContent = col;
      titleSel.appendChild(opt);
    });
    // Default to first column, or restore prior if still present
    if (columns.indexOf(prevTitle) !== -1) {
      titleSel.value = prevTitle;
    } else if (columns.length > 0) {
      titleSel.value = columns[0];
    }

    // Rebuild image select: (none) first, then all columns
    imageSel.innerHTML = "";
    var noneOpt = document.createElement("option");
    noneOpt.value = "";
    noneOpt.textContent = "(none)";
    imageSel.appendChild(noneOpt);
    columns.forEach(function (col) {
      var opt = document.createElement("option");
      opt.value = col;
      opt.textContent = col;
      imageSel.appendChild(opt);
    });
    // Restore prior image selection if still present; otherwise keep (none)
    if (prevImage && columns.indexOf(prevImage) !== -1) {
      imageSel.value = prevImage;
    } else {
      imageSel.value = "";
    }

    notifyChanged();
  }

  var csvDebounceTimer = null;

  function initCsvUpload() {
    var fileEl = document.getElementById("tasks-csv-file");
    var csvEl = document.getElementById("tasks-csv");
    var nameEl = document.getElementById("csv-file-name");
    if (!fileEl || !csvEl) return;
    fileEl.addEventListener("change", function () {
      var file = fileEl.files && fileEl.files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function () {
        csvEl.value = String(reader.result || "");
        if (nameEl) nameEl.textContent = file.name + " loaded — edit below if needed.";
        // Fire the same path as pasting: repopulates column pickers + preview.
        csvEl.dispatchEvent(new Event("input", { bubbles: true }));
      };
      reader.onerror = function () {
        if (nameEl) nameEl.textContent = "Couldn't read " + file.name + " — try pasting instead.";
      };
      reader.readAsText(file);
      // Allow re-selecting the same file later.
      fileEl.value = "";
    });
  }

  function initCsvPicker() {
    var csvEl = document.getElementById("tasks-csv");
    var titleSel = document.getElementById("task-title-col");
    var imageSel = document.getElementById("task-image-col");
    if (!csvEl) return;

    csvEl.addEventListener("input", function () {
      clearTimeout(csvDebounceTimer);
      csvDebounceTimer = setTimeout(function () {
        var val = csvEl.value.trim();
        if (!val) {
          // Clear selects to default state
          if (titleSel) {
            titleSel.innerHTML = '<option value="">(first column)</option>';
          }
          if (imageSel) {
            imageSel.innerHTML = '<option value="">(none)</option>';
          }
          notifyChanged();
          return;
        }
        var firstLine = val.split("\n")[0];
        var columns = firstLine.split(",").map(sanitizeColumnName).filter(function (c) { return c.length > 0; });
        populateColumnSelects(columns);
      }, 300);
    });

    // Wire change events on the selects themselves
    if (titleSel) {
      titleSel.addEventListener("change", function () { notifyChanged(); });
    }
    if (imageSel) {
      imageSel.addEventListener("change", function () { notifyChanged(); });
    }
  }

  // ── Serialize ──────────────────────────────────────────────────────────────

  function buildDefinition() {
    var name = (document.getElementById("assignment-name") || {}).value || "";
    var slugInput = document.getElementById("assignment-slug");
    var slug = slugInput ? slugInput.value.trim() : "";
    if (!slug && name) slug = slugify(name);
    var modeChecked = document.querySelector('input[name="mode"]:checked');
    var mode = modeChecked ? modeChecked.value : "form";
    var instructions = (document.getElementById("assignment-instructions") || {}).value || "";
    var rpt = parseInt((document.getElementById("assignment-rpt") || {}).value || "3", 10) || 3;

    var taskColumns = [];
    var taskTitleColumn = null;
    var taskImageColumn = null;

    if (mode === "tasks") {
      var csvEl = document.getElementById("tasks-csv");
      if (csvEl && csvEl.value.trim()) {
        var firstLine = csvEl.value.trim().split("\n")[0];
        taskColumns = firstLine.split(",").map(sanitizeColumnName).filter(function (c) { return c.length > 0; });
      }

      // Read from the column picker selects
      var titleSel = document.getElementById("task-title-col");
      var imageSel = document.getElementById("task-image-col");

      if (titleSel && titleSel.value) {
        taskTitleColumn = titleSel.value;
      } else if (taskColumns.length > 0) {
        taskTitleColumn = taskColumns[0];
      }

      if (imageSel && imageSel.value) {
        taskImageColumn = imageSel.value;
      }
    }

    return {
      slug: slug,
      name: name,
      mode: mode,
      instructions: instructions,
      responses_per_task: rpt,
      task_columns: taskColumns,
      task_title_column: taskTitleColumn,
      task_image_column: taskImageColumn,
      fields: fields.map(function (f) {
        var out = Object.assign({}, f);
        delete out._idManuallySet;
        return out;
      }),
    };
  }

  // ── Palette ────────────────────────────────────────────────────────────────

  function initPalette() {
    var palette = document.querySelector(".palette");
    if (!palette) return;
    palette.addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-type], button[data-kind]");
      if (!btn) return;
      var type = btn.dataset.type;
      var kind = btn.dataset.kind;
      if (type) {
        fields.push(makeInputField(type));
      } else if (kind) {
        fields.push(makeBlock(kind));
      }
      renderFields();
      // notifyChanged is called inside renderFields()
    });
  }

  // ── Mode toggle (radio cards) ──────────────────────────────────────────────

  function initModeToggle() {
    var modeInputs = document.querySelectorAll('input[name="mode"]');
    var tasksSection = document.getElementById("tasks-section");
    var rptLabel = document.getElementById("rpt-label");
    if (!modeInputs.length) return;
    function update() {
      var modeChecked = document.querySelector('input[name="mode"]:checked');
      var isTasks = modeChecked && modeChecked.value === "tasks";
      if (tasksSection) tasksSection.style.display = isTasks ? "" : "none";
      if (rptLabel) rptLabel.style.display = isTasks ? "" : "none";
      notifyChanged();
    }
    modeInputs.forEach(function (inp) {
      inp.addEventListener("change", update);
    });
    update();
  }

  // ── Live slug placeholder ─────────────────────────────────────────────────

  function initSlugPlaceholder() {
    var nameEl = document.getElementById("assignment-name");
    var slugEl = document.getElementById("assignment-slug");
    if (!nameEl || !slugEl) return;

    nameEl.addEventListener("input", function () {
      // Only update placeholder; explicit value always wins
      var generated = slugify(nameEl.value);
      slugEl.placeholder = generated || "my_assignment";
      notifyChanged();
    });

    // Also notify when slug or instructions change
    slugEl.addEventListener("input", function () { notifyChanged(); });

    var instrEl = document.getElementById("assignment-instructions");
    if (instrEl) {
      instrEl.addEventListener("input", function () { notifyChanged(); });
    }

    var rptEl = document.getElementById("assignment-rpt");
    if (rptEl) {
      rptEl.addEventListener("input", function () { notifyChanged(); });
    }
  }

  // ── Preview ──────────────────────────────────────────────────────────────────

  function initPreview() {
    // Fire an immediate (non-debounced) render so the skeleton appears on load.
    fetchPreview();
  }

  // ── Form submit serialization ──────────────────────────────────────────────

  function initFormSubmit() {
    var form = document.getElementById("assignment-form");
    if (!form) return;
    form.addEventListener("submit", function () {
      var jsonInput = document.getElementById("definition-json");
      if (jsonInput) {
        jsonInput.value = JSON.stringify(buildDefinition());
      }
    });
  }

  // ── Restore from initial definition (on error re-render) ──────────────────

  function restoreInitial() {
    var defn = window.__initialDefinition;
    if (!defn) return;
    try {
      if (typeof defn === "string") defn = JSON.parse(defn);
    } catch (e) { return; }
    // Restore meta
    var nameEl = document.getElementById("assignment-name");
    if (nameEl && defn.name) nameEl.value = defn.name;
    var slugEl = document.getElementById("assignment-slug");
    if (slugEl && defn.slug) { slugEl.value = defn.slug; slugEl._restored = true; }
    // Restore mode via radio cards
    if (defn.mode) {
      var modeRadio = document.querySelector('input[name="mode"][value="' + defn.mode + '"]');
      if (modeRadio) {
        modeRadio.checked = true;
        modeRadio.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }
    var instrEl = document.getElementById("assignment-instructions");
    if (instrEl && defn.instructions) instrEl.value = defn.instructions;
    var rptEl = document.getElementById("assignment-rpt");
    if (rptEl && defn.responses_per_task) rptEl.value = defn.responses_per_task;
    // Restore fields
    if (Array.isArray(defn.fields)) {
      fields = defn.fields.map(function (f) { return Object.assign({}, f); });
    }
    renderFields();
    // Trigger mode toggle UI update
    var anyMode = document.querySelector('input[name="mode"]:checked');
    if (anyMode) anyMode.dispatchEvent(new Event("change", { bubbles: true }));
  }

  // ── Init ───────────────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", function () {
    initPalette();
    initModeToggle();
    initSlugPlaceholder();
    initCsvPicker();
    initCsvUpload();
    initPreview();
    initFormSubmit();
    restoreInitial();
    // Initial empty-state render
    renderFields();
  });
})();
