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
    var card = document.createElement("div");
    card.className = "field-card";
    card.dataset.index = index;

    var header = document.createElement("div");
    header.className = "field-header";

    // Type badge
    var badge = document.createElement("span");
    badge.className = "field-type-badge";
    if (field.kind === "input") {
      badge.textContent = field.type;
    } else {
      badge.textContent = field.kind;
    }
    header.appendChild(badge);

    // Controls: move up / move down / remove
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
      // Auto-set id from label if id is empty or was auto-generated
      if (!fields[index]._idManuallySet) {
        fields[index].id = generateIdForIndex(inpLabel.value, index);
        inpId.value = fields[index].id;
      }
    });
    lblLabel.appendChild(inpLabel);
    row1.appendChild(lblLabel);

    // ID
    var lblId = document.createElement("label");
    lblId.textContent = "ID (column name)";
    var inpId = document.createElement("input");
    inpId.type = "text";
    inpId.value = field.id || "";
    inpId.placeholder = "field_id";
    inpId.addEventListener("input", function () {
      fields[index].id = inpId.value;
      fields[index]._idManuallySet = true;
    });
    lblId.appendChild(inpId);
    row1.appendChild(lblId);

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
    inpHelp.addEventListener("input", function () { fields[index].help = inpHelp.value; });
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
      cb.addEventListener("change", function () { fields[index][propName] = cb.checked; });
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
          var oRow = document.createElement("div");
          oRow.className = "option-row";
          var oInp = document.createElement("input");
          oInp.type = "text";
          oInp.value = opt;
          oInp.addEventListener("input", function () {
            fields[index].options[oi] = oInp.value;
          });
          var oRemove = document.createElement("button");
          oRemove.type = "button";
          oRemove.textContent = "✕";
          oRemove.addEventListener("click", function () {
            fields[index].options.splice(oi, 1);
            renderOptions();
          });
          oRow.appendChild(oInp);
          oRow.appendChild(oRemove);
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
    if (emptyState) {
      emptyState.style.display = fields.length === 0 ? "" : "none";
    }
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
    if (mode === "tasks") {
      var csvEl = document.getElementById("tasks-csv");
      if (csvEl && csvEl.value.trim()) {
        var firstLine = csvEl.value.trim().split("\n")[0];
        taskColumns = firstLine.split(",").map(function (h) {
          return h.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
        });
      }
    }

    var taskTitleColumn = taskColumns.length > 0 ? taskColumns[0] : null;

    return {
      slug: slug,
      name: name,
      mode: mode,
      instructions: instructions,
      responses_per_task: rpt,
      task_columns: taskColumns,
      task_title_column: taskTitleColumn,
      task_image_column: null,
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
    }
    modeInputs.forEach(function (inp) {
      inp.addEventListener("change", update);
    });
    update();
  }

  // ── Preview (inert in Task 1; Task 3 wires live refresh) ──────────────────

  function initPreview() {
    // Preview button removed; live preview wired in Task 3.
    // The #preview-frame iframe and #preview-note are present in the DOM.
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
    initPreview();
    initFormSubmit();
    restoreInitial();
    // Initial empty-state render
    renderFields();
  });
})();
