# Datasette Assignments Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the "City Public Records Census" crowdsourcing demo on Fly.io with full admin Datasette access, plus NOTES.md (caveats) and a two-track TUTORIAL.md with styled HTML examples.

**Architecture:** A single Datasette 1.0a35 instance serves two SQLite databases (`census.db` for the new demo, `assignments.db` for the legacy Document Review example) plus a persistent `internal.db` holding the datasette-apps definitions. Contributors write only through single-statement stored queries; SQL triggers handle side effects. On Fly.io, all three databases live on a 1GB volume; the Docker image carries seed copies that an entrypoint script installs only when the volume is empty.

**Tech Stack:** Datasette 1.0a35 (alpha), datasette-apps 0.1a3, datasette-auth-passwords 1.1.1, Python 3.12, SQLite, Fly.io (Machines + volume), pytest for script tests.

## Global Constraints

- Pin exactly: `datasette==1.0a35`, `datasette-apps==0.1a3`, `datasette-auth-passwords==1.1.1`. Never upgrade casually — these are alphas and plugin APIs churn (datasette-upload-csvs is already broken on 1.0a35).
- All permission blocks use `allow: true` — NEVER `{unauthenticated: true}` (it denies the logged-in admin).
- Stored write queries must be a single SQL statement. Side effects go in triggers.
- Every setup/sync script must be idempotent: running twice never duplicates rows or destroys responses.
- Deploys must never overwrite live data: seed databases copy to `/data` only if the file does not already exist.
- The datasette-apps sandbox forbids iframes/oEmbed. External assets may only be images/scripts/styles from origins listed in `allowed_csp_origins` AND opted into per-app.
- Auth config shape (verified working on 1.0a35): `plugins.datasette-auth-passwords.root_password_hash: {$env: DATASETTE_ROOT_PASSWORD_HASH}`.
- Existing Document Review app id in `internal.db`: `01kvk3vtk8zpzpac2kk94f2qqx`.
- Work happens on `main` in `/Users/morisy/Documents/Code/datasette_assignments` (already a git repo).

---

### Task 1: Repo restructure + pinned environment

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `apps/` directory
- Modify: `.gitignore`
- Move: `app.html` → `apps/document_review.html`, `setup.py` → `scripts/setup_documents.py`

**Interfaces:**
- Produces: `.venv/` with pinned deps used by every later task; `apps/document_review.html` path used by Task 5; `scripts/` directory used by Tasks 2, 3, 5.

- [ ] **Step 1: Create requirements files**

`requirements.txt`:
```
datasette==1.0a35
datasette-apps==0.1a3
datasette-auth-passwords==1.1.1
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest==8.4.1
```

- [ ] **Step 2: Update .gitignore**

Replace `.gitignore` contents with:
```
datasette.log
__pycache__/
.claude/settings.local.json
.venv/
.pytest_cache/
```

- [ ] **Step 3: Create venv and install**

```bash
cd /Users/morisy/Documents/Code/datasette_assignments
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/datasette --version
```
Expected: `datasette, version 1.0a35`

- [ ] **Step 4: Restructure files**

```bash
mkdir -p apps scripts tests deploy
git mv app.html apps/document_review.html
git mv setup.py scripts/setup_documents.py
```
Then edit `scripts/setup_documents.py`: change `DB_PATH = "assignments.db"` and `CSV_PATH = "documents.csv"` to:
```python
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "assignments.db")
CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "documents.csv")
```

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "chore: pin deps, restructure into apps/ scripts/ tests/ deploy/"
```

---

### Task 2: Top-50 cities CSV

> **Amended 2026-07-14 (user decision):** no pre-seeded website URLs — contributors
> find each city's official site themselves. No URL-checker script.

**Files:**
- Replace: `cities.csv`

**Interfaces:**
- Produces: `cities.csv` with header `city,state` (50 rows) consumed by Task 3's `setup_census.py`.

- [ ] **Step 1: Write cities.csv**

Replace `cities.csv` with (top 50 US cities by population):
```csv
city,state
New York,NY
Los Angeles,CA
Chicago,IL
Houston,TX
Phoenix,AZ
Philadelphia,PA
San Antonio,TX
San Diego,CA
Dallas,TX
Jacksonville,FL
Austin,TX
Fort Worth,TX
San Jose,CA
Columbus,OH
Charlotte,NC
Indianapolis,IN
San Francisco,CA
Seattle,WA
Denver,CO
Oklahoma City,OK
Nashville,TN
Washington,DC
El Paso,TX
Las Vegas,NV
Boston,MA
Detroit,MI
Portland,OR
Louisville,KY
Memphis,TN
Baltimore,MD
Milwaukee,WI
Albuquerque,NM
Tucson,AZ
Fresno,CA
Sacramento,CA
Mesa,AZ
Kansas City,MO
Atlanta,GA
Colorado Springs,CO
Omaha,NE
Raleigh,NC
Miami,FL
Long Beach,CA
Virginia Beach,VA
Oakland,CA
Minneapolis,MN
Tulsa,OK
Tampa,FL
Arlington,TX
New Orleans,LA
```

- [ ] **Step 2: Commit**

```bash
git add cities.csv
git commit -m "feat: top-50 cities seed data"
```

---

### Task 3: census.db builder (`setup_census.py`) — TDD

**Files:**
- Create: `scripts/setup_census.py`, `tests/test_setup_census.py`

**Interfaces:**
- Produces: `build(db_path, csv_path, responses_per_task=3)` function and CLI (`python scripts/setup_census.py`) creating `census.db` with tables `tasks(id, city, state, status, created_at)`, `responses(id, task_id, records_page_url, records_page_missing, records_email, records_email_missing, data_portal_url, data_portal_missing, notes, submitted_at)`, `config(key, value)`, and trigger `mark_task_done`. Consumed by Tasks 4, 6, 7.

- [ ] **Step 1: Write the failing tests**

`tests/test_setup_census.py`:
```python
import csv
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from setup_census import build

CITIES = [("Boston", "MA"), ("Chicago", "IL")]

def make_csv(tmp_path):
    p = tmp_path / "cities.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["city", "state"])
        w.writerows(CITIES)
    return p

def test_build_creates_tasks(tmp_path):
    db = tmp_path / "census.db"
    build(db, make_csv(tmp_path))
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 2
    row = conn.execute(
        "SELECT city, state, status FROM tasks ORDER BY id LIMIT 1"
    ).fetchone()
    assert row == ("Boston", "MA", "pending")
    assert conn.execute(
        "SELECT value FROM config WHERE key='responses_per_task'"
    ).fetchone()[0] == "3"

def test_build_is_idempotent(tmp_path):
    db = tmp_path / "census.db"
    csv_path = make_csv(tmp_path)
    build(db, csv_path)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO responses (task_id, records_page_url, records_page_missing,"
        " records_email, records_email_missing, data_portal_url,"
        " data_portal_missing, notes) VALUES (1, 'https://x.gov/foia', 0,"
        " '', 1, '', 1, 'test')")
    conn.commit()
    conn.close()
    build(db, csv_path)  # rerun must not duplicate tasks or delete responses
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0] == 1

def test_trigger_marks_done_at_target(tmp_path):
    db = tmp_path / "census.db"
    build(db, make_csv(tmp_path), responses_per_task=2)
    conn = sqlite3.connect(db)
    ins = ("INSERT INTO responses (task_id, records_page_url, records_page_missing,"
           " records_email, records_email_missing, data_portal_url,"
           " data_portal_missing, notes) VALUES (1, 'https://x.gov', 0, '', 1, '', 1, '')")
    conn.execute(ins)
    conn.commit()
    assert conn.execute("SELECT status FROM tasks WHERE id=1").fetchone()[0] == "pending"
    conn.execute(ins)
    conn.commit()
    assert conn.execute("SELECT status FROM tasks WHERE id=1").fetchone()[0] == "done"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_setup_census.py -v
```
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'setup_census'`

- [ ] **Step 3: Write scripts/setup_census.py**

```python
"""Build census.db for the City Public Records Census assignment.

Each row of cities.csv becomes one task. Contributors submit the city's
public records page URL, public records email, and open data portal URL —
or flag each as not found. A task is 'done' once it has collected
responses_per_task submissions (the mark_task_done trigger handles this,
because Datasette stored write queries are limited to one statement).

Run with: python scripts/setup_census.py   (safe to re-run; never wipes data)
"""
import csv
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "..", "census.db")
CSV_PATH = os.path.join(HERE, "..", "cities.csv")
RESPONSES_PER_TASK = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- 'pending' | 'done'
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    records_page_url TEXT,
    records_page_missing INTEGER NOT NULL DEFAULT 0,
    records_email TEXT,
    records_email_missing INTEGER NOT NULL DEFAULT 0,
    data_portal_url TEXT,
    data_portal_missing INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    submitted_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

DROP TRIGGER IF EXISTS mark_task_done;
CREATE TRIGGER mark_task_done
AFTER INSERT ON responses
BEGIN
    UPDATE tasks SET status = 'done'
    WHERE id = NEW.task_id
      AND (SELECT COUNT(*) FROM responses WHERE task_id = NEW.task_id)
          >= (SELECT CAST(value AS INTEGER) FROM config WHERE key = 'responses_per_task');
END;
"""


def build(db_path, csv_path, responses_per_task=RESPONSES_PER_TASK):
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO config (key, value) VALUES ('responses_per_task', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(responses_per_task),),
        )
        already = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        if already:
            print(f"tasks table already has {already} rows; skipping city load.")
        else:
            with open(csv_path, newline="", encoding="utf-8") as f:
                rows = [(r["city"].strip(), r["state"].strip())
                        for r in csv.DictReader(f)]
            conn.executemany(
                "INSERT INTO tasks (city, state) VALUES (?, ?)", rows)
            print(f"Loaded {len(rows)} city tasks.")
        conn.commit()
    finally:
        conn.close()
    print(f"Database ready: {db_path}")


if __name__ == "__main__":
    build(DB_PATH, CSV_PATH)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_setup_census.py -v
```
Expected: 3 passed

- [ ] **Step 5: Build the real database**

```bash
.venv/bin/python scripts/setup_census.py
sqlite3 census.db "SELECT COUNT(*) FROM tasks; SELECT * FROM config;"
```
Expected: `50` and `responses_per_task|3`

- [ ] **Step 6: Commit**

```bash
git add scripts/setup_census.py tests/test_setup_census.py census.db
git commit -m "feat: census.db builder with done-marking trigger (TDD)"
```

---

### Task 4: The census app (`apps/census.html`)

**Files:**
- Create: `apps/census.html`

**Interfaces:**
- Consumes: `census.db` schema from Task 3; stored query `census/submit_response` defined in Task 6 (parameters: `task_id, records_page_url, records_page_missing, records_email, records_email_missing, data_portal_url, data_portal_missing, notes`).
- Produces: the single-file app HTML that Task 5 syncs into `internal.db`.

- [ ] **Step 1: Write apps/census.html**

Complete file (adapted from the prototype's proven structure — same progress bar, sessionStorage skip, toast, end states; new three-field-group form):

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>City Public Records Census</title>
  <style>
    :root {
      --ink: #1a1a2e; --ink-mid: #4a4a6a; --ink-soft: #8888aa;
      --paper: #f7f7fb; --rule: #dddde8;
      --accent: #3b5bdb; --accent-dk: #2f4ac5;
      --ok: #2f9e44; --warn: #e67700; --radius: 6px;
    }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: system-ui, -apple-system, sans-serif;
      font-size: 15px; line-height: 1.55;
      background: var(--paper); color: var(--ink);
      min-height: 100vh; display: flex; flex-direction: column;
    }
    header {
      border-bottom: 1px solid var(--rule); padding: 14px 20px; background: #fff;
      display: flex; align-items: baseline; gap: 10px;
    }
    .eyebrow {
      font-size: 11px; font-weight: 600; letter-spacing: 0.08em;
      text-transform: uppercase; color: var(--accent);
    }
    header h1 { font-size: 15px; font-weight: 700; }
    .progress-wrap { background: #fff; border-bottom: 1px solid var(--rule); padding: 10px 20px; }
    .progress-label {
      display: flex; justify-content: space-between;
      font-size: 12px; color: var(--ink-soft); margin-bottom: 6px;
    }
    .progress-label strong { color: var(--ink-mid); }
    .progress-track { height: 4px; background: var(--rule); border-radius: 2px; overflow: hidden; }
    .progress-fill { height: 100%; background: var(--accent); border-radius: 2px; transition: width 0.4s ease; }
    main { flex: 1; max-width: 680px; width: 100%; margin: 0 auto; padding: 24px 20px 48px; }
    .card { background: #fff; border: 1px solid var(--rule); border-radius: var(--radius); overflow: hidden; }
    .card-task { padding: 18px 20px; border-bottom: 1px solid var(--rule); }
    .task-label {
      font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
      color: var(--ink-soft); margin-bottom: 8px;
    }
    .city-name { font-size: 24px; font-weight: 700; line-height: 1.2; }
    .city-meta { margin-top: 6px; font-size: 14px; color: var(--ink-soft); }
    .city-meta a { color: var(--accent); text-decoration: none; font-weight: 600; }
    .city-meta a:hover { text-decoration: underline; }
    .instructions {
      margin-top: 12px; padding: 10px 14px; background: var(--paper);
      border-radius: var(--radius); font-size: 13px; color: var(--ink-mid);
    }
    .card-form { padding: 18px 20px; display: grid; gap: 20px; }
    .field-group { display: grid; gap: 6px; }
    label { font-size: 13px; font-weight: 600; color: var(--ink-mid); }
    .hint { font-size: 12px; font-weight: 400; color: var(--ink-soft); }
    input[type="url"], input[type="email"], textarea {
      width: 100%; padding: 9px 12px; border: 1px solid var(--rule); border-radius: var(--radius);
      font: inherit; font-size: 14px; color: var(--ink); background: #fff;
      transition: border-color 0.12s, box-shadow 0.12s;
    }
    input:focus, textarea:focus {
      outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(59,91,219,0.12);
    }
    input:disabled { background: var(--paper); color: var(--ink-soft); }
    textarea { min-height: 60px; resize: vertical; }
    .missing-row { display: flex; align-items: center; gap: 7px; font-size: 13px; color: var(--ink-mid); }
    .missing-row input { accent-color: var(--accent); width: 15px; height: 15px; }
    .field-error { font-size: 12px; color: var(--warn); display: none; }
    .field-group.invalid .field-error { display: block; }
    .field-group.invalid input[type="url"],
    .field-group.invalid input[type="email"] { border-color: var(--warn); }
    .action-bar {
      padding: 14px 20px; border-top: 1px solid var(--rule);
      display: flex; gap: 10px; align-items: center;
    }
    .btn {
      display: inline-flex; align-items: center; gap: 6px; padding: 9px 18px;
      border-radius: var(--radius); font: inherit; font-size: 14px; font-weight: 600;
      cursor: pointer; border: none; transition: background 0.12s;
    }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .btn-primary { background: var(--accent); color: #fff; }
    .btn-primary:hover:not(:disabled) { background: var(--accent-dk); }
    .btn-skip { background: transparent; color: var(--ink-soft); border: 1px solid var(--rule); }
    .btn-skip:hover:not(:disabled) { background: var(--rule); }
    .remaining { margin-left: auto; font-size: 12px; color: var(--ink-soft); }
    .state { text-align: center; padding: 60px 20px; }
    .state-icon { font-size: 36px; margin-bottom: 12px; }
    .state h2 { font-size: 18px; font-weight: 700; margin-bottom: 8px; }
    .state p { color: var(--ink-soft); font-size: 14px; }
    .toast {
      position: fixed; bottom: 24px; left: 50%;
      transform: translateX(-50%) translateY(80px);
      background: var(--ink); color: #fff; padding: 10px 20px; border-radius: 99px;
      font-size: 13px; font-weight: 500; opacity: 0;
      transition: transform 0.25s ease, opacity 0.25s ease; pointer-events: none;
    }
    .toast.show { transform: translateX(-50%) translateY(0); opacity: 1; }
    .toast.ok { background: var(--ok); }
    .toast.warn { background: var(--warn); }
    .spinner {
      display: inline-block; width: 14px; height: 14px;
      border: 2px solid rgba(255,255,255,0.4); border-top-color: #fff;
      border-radius: 50%; animation: spin 0.6s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) {
      .spinner { animation: none; } .progress-fill { transition: none; }
    }
  </style>
</head>
<body>

<header>
  <span class="eyebrow">Assignment</span>
  <h1>City Public Records Census</h1>
</header>

<div class="progress-wrap">
  <div class="progress-label">
    <span>Progress</span>
    <span><strong id="done-count">0</strong> of <strong id="total-count">0</strong> cities fully verified</span>
  </div>
  <div class="progress-track">
    <div class="progress-fill" id="progress-fill" style="width:0%"></div>
  </div>
</div>

<main id="main">
  <div class="state"><div class="state-icon">⏳</div><h2>Loading…</h2></div>
</main>

<div class="toast" id="toast"></div>

<script>
const DB = "census";

let currentTask = null;
let target = 3;
let totalCount = 0;
let doneCount = 0;
let collected = 0;
let toastTimer;

// Cities this browser session already answered or skipped. Survives refresh.
const SEEN_KEY = "census_seen:" + location.pathname;
let seen = loadSeen();
function loadSeen() {
  try { return new Set(JSON.parse(sessionStorage.getItem(SEEN_KEY) || "[]")); }
  catch { return new Set(); }
}
function saveSeen() { try { sessionStorage.setItem(SEEN_KEY, JSON.stringify([...seen])); } catch {} }
function markSeen(id) { seen.add(id); saveSeen(); }

function $(id) { return document.getElementById(id); }

function showToast(msg, type = "") {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast show" + (type ? " " + type : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = "toast"; }, 2800);
}

function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

async function loadProgress() {
  const r = await datasette.query(DB,
    `WITH n AS (SELECT CAST(value AS INTEGER) AS target FROM config WHERE key = 'responses_per_task'),
          counts AS (
            SELECT t.id, (SELECT COUNT(*) FROM responses r WHERE r.task_id = t.id) AS c
            FROM tasks t
          )
     SELECT (SELECT target FROM n) AS target,
            COUNT(*) AS total,
            SUM(CASE WHEN c >= (SELECT target FROM n) THEN 1 ELSE 0 END) AS done,
            COALESCE(SUM(c), 0) AS collected
     FROM counts`);
  const row = r.rows[0];
  target     = row.target || 3;
  totalCount = row.total || 0;
  doneCount  = row.done  || 0;
  collected  = row.collected || 0;

  $("done-count").textContent  = doneCount;
  $("total-count").textContent = totalCount;
  const goal = totalCount * target;
  const pct = goal > 0 ? Math.min(100, Math.round((collected / goal) * 100)) : 0;
  $("progress-fill").style.width = pct + "%";
}

async function loadNextTask() {
  $("main").innerHTML = `<div class="state"><div class="state-icon">⏳</div><h2>Loading next city…</h2></div>`;
  const excludeClause = seen.size ? `AND t.id NOT IN (${[...seen].join(",")})` : "";
  const r = await datasette.query(DB,
    `SELECT t.id, t.city, t.state
     FROM tasks t
     WHERE (SELECT COUNT(*) FROM responses r WHERE r.task_id = t.id)
           < (SELECT CAST(value AS INTEGER) FROM config WHERE key = 'responses_per_task')
       ${excludeClause}
     ORDER BY RANDOM()
     LIMIT 1`);
  if (!r.rows.length) {
    const everythingDone = doneCount >= totalCount && totalCount > 0;
    $("main").innerHTML = `
      <div class="state">
        <div class="state-icon">✅</div>
        <h2>${everythingDone ? "All done!" : "You're all caught up"}</h2>
        <p>${everythingDone
            ? "Every city has collected enough responses. Thank you for contributing."
            : "You've covered every city still open right now. Check back later as others finish, or share the link with more people."}</p>
      </div>`;
    currentTask = null;
    return;
  }
  currentTask = r.rows[0];
  renderTask(currentTask);
}

function fieldGroup(key, label, hint, inputType, placeholder, missingLabel) {
  return `
    <div class="field-group" id="group-${key}">
      <label for="${key}">${label} <span class="hint">${hint}</span></label>
      <input type="${inputType}" id="${key}" placeholder="${placeholder}" autocomplete="off">
      <div class="missing-row">
        <input type="checkbox" id="${key}-missing"
               onchange="toggleMissing('${key}')">
        <label for="${key}-missing" style="font-weight:400">${missingLabel}</label>
      </div>
      <div class="field-error" id="${key}-error"></div>
    </div>`;
}

function renderTask(task) {
  const remaining = totalCount - doneCount;
  $("main").innerHTML = `
    <div class="card">
      <div class="card-task">
        <div class="task-label">Your city</div>
        <div class="city-name">${esc(task.city)}, ${esc(task.state)}</div>
        <div class="instructions">
          Find ${esc(task.city)}'s official city website (search the web for
          "${esc(task.city)} ${esc(task.state)} official city site" — it usually ends in .gov),
          then look for the three items below.
          Tips: search the site for "public records", "FOIA", "open records", or "open data".
          If you genuinely can't find one after a few minutes, check its "couldn't find" box — that's
          useful data too.
        </div>
      </div>
      <div class="card-form">
        ${fieldGroup("records-page", "Public records request page",
          "(where residents ask for records)", "url", "https://…",
          "I couldn't find a public records page")}
        ${fieldGroup("records-email", "Public records email address",
          "(for submitting requests)", "email", "records@…",
          "I couldn't find a public records email")}
        ${fieldGroup("data-portal", "Open data portal",
          "(datasets the city publishes)", "url", "https://…",
          "I couldn't find an open data portal")}
        <div class="field-group">
          <label for="notes">Notes <span class="hint">(optional — anything confusing or worth flagging)</span></label>
          <textarea id="notes"></textarea>
        </div>
      </div>
      <div class="action-bar">
        <button class="btn btn-primary" id="btn-submit" onclick="submitResponse()">Submit</button>
        <button class="btn btn-skip" onclick="skipTask()">Skip this city</button>
        <span class="remaining">${remaining} cities to go</span>
      </div>
    </div>`;
}

function toggleMissing(key) {
  const input = $(key);
  const missing = $(key + "-missing").checked;
  input.disabled = missing;
  if (missing) { input.value = ""; clearError(key); }
}

function setError(key, msg) {
  $("group-" + key).classList.add("invalid");
  $(key + "-error").textContent = msg;
}
function clearError(key) {
  $("group-" + key).classList.remove("invalid");
}

// Each field needs either a value or its "couldn't find" box —
// a flagged absence is data, a blank is not.
function readField(key, kind, label) {
  clearError(key);
  const missing = $(key + "-missing").checked;
  const value = $(key).value.trim();
  if (missing) return { value: "", missing: 1 };
  if (!value) {
    setError(key, `Enter the ${label}, or check "couldn't find" below.`);
    return null;
  }
  if (kind === "url" && !/^https?:\/\/.+\..+/.test(value)) {
    setError(key, "That doesn't look like a full URL — it should start with http:// or https://");
    return null;
  }
  if (kind === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
    setError(key, "That doesn't look like an email address.");
    return null;
  }
  return { value, missing: 0 };
}

async function submitResponse() {
  if (!currentTask) return;
  const page   = readField("records-page", "url", "public records page URL");
  const email  = readField("records-email", "email", "public records email");
  const portal = readField("data-portal", "url", "open data portal URL");
  if (!page || !email || !portal) {
    showToast("Each item needs a value or its \"couldn't find\" box checked", "warn");
    return;
  }
  const btn = $("btn-submit");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Saving…';
  try {
    await datasette.storedQuery(DB, "submit_response", {
      task_id: currentTask.id,
      records_page_url: page.value,
      records_page_missing: page.missing,
      records_email: email.value,
      records_email_missing: email.missing,
      data_portal_url: portal.value,
      data_portal_missing: portal.missing,
      notes: $("notes").value.trim() || null
    });
    markSeen(currentTask.id);
    await loadProgress();
    showToast("Saved — thank you!", "ok");
    await loadNextTask();
  } catch(e) {
    btn.disabled = false;
    btn.innerHTML = "Submit";
    showToast("Save failed: " + (e.message || String(e)), "warn");
  }
}

// Skip is client-side only: this session moves past the city without
// recording anything, so one person skipping never removes it for everyone.
async function skipTask() {
  if (!currentTask) return;
  markSeen(currentTask.id);
  showToast("Skipped");
  await loadNextTask();
}

async function main() {
  await loadProgress();
  await loadNextTask();
}
main().catch(e => {
  $("main").innerHTML = `<div class="state"><div class="state-icon">⚠️</div><h2>Error</h2><p>${esc(e.message || String(e))}</p></div>`;
});
</script>
</body>
</html>
```

- [ ] **Step 2: Sanity-check the HTML parses**

```bash
.venv/bin/python -c "
from html.parser import HTMLParser
class P(HTMLParser): pass
P().feed(open('apps/census.html').read())
print('parsed ok, bytes:', len(open('apps/census.html').read()))
"
```
Expected: `parsed ok` (functional verification happens in Task 6 against a running instance).

- [ ] **Step 3: Commit**

```bash
git add apps/census.html
git commit -m "feat: City Public Records Census app UI"
```

---

### Task 5: App sync script (`sync_apps.py`) — TDD

**Files:**
- Create: `scripts/sync_apps.py`, `tests/test_sync_apps.py`

**Interfaces:**
- Consumes: `apps/census.html` (Task 4), `apps/document_review.html` (Task 1), existing `internal.db`.
- Produces: CLI `python scripts/sync_apps.py [--internal PATH]` that upserts both app definitions into the datasette-apps tables (`apps`, `app_revisions`, `app_sql_databases`). Task 6 runs it against the real `internal.db`.

**Background for the implementer:** datasette-apps (0.1a3) stores each app as a row in `apps` (id TEXT pk, name, description, path `/-/apps/<id>`, source, metadata, actor_id, is_private, stored_queries JSON, current_version, timestamps) with HTML in `app_revisions` (app_id, version, actor_id, name, description, html, is_private, sql_databases JSON, stored_queries JSON, csp_origins JSON, changed_fields JSON, created_at) and one row per accessible database in `app_sql_databases`. Matching is by `name`; the sync appends a new revision only when the HTML actually changed.

- [ ] **Step 1: Write the failing tests**

`tests/test_sync_apps.py`:
```python
import json
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from sync_apps import sync_app

REPO = Path(__file__).parent.parent

def fresh_internal(tmp_path):
    dst = tmp_path / "internal.db"
    shutil.copy(REPO / "internal.db", dst)
    return dst

DEF = {
    "name": "Test App",
    "description": "A test",
    "html": "<html><body>v1</body></html>",
    "sql_databases": ["census"],
    "stored_queries": ["census/submit_response"],
    "is_private": 0,
}

def test_creates_new_app(tmp_path):
    db = fresh_internal(tmp_path)
    app_id = sync_app(db, DEF)
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT name, is_private, current_version, path, stored_queries"
        " FROM apps WHERE id = ?", (app_id,)).fetchone()
    assert row[0] == "Test App"
    assert row[1] == 0
    assert row[2] == 1
    assert row[3] == f"/-/apps/{app_id}"
    assert json.loads(row[4]) == ["census/submit_response"]
    html = conn.execute(
        "SELECT html FROM app_revisions WHERE app_id = ? AND version = 1",
        (app_id,)).fetchone()[0]
    assert html == DEF["html"]
    dbs = [r[0] for r in conn.execute(
        "SELECT database_name FROM app_sql_databases WHERE app_id = ?", (app_id,))]
    assert dbs == ["census"]

def test_sync_is_idempotent(tmp_path):
    db = fresh_internal(tmp_path)
    id1 = sync_app(db, DEF)
    id2 = sync_app(db, DEF)  # unchanged -> no new revision
    assert id1 == id2
    conn = sqlite3.connect(db)
    assert conn.execute(
        "SELECT COUNT(*) FROM app_revisions WHERE app_id = ?", (id1,)).fetchone()[0] == 1

def test_changed_html_appends_revision(tmp_path):
    db = fresh_internal(tmp_path)
    app_id = sync_app(db, DEF)
    changed = dict(DEF, html="<html><body>v2</body></html>")
    sync_app(db, changed)
    conn = sqlite3.connect(db)
    assert conn.execute(
        "SELECT current_version FROM apps WHERE id = ?", (app_id,)).fetchone()[0] == 2
    html = conn.execute(
        "SELECT html FROM app_revisions WHERE app_id = ? AND version = 2",
        (app_id,)).fetchone()[0]
    assert "v2" in html
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_sync_apps.py -v
```
Expected: ERROR `ModuleNotFoundError: No module named 'sync_apps'`

- [ ] **Step 3: Write scripts/sync_apps.py**

```python
"""Upsert this repo's app HTML files into datasette-apps' internal.db tables.

The repo files under apps/ are the source of truth; the datasette-apps web
editor is treated as a preview surface. Run after editing any app HTML:

    python scripts/sync_apps.py [--internal internal.db]

Matches apps by name. Appends a new app_revisions row (and bumps
apps.current_version) only when the HTML actually changed, mirroring how
the plugin's own editor saves revisions. Restart Datasette afterwards.
"""
import argparse
import json
import os
import secrets
import sqlite3
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..")

# Crockford base32, lowercased — matches the ULID-style ids datasette-apps generates.
ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


def make_ulid():
    ts = int(time.time() * 1000)
    chars = []
    for _ in range(10):
        chars.append(ALPHABET[ts & 31])
        ts >>= 5
    head = "".join(reversed(chars))
    tail = "".join(secrets.choice(ALPHABET) for _ in range(16))
    return head + tail


def now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def sync_app(internal_db, definition):
    """Create or update one app. Returns the app id."""
    conn = sqlite3.connect(internal_db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM apps WHERE name = ? AND deleted_at IS NULL",
            (definition["name"],)).fetchone()
        ts = now()
        stored_queries = json.dumps(definition["stored_queries"])
        sql_databases = json.dumps(definition["sql_databases"])

        if row is None:
            app_id = make_ulid()
            conn.execute(
                "INSERT INTO apps (id, external, name, description, path, source,"
                " metadata, actor_id, is_private, stored_queries, current_version,"
                " created_at, updated_at)"
                " VALUES (?, 0, ?, ?, ?, 'datasette-apps', '{}', 'root', ?, ?, 1, ?, ?)",
                (app_id, definition["name"], definition["description"],
                 f"/-/apps/{app_id}", definition["is_private"], stored_queries, ts, ts))
            conn.execute(
                "INSERT INTO app_revisions (app_id, version, actor_id, name,"
                " description, html, is_private, sql_databases, stored_queries,"
                " csp_origins, changed_fields, created_at)"
                " VALUES (?, 1, 'root', ?, ?, ?, ?, ?, ?, '[]', ?, ?)",
                (app_id, definition["name"], definition["description"],
                 definition["html"], definition["is_private"], sql_databases,
                 stored_queries,
                 json.dumps(["name", "description", "html", "is_private",
                             "sql_databases", "stored_queries"]), ts))
            print(f"created app {definition['name']!r} -> {app_id}")
        else:
            app_id = row["id"]
            current_html = conn.execute(
                "SELECT html FROM app_revisions WHERE app_id = ? AND version = ?",
                (app_id, row["current_version"])).fetchone()
            if current_html and current_html["html"] == definition["html"]:
                print(f"unchanged: {definition['name']!r} (version {row['current_version']})")
            else:
                new_version = row["current_version"] + 1
                conn.execute(
                    "INSERT INTO app_revisions (app_id, version, actor_id, name,"
                    " description, html, is_private, sql_databases, stored_queries,"
                    " csp_origins, changed_fields, created_at)"
                    " VALUES (?, ?, 'root', ?, ?, ?, ?, ?, ?, '[]', ?, ?)",
                    (app_id, new_version, definition["name"],
                     definition["description"], definition["html"],
                     definition["is_private"], sql_databases, stored_queries,
                     json.dumps(["html"]), ts))
                conn.execute(
                    "UPDATE apps SET current_version = ?, description = ?,"
                    " is_private = ?, stored_queries = ?, updated_at = ?"
                    " WHERE id = ?",
                    (new_version, definition["description"],
                     definition["is_private"], stored_queries, ts, app_id))
                print(f"updated {definition['name']!r} -> version {new_version}")

        for db_name in definition["sql_databases"]:
            conn.execute(
                "INSERT OR IGNORE INTO app_sql_databases"
                " (app_id, database_name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (app_id, db_name, ts, ts))
        conn.commit()
        return app_id
    finally:
        conn.close()


def read(path):
    with open(os.path.join(REPO, path), encoding="utf-8") as f:
        return f.read()


DEFINITIONS = [
    {
        "name": "City Public Records Census",
        "description": "Help build a public dataset: find each city's public "
                       "records page, records email, and open data portal.",
        "html": None,  # filled from apps/census.html below
        "html_path": "apps/census.html",
        "sql_databases": ["census"],
        "stored_queries": ["census/submit_response"],
        "is_private": 0,
    },
    {
        "name": "Document Review",
        "description": "Read one page of a public document and describe or "
                       "transcribe what's on it.",
        "html": None,
        "html_path": "apps/document_review.html",
        "sql_databases": ["assignments"],
        "stored_queries": ["assignments/submit_response"],
        "is_private": 0,
    },
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--internal", default=os.path.join(REPO, "internal.db"))
    args = parser.parse_args()
    for definition in DEFINITIONS:
        definition = dict(definition, html=read(definition.pop("html_path")))
        sync_app(args.internal, definition)
    print("Done. Restart Datasette to pick up changes.")


if __name__ == "__main__":
    main()
```

Note: `sync_app()` receives definitions that already have `html`; the tests pass `html` directly and never use `html_path`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_sync_apps.py -v
```
Expected: 3 passed

- [ ] **Step 5: Rename the legacy app so sync matches it by name**

The existing app row is named "Assignment Tool Test"; the sync definitions call it "Document Review". Rename once:
```bash
sqlite3 internal.db "UPDATE apps SET name = 'Document Review',
  description = 'Read one page of a public document and describe or transcribe what''s on it.'
  WHERE id = '01kvk3vtk8zpzpac2kk94f2qqx';"
```

- [ ] **Step 6: Run the sync for real**

```bash
.venv/bin/python scripts/sync_apps.py
sqlite3 internal.db "SELECT id, name, is_private, current_version FROM apps WHERE deleted_at IS NULL;"
```
Expected: census app created with a fresh id; Document Review either `unchanged` or bumped one version (the moved file is byte-identical, so expect `unchanged`). Record the census app id — Task 6 uses it.

- [ ] **Step 7: Commit**

```bash
git add scripts/sync_apps.py tests/test_sync_apps.py internal.db
git commit -m "feat: sync repo app HTML into datasette-apps internal.db"
```

---

### Task 6: Wire up datasette.yaml + full local verification

**Files:**
- Modify: `datasette.yaml`

**Interfaces:**
- Consumes: `census.db` (Task 3), synced apps in `internal.db` (Task 5).
- Produces: the exact config production uses; a locally verified instance. The stored query `census/submit_response` parameter names here must match `apps/census.html`'s `storedQuery` call exactly.

- [ ] **Step 1: Replace datasette.yaml**

```yaml
databases:
  census:
    queries:
      submit_response:
        # Single statement only — the mark_task_done trigger (see
        # scripts/setup_census.py) flips tasks to 'done' at the target count.
        sql: |
          INSERT INTO responses (
            task_id,
            records_page_url, records_page_missing,
            records_email, records_email_missing,
            data_portal_url, data_portal_missing,
            notes, submitted_at
          ) VALUES (
            :task_id,
            :records_page_url, :records_page_missing,
            :records_email, :records_email_missing,
            :data_portal_url, :data_portal_missing,
            :notes, datetime('now')
          );
        write: true
        # `true` = everyone. `{unauthenticated: true}` would match ONLY
        # logged-out users and silently lock the admin out.
        allow: true
  assignments:
    queries:
      submit_response:
        sql: |
          INSERT INTO responses (task_id, answer, notes, submitted_at)
          VALUES (:task_id, :answer, :notes, datetime('now'));
        write: true
        allow: true

# Instance-wide read + SQL access for everyone, admin included.
allow: true
allow_sql: true

# datasette-apps only auto-grants view-app to an app's owner; this lets
# logged-out contributors open published (non-private) apps.
permissions:
  view-app: true

plugins:
  # Admin login. Generate the hash with:
  #   python -c "from datasette_auth_passwords.utils import hash_password; print(hash_password('yourpassword'))"
  datasette-auth-passwords:
    root_password_hash:
      $env: DATASETTE_ROOT_PASSWORD_HASH
  # Administrator-approved origins apps may load assets from (images only in
  # practice — the sandbox has no frame-src, so iframes/oEmbed are impossible).
  # Each app must additionally opt in via its own allowed-origins field.
  datasette-apps:
    allowed_csp_origins:
      - https://s3.documentcloud.org
```

- [ ] **Step 2: Run the full stack locally**

```bash
export DATASETTE_ROOT_PASSWORD_HASH=$(.venv/bin/python -c \
  "from datasette_auth_passwords.utils import hash_password; print(hash_password('localdev'))")
.venv/bin/datasette serve census.db assignments.db \
  --internal internal.db -c datasette.yaml \
  --secret localsecret -p 8001 > datasette.log 2>&1 &
sleep 3
```

- [ ] **Step 3: Verify read paths (anonymous)**

```bash
curl -s -o /dev/null -w "home: %{http_code}\n" http://127.0.0.1:8001/
curl -s "http://127.0.0.1:8001/census/-/query.json?sql=SELECT+COUNT(*)+AS+n+FROM+tasks&_shape=array"
CENSUS_APP_ID=$(sqlite3 internal.db "SELECT id FROM apps WHERE name='City Public Records Census'")
curl -s -o /dev/null -w "app page: %{http_code}\n" "http://127.0.0.1:8001/-/apps/$CENSUS_APP_ID"
```
Expected: `home: 200`, `[{"n": 50}]`, `app page: 200`

- [ ] **Step 4: Verify the write path (anonymous)**

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8001/census/submit_response.json \
  -H 'Content-Type: application/json' \
  -d '{"task_id":1,"records_page_url":"https://www.nyc.gov/records","records_page_missing":0,"records_email":"","records_email_missing":1,"data_portal_url":"https://opendata.cityofnewyork.us","data_portal_missing":0,"notes":"local verification"}'
curl -s "http://127.0.0.1:8001/census/-/query.json?sql=SELECT+task_id,records_page_url,records_email_missing+FROM+responses&_shape=array"
```
Expected: HTTP 200 with `"ok": true`; the SELECT returns the inserted row.

- [ ] **Step 5: Verify the trigger fires at target**

```bash
for i in 2 3; do curl -s -o /dev/null -X POST http://127.0.0.1:8001/census/submit_response.json \
  -H 'Content-Type: application/json' \
  -d '{"task_id":1,"records_page_url":"https://example.gov","records_page_missing":0,"records_email":"","records_email_missing":1,"data_portal_url":"","data_portal_missing":1,"notes":null}'; done
curl -s "http://127.0.0.1:8001/census/-/query.json?sql=SELECT+status+FROM+tasks+WHERE+id=1&_shape=array"
```
Expected: `[{"status": "done"}]`

- [ ] **Step 6: Verify admin login**

```bash
CSRF=$(curl -s -c /tmp/cj.txt http://127.0.0.1:8001/-/login | grep -o 'name="csrftoken" value="[^"]*"' | sed 's/.*value="//;s/"//')
curl -s -b /tmp/cj.txt -c /tmp/cj.txt -o /dev/null -X POST http://127.0.0.1:8001/-/login \
  -d "username=root&password=localdev&csrftoken=$CSRF"
curl -s -b /tmp/cj.txt http://127.0.0.1:8001/-/actor.json
```
Expected: `{"actor": {"id": "root"}}`

- [ ] **Step 7: Browser check + reset test data**

Open `http://127.0.0.1:8001/-/apps/<CENSUS_APP_ID>` in a real browser: submit one city with a mix of values and "couldn't find" checks, confirm validation blocks an empty unfilled field, confirm the progress bar advances, confirm Skip moves on without writing. Then reset:
```bash
sqlite3 census.db "DELETE FROM responses; UPDATE tasks SET status='pending';"
kill %1  # stop the background datasette
```

- [ ] **Step 8: Commit**

```bash
git add datasette.yaml census.db
git commit -m "feat: production datasette.yaml with census stored query + auth"
```

---

### Task 7: Deployment files (Dockerfile, entrypoint, fly.toml)

**Files:**
- Create: `Dockerfile`, `deploy/entrypoint.sh`, `fly.toml`, `.dockerignore`

**Interfaces:**
- Consumes: `requirements.txt`, `datasette.yaml`, seed DBs (`census.db`, `assignments.db`, `internal.db`).
- Produces: a deployable Fly.io app. Task 8 deploys it.

- [ ] **Step 1: Write Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY datasette.yaml ./
COPY deploy/entrypoint.sh ./entrypoint.sh
# Seed databases: installed onto the volume ONLY if not already present,
# so deploys never overwrite live contributor data.
COPY census.db assignments.db internal.db ./seed/
RUN chmod +x entrypoint.sh

EXPOSE 8080
CMD ["./entrypoint.sh"]
```

- [ ] **Step 2: Write deploy/entrypoint.sh**

```sh
#!/bin/sh
# Seed the volume on first boot only, then start Datasette.
set -e

mkdir -p /data
for f in census.db assignments.db internal.db; do
  if [ ! -f "/data/$f" ]; then
    echo "seeding /data/$f"
    cp "/app/seed/$f" "/data/$f"
  fi
done

exec datasette serve /data/census.db /data/assignments.db \
  --internal /data/internal.db \
  -c /app/datasette.yaml \
  --secret "$DATASETTE_SECRET" \
  --setting sql_time_limit_ms 3000 \
  -h 0.0.0.0 -p 8080
```

- [ ] **Step 3: Write .dockerignore**

```
.venv
.git
.pytest_cache
__pycache__
datasette.log
docs
tests
scratchpad
```

- [ ] **Step 4: Write fly.toml**

```toml
app = "records-census-demo"
primary_region = "bos"

[mounts]
  source = "data"
  destination = "/data"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"
```

(If the app name is taken at `fly launch` time, pick another — e.g. `muckrock-records-census` — and update `app =` to match.)

- [ ] **Step 5: Local container test (skip cleanly if Docker absent)**

```bash
if docker info >/dev/null 2>&1; then
  docker build -t census-demo .
  docker run --rm -d -p 8080:8080 \
    -e DATASETTE_SECRET=testsecret \
    -e DATASETTE_ROOT_PASSWORD_HASH="$DATASETTE_ROOT_PASSWORD_HASH" \
    --name census-demo census-demo
  sleep 4
  curl -s -o /dev/null -w "docker home: %{http_code}\n" http://127.0.0.1:8080/
  curl -s "http://127.0.0.1:8080/census/-/query.json?sql=SELECT+COUNT(*)+AS+n+FROM+tasks&_shape=array"
  docker rm -f census-demo
else
  echo "Docker not available locally; Fly's remote builder will build the image in Task 8."
fi
```
Expected (if Docker present): `docker home: 200` and `[{"n": 50}]`. Note the container test runs without a volume, so it seeds into the container's own `/data` — that's fine for a smoke test.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile deploy/entrypoint.sh fly.toml .dockerignore
git commit -m "feat: Fly.io deployment (volume-seeded, never overwrites live data)"
```

---

### Task 8: Deploy to Fly.io + production smoke test

**Files:** none new (uses Task 7's).

**USER GATE:** Before this task, Michael must: (1) create a Fly.io account at https://fly.io/app/sign-up, (2) add a payment card, (3) install flyctl (`brew install flyctl`) and run `fly auth login`. Pause and ask him when reaching this task.

- [ ] **Step 1: Create the app and volume**

```bash
fly apps create records-census-demo
fly volumes create data --app records-census-demo --region bos --size 1 --yes
```
(If the name is taken, choose another and update `fly.toml`.)

- [ ] **Step 2: Set secrets**

```bash
fly secrets set --app records-census-demo \
  DATASETTE_SECRET="$(openssl rand -hex 32)"
# Ask Michael for the admin password he wants (or generate one and tell him),
# then — note the single quotes; the hash contains $ characters:
HASH=$(.venv/bin/python -c "from datasette_auth_passwords.utils import hash_password; import getpass; print(hash_password(getpass.getpass('admin password: ')))")
fly secrets set --app records-census-demo DATASETTE_ROOT_PASSWORD_HASH="$HASH"
```

- [ ] **Step 3: Deploy**

```bash
fly deploy --app records-census-demo --ha=false
```
Expected: build succeeds, one machine starts, health passes. `--ha=false` keeps a single machine — required, since SQLite on one volume cannot be shared across machines.

- [ ] **Step 4: Production smoke test**

```bash
BASE=https://records-census-demo.fly.dev
curl -s -o /dev/null -w "home: %{http_code}\n" $BASE/
curl -s "$BASE/census/-/query.json?sql=SELECT+COUNT(*)+AS+n+FROM+tasks&_shape=array"
CENSUS_APP_ID=$(sqlite3 internal.db "SELECT id FROM apps WHERE name='City Public Records Census'")
curl -s -o /dev/null -w "app: %{http_code}\n" "$BASE/-/apps/$CENSUS_APP_ID"
curl -s -w "\nHTTP %{http_code}\n" -X POST $BASE/census/submit_response.json \
  -H 'Content-Type: application/json' \
  -d '{"task_id":2,"records_page_url":"","records_page_missing":1,"records_email":"","records_email_missing":1,"data_portal_url":"","data_portal_missing":1,"notes":"deploy smoke test"}'
```
Expected: `home: 200`, `[{"n": 50}]`, `app: 200`, write returns ok.

- [ ] **Step 5: Persistence-across-restart test**

```bash
fly machine restart --app records-census-demo $(fly machine list --app records-census-demo -q | head -1)
sleep 10
curl -s "$BASE/census/-/query.json?sql=SELECT+COUNT(*)+AS+n+FROM+responses+WHERE+notes='deploy smoke test'&_shape=array"
```
Expected: `[{"n": 1}]` — the response survived the restart. Then clean up the smoke row:
```bash
# via admin: log in at $BASE/-/login as root, or run locally against prod is NOT possible —
# instead delete through a one-off ssh console:
fly ssh console --app records-census-demo -C "sqlite3 /data/census.db \"DELETE FROM responses WHERE notes='deploy smoke test'; UPDATE tasks SET status='pending' WHERE id=2;\""
```
(If `sqlite3` is absent in the image, use `python3 -c` with the sqlite3 module instead.)

- [ ] **Step 6: Manual admin check**

Michael (or implementer in a browser): log in at `https://records-census-demo.fly.dev/-/login` as `root`, confirm the full Datasette UI (tables, SQL, CSV export links) and the apps editor at `/-/apps` work.

- [ ] **Step 7: Commit any name/config adjustments**

```bash
git add fly.toml && git diff --cached --quiet || git commit -m "chore: final fly.toml as deployed"
```

---

### Task 9: NOTES.md

**Files:**
- Create: `NOTES.md`

- [ ] **Step 1: Write NOTES.md**

Full content (append anything new learned during Tasks 1–8, especially Fly deploy surprises):

```markdown
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
(`--internal internal.db`), not in `datasette.yaml`. Under version control here,
the repo's `apps/*.html` files are the source of truth and
`scripts/sync_apps.py` upserts them (idempotently, as new revisions) into
`internal.db`. If you edit an app in the datasette-apps web editor instead,
copy the HTML back into `apps/` or the next sync will overwrite it.

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

## Misc

- DocumentCloud's API rejects Python's default urllib User-Agent — send a
  custom one (see `scripts/setup_documents.py`).
- The `datasette.query()` JS API is read-only; writes go through
  `datasette.storedQuery(db, name, params)`.
- App task-selection uses `ORDER BY RANDOM()` — fine at this scale (50–10k
  tasks); revisit if you load hundreds of thousands.
```

- [ ] **Step 2: Verify claims against the shipped code**

Re-read NOTES.md checking every file path and config key it cites exists in the repo as described (e.g. `scripts/setup_census.py` trigger name, `deploy/entrypoint.sh` seeding condition). Fix discrepancies.

- [ ] **Step 3: Commit**

```bash
git add NOTES.md && git commit -m "docs: NOTES.md — caveats and institutional knowledge"
```

---

### Task 10: TUTORIAL.md (two-track, with styled HTML examples)

**Files:**
- Create: `TUTORIAL.md`

**Content requirements** (write friendly prose in MuckRock's voice around this exact skeleton; every code block below appears verbatim in the tutorial):

- [ ] **Step 1: Write TUTORIAL.md with these sections**

1. **What you'll build** — screenshot placeholder markup `![The finished assignment](docs/images/census-app.png)` (Task 11 captures the real image), one paragraph: "a crowdsourcing page where anyone can help verify facts, with every response landing in a database you can search, facet, and export."
2. **What you'll need** — a computer with Python 3.10+, 20 minutes, optionally a Fly.io account for publishing. `<details><summary>Under the hood</summary>` aside explaining the stack (Datasette = SQLite + web UI; datasette-apps = sandboxed single-file HTML apps).
3. **Step 1: Install** — verbatim:
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install datasette==1.0a35 datasette-apps==0.1a3 datasette-auth-passwords==1.1.1
   ```
   with the "why pinned versions" caveat linking NOTES.md.
4. **Step 2: Describe your task as a CSV** — show `cities.csv` head (5 rows), explain "one row = one task someone can do in a few minutes"; aside: designing good microtasks (small, verifiable, redundant).
5. **Step 3: Build the task database** — `python scripts/setup_census.py`; aside shows the `tasks`/`responses`/`config` schema and the full `mark_task_done` trigger with explanation of the single-statement rule.
6. **Step 4: Run it locally** — the `datasette serve ... --internal internal.db -c datasette.yaml --secret ...` command with the password-hash export; what you should see at http://127.0.0.1:8001.
7. **Step 5: The assignment app** — `python scripts/sync_apps.py`; tour of `apps/census.html` structure: the query that picks a task, the stored-query submit, the progress bar. Aside: full annotated `datasette.query()` / `datasette.storedQuery()` API explanation.
8. **Step 6: Make it yours — styled building blocks.** The "examples of HTML to make it look good" section. Copy-paste recipes, each a complete self-contained snippet using the app's CSS variables:
   - **A multiple-choice question** (radio cards):
     ```html
     <div class="field-group">
       <label>Is this a public records page?</label>
       <div class="choice-row">
         <label class="choice"><input type="radio" name="verdict" value="yes"> Yes</label>
         <label class="choice"><input type="radio" name="verdict" value="no"> No</label>
         <label class="choice"><input type="radio" name="verdict" value="unsure"> Not sure</label>
       </div>
     </div>
     <style>
     .choice-row { display: flex; gap: 8px; }
     .choice {
       flex: 1; display: flex; align-items: center; justify-content: center; gap: 8px;
       padding: 10px; border: 1px solid var(--rule); border-radius: 6px;
       cursor: pointer; font-weight: 600; transition: border-color 0.12s, background 0.12s;
     }
     .choice:has(input:checked) {
       border-color: var(--accent); background: rgba(59,91,219,0.06); color: var(--accent);
     }
     </style>
     ```
   - **An image task card** (the DocumentCloud page-image pattern, with skeleton loader) — reuse the `.page-wrap`/`.page-img`/`.page-skeleton` block from `apps/document_review.html` verbatim, plus the CSP explanation: admin adds the origin to `allowed_csp_origins`, app opts in, images only — no iframes/oEmbed (link NOTES.md).
   - **A star/scale rating**:
     ```html
     <div class="field-group">
       <label>How readable is this page?</label>
       <div class="scale" id="scale">
         <button type="button" data-v="1">1</button>
         <button type="button" data-v="2">2</button>
         <button type="button" data-v="3">3</button>
         <button type="button" data-v="4">4</button>
         <button type="button" data-v="5">5</button>
       </div>
     </div>
     <style>
     .scale { display: flex; gap: 6px; }
     .scale button {
       width: 42px; height: 42px; border: 1px solid var(--rule); border-radius: 6px;
       background: #fff; font: inherit; font-weight: 700; cursor: pointer;
     }
     .scale button.active { background: var(--accent); border-color: var(--accent); color: #fff; }
     </style>
     <script>
     document.querySelectorAll("#scale button").forEach(b =>
       b.onclick = () => {
         document.querySelectorAll("#scale button").forEach(x => x.classList.remove("active"));
         b.classList.add("active");
         window.scaleValue = Number(b.dataset.v);
       });
     </script>
     ```
   - **A "couldn't find it" pattern** (input + checkbox that disables it) — extracted from census.html with explanation of why flagged absence beats blank.
   - **Theme it** — the `:root` CSS variables block with two alternate palettes (a warm newsroom palette, a civic green palette) shown as drop-in replacements.
9. **Step 7: Publish it (Fly.io)** — condensed Task 7/8 flow: install flyctl, `fly auth login`, `fly apps create`, volume, two secrets, `fly deploy --ha=false`; cost expectations; aside on why a volume (SQLite persistence) and why one machine.
10. **Step 8: Watch the results come in** — the admin experience: log in, browse `responses`, facet by city, export CSV; three useful SQL queries verbatim (latest responses; per-city agreement `GROUP BY task_id HAVING COUNT(DISTINCT records_page_url) > 1`; completion leaderboard).
11. **Adapting this to your own project** — checklist: change the CSV columns → change `setup_census.py` schema → change the form fields → change the stored query params (all four must agree; list the exact four places).
12. **Limitations to know about** — condensed pointer list into NOTES.md.

- [ ] **Step 2: Verify every command in the tutorial actually runs**

Run each bash block from a clean shell (venv exists from Task 1). Fix any command that doesn't work as written.

- [ ] **Step 3: Commit**

```bash
git add TUTORIAL.md && git commit -m "docs: two-track tutorial with styled HTML recipes"
```

---

### Task 11: README + screenshot + final review

**Files:**
- Create: `README.md`, `docs/images/census-app.png`

- [ ] **Step 1: Capture the screenshot**

With the local instance running (Task 6 Step 2 command), screenshot the census app page and save to `docs/images/census-app.png` (browser tooling or macOS `screencapture`).

- [ ] **Step 2: Write README.md**

```markdown
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
```
(Update the demo URL if the Fly app name changed in Task 8.)

- [ ] **Step 3: Full-repo final check**

```bash
.venv/bin/pytest
.venv/bin/python scripts/setup_census.py   # idempotent — "already has 50 rows"
git status --short                          # nothing unexpected
```

- [ ] **Step 4: Commit**

```bash
git add README.md docs/images/census-app.png
git commit -m "docs: README, demo screenshot"
```

---

## Self-Review Notes

- **Spec coverage:** NOTES.md → Task 9; tutorial (two-track + styled HTML examples) → Task 10; demo app with three flag-able fields + progress bar → Tasks 3–6; Fly.io with persistence + admin auth → Tasks 7–8; Document Review kept as second app → Tasks 1, 5; top-50 cities seed list (no website URLs per 2026-07-14 amendment) → Task 2; smoke test incl. restart persistence → Task 8. Phase 2 (WYSIWYG plugin) intentionally absent.
- **Type consistency:** stored-query parameter names identical across `apps/census.html` (Task 4), `datasette.yaml` (Task 6), and test INSERTs (Task 3): `task_id, records_page_url, records_page_missing, records_email, records_email_missing, data_portal_url, data_portal_missing, notes`. `sync_app(db_path, definition) -> app_id` matches between Task 5 tests and implementation.
- **Known judgment calls:** `sync_apps.py` writes datasette-apps tables directly (schema verified against the live internal.db for the pinned 0.1a3); acceptable because versions are pinned. City URLs are best-effort and Task 2 Step 3 verifies each one.
```
