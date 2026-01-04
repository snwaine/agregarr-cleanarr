import os
import json
import signal
from pathlib import Path
from datetime import datetime, timezone

import requests
from flask import (
    Flask, request, redirect, render_template_string,
    flash, get_flashed_messages
)

CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))
CONFIG_PATH = CONFIG_DIR / "config.json"
STATE_PATH = CONFIG_DIR / "state.json"

app = Flask(__name__)
app.secret_key = "agregarr-cleanarr-secret"

def env_default(name: str, default: str = "") -> str:
    return os.environ.get(name, default)

def load_config():
    # Defaults from env
    cfg = {
        "RADARR_URL": env_default("RADARR_URL", "http://radarr:7878").rstrip("/"),
        "RADARR_API_KEY": env_default("RADARR_API_KEY", ""),
        "TAG_LABEL": env_default("TAG_LABEL", "autodelete30"),
        "DAYS_OLD": int(env_default("DAYS_OLD", "30")),
        "DRY_RUN": env_default("DRY_RUN", "true").lower() == "true",
        "DELETE_FILES": env_default("DELETE_FILES", "true").lower() == "true",
        "ADD_IMPORT_EXCLUSION": env_default("ADD_IMPORT_EXCLUSION", "false").lower() == "true",
        "CRON_SCHEDULE": env_default("CRON_SCHEDULE", "15 3 * * *"),
        "RUN_ON_STARTUP": env_default("RUN_ON_STARTUP", "false").lower() == "true",
        "HTTP_TIMEOUT_SECONDS": int(env_default("HTTP_TIMEOUT_SECONDS", "30")),
    }

    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg.update({k: data[k] for k in data.keys() if k in cfg})
        except Exception:
            pass

    return cfg

def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

def load_state():
    try:
        if STATE_PATH.exists():
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def checkbox(name: str) -> bool:
    return request.form.get(name) == "on"

# --------------------------
# Radarr preview helpers
# --------------------------
def radarr_headers(cfg):
    return {"X-Api-Key": cfg.get("RADARR_API_KEY", "")}

def radarr_get(cfg, path: str):
    url = cfg["RADARR_URL"].rstrip("/") + path
    r = requests.get(url, headers=radarr_headers(cfg), timeout=int(cfg.get("HTTP_TIMEOUT_SECONDS", 30)))
    r.raise_for_status()
    return r.json()

def parse_radarr_date(s: str):
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def preview_candidates(cfg):
    tag_label = cfg.get("TAG_LABEL", "autodelete30")
    days_old = int(cfg.get("DAYS_OLD", 30))

    now = datetime.now(timezone.utc)
    cutoff = now - __import__("datetime").timedelta(days=days_old)

    tags = radarr_get(cfg, "/api/v3/tag")
    tag = next((t for t in tags if t.get("label") == tag_label), None)
    if not tag:
        return {"error": f"Tag '{tag_label}' not found in Radarr.", "candidates": [], "cutoff": cutoff.isoformat()}

    tag_id = tag["id"]
    movies = radarr_get(cfg, "/api/v3/movie")

    candidates = []
    for m in movies:
        if tag_id not in (m.get("tags") or []):
            continue
        added_str = m.get("added")
        if not added_str:
            continue
        added = parse_radarr_date(added_str).astimezone(timezone.utc)
        if added < cutoff:
            age_days = int((now - added).total_seconds() // 86400)
            candidates.append({
                "id": m.get("id"),
                "title": m.get("title"),
                "year": m.get("year"),
                "added": added_str,
                "age_days": age_days,
                "path": m.get("path"),
            })

    candidates.sort(key=lambda x: x["age_days"], reverse=True)
    return {"error": None, "candidates": candidates, "tag_id": tag_id, "cutoff": cutoff.isoformat()}

# --------------------------
# Dashboard helpers
# --------------------------
def parse_iso(dt_str: str):
    if not dt_str:
        return None
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def time_ago(dt_str: str) -> str:
    dt = parse_iso(dt_str)
    if not dt:
        return ""
    now = datetime.now(timezone.utc)
    delta = now - dt.astimezone(timezone.utc)
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hrs = mins // 60
    if hrs < 48:
        return f"{hrs}h ago"
    days = hrs // 24
    return f"{days}d ago"

# --------------------------
# Dark Theme Base
# --------------------------
BASE_HEAD = """
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root{
    --bg:#0b0f14;
    --panel:#0f1620;
    --panel2:#0c121b;
    --muted:#9aa7b2;
    --text:#e6edf3;
    --line:#1f2a36;
    --line2:#283241;
    --accent:#7c3aed;    /* purple */
    --accent2:#22c55e;   /* green */
    --warn:#f59e0b;      /* amber */
    --bad:#ef4444;       /* red */
    --shadow: 0 12px 30px rgba(0,0,0,.35);
  }

  * { box-sizing: border-box; }
  body{
    margin:0;
    font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, "Apple Color Emoji","Segoe UI Emoji";
    background: radial-gradient(1200px 700px at 20% 0%, rgba(124,58,237,.18), transparent 60%),
                radial-gradient(900px 600px at 100% 10%, rgba(34,197,94,.12), transparent 55%),
                var(--bg);
    color: var(--text);
  }

  a{ color: var(--text); text-decoration: none; }
  a:hover{ text-decoration: underline; }

  .wrap{ max-width: 1200px; margin: 0 auto; padding: 22px 18px 36px; }

  .topbar{
    display:flex; align-items:center; justify-content: space-between;
    gap:12px;
    padding: 14px 16px;
    border: 1px solid var(--line);
    border-radius: 14px;
    background: linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.02));
    box-shadow: var(--shadow);
    position: sticky;
    top: 14px;
    z-index: 20;
    backdrop-filter: blur(10px);
  }
  .brand{ display:flex; align-items:center; gap:12px; }
  .logo{
    width: 38px; height: 38px; border-radius: 12px;
    background: linear-gradient(135deg, rgba(124,58,237,.9), rgba(34,197,94,.6));
    box-shadow: 0 10px 24px rgba(124,58,237,.18);
  }
  .title h1{ margin:0; font-size: 16px; letter-spacing:.2px; }
  .title .sub{ color: var(--muted); font-size: 12px; margin-top: 2px; }

  .nav{
    display:flex; align-items:center; gap:8px; flex-wrap: wrap; justify-content: flex-end;
  }
  .pill{
    border: 1px solid var(--line2);
    background: rgba(255,255,255,.03);
    padding: 8px 11px;
    border-radius: 999px;
    font-size: 13px;
  }
  .pill.active{
    border-color: rgba(124,58,237,.65);
    box-shadow: 0 0 0 3px rgba(124,58,237,.18);
  }

  .grid{
    display:grid;
    grid-template-columns: repeat(12, 1fr);
    gap: 14px;
    margin-top: 16px;
  }

  .card{
    grid-column: span 12;
    border: 1px solid var(--line);
    border-radius: 16px;
    background: linear-gradient(180deg, rgba(255,255,255,.03), rgba(255,255,255,.015));
    box-shadow: var(--shadow);
    overflow:hidden;
  }
  .card .hd{
    padding: 14px 16px;
    border-bottom: 1px solid var(--line);
    display:flex; align-items:center; justify-content: space-between;
    gap:12px;
    background: rgba(0,0,0,.12);
  }
  .card .hd h2{ margin:0; font-size: 14px; letter-spacing:.2px; }
  .card .bd{ padding: 14px 16px; }

  .kpi{
    display:grid;
    grid-template-columns: repeat(12, 1fr);
    gap: 12px;
  }
  .k{
    grid-column: span 12;
    border: 1px solid var(--line);
    border-radius: 14px;
    background: rgba(0,0,0,.18);
    padding: 12px 12px;
  }
  .k .l{ color: var(--muted); font-size: 12px; }
  .k .v{ margin-top: 6px; font-size: 18px; font-weight: 700; }

  @media(min-width: 900px){
    .k { grid-column: span 4; }
    .half { grid-column: span 6; }
  }

  .muted{ color: var(--muted); }
  code{
    background: rgba(255,255,255,.06);
    border: 1px solid var(--line2);
    padding: 2px 7px;
    border-radius: 10px;
    color: #dbeafe;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono","Courier New", monospace;
    font-size: 12px;
  }

  .btnrow{ display:flex; gap:10px; flex-wrap: wrap; }
  .btn{
    border: 1px solid var(--line2);
    background: rgba(255,255,255,.03);
    color: var(--text);
    padding: 10px 12px;
    border-radius: 12px;
    cursor:pointer;
    font-weight: 600;
    font-size: 13px;
  }
  .btn:hover{ border-color: rgba(124,58,237,.55); }
  .btn.primary{
    border-color: rgba(124,58,237,.55);
    background: linear-gradient(135deg, rgba(124,58,237,.28), rgba(124,58,237,.10));
  }
  .btn.good{
    border-color: rgba(34,197,94,.55);
    background: linear-gradient(135deg, rgba(34,197,94,.22), rgba(34,197,94,.08));
  }
  .btn.warn{
    border-color: rgba(245,158,11,.55);
    background: linear-gradient(135deg, rgba(245,158,11,.22), rgba(245,158,11,.08));
  }
  .btn.bad{
    border-color: rgba(239,68,68,.55);
    background: linear-gradient(135deg, rgba(239,68,68,.20), rgba(239,68,68,.08));
  }

  .alert{
    border-radius: 14px;
    padding: 12px 14px;
    border: 1px solid var(--line2);
    background: rgba(255,255,255,.03);
    margin: 14px 0 0;
  }
  .alert.success{ border-color: rgba(34,197,94,.55); }
  .alert.error{ border-color: rgba(239,68,68,.55); }

  .form{
    display:grid;
    grid-template-columns: 1fr;
    gap: 12px;
  }
  @media(min-width: 900px){
    .form{ grid-template-columns: 1fr 1fr; }
  }
  .field{
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 10px 12px;
    background: rgba(0,0,0,.18);
  }
  .field label{ display:block; font-size: 12px; color: var(--muted); margin-bottom: 8px; }
  .field input[type=text], .field input[type=password], .field input[type=number]{
    width: 100%;
    border: 1px solid var(--line2);
    background: rgba(255,255,255,.04);
    color: var(--text);
    padding: 10px 10px;
    border-radius: 12px;
    outline: none;
  }
  .field input:focus{
    border-color: rgba(124,58,237,.65);
    box-shadow: 0 0 0 3px rgba(124,58,237,.15);
  }

  .checks{
    display:flex;
    flex-direction: column;
    gap: 10px;
    margin-top: 4px;
  }
  .check{
    display:flex; align-items:center; gap:10px;
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 10px 12px;
    background: rgba(0,0,0,.18);
  }
  .check input{ transform: scale(1.2); }

  table{
    width:100%;
    border-collapse: collapse;
    overflow:hidden;
    border-radius: 14px;
    border: 1px solid var(--line);
  }
  th, td{
    padding: 10px 10px;
    border-bottom: 1px solid var(--line);
    font-size: 13px;
    vertical-align: top;
  }
  th{
    text-align:left;
    color:#cbd5e1;
    background: rgba(255,255,255,.04);
    position: sticky;
    top: 0;
  }
  tr:hover td{ background: rgba(255,255,255,.02); }
  .tablewrap{ max-height: 420px; overflow:auto; border-radius: 14px; border: 1px solid var(--line); }

  .statusDot{
    display:inline-flex; align-items:center; gap:8px;
    font-weight: 700;
  }
  .dot{
    width:10px; height:10px; border-radius: 999px;
    background: var(--muted);
    box-shadow: 0 0 0 4px rgba(255,255,255,.05);
  }
  .dot.ok{ background: var(--accent2); box-shadow: 0 0 0 4px rgba(34,197,94,.12); }
  .dot.warn{ background: var(--warn); box-shadow: 0 0 0 4px rgba(245,158,11,.12); }
  .dot.bad{ background: var(--bad); box-shadow: 0 0 0 4px rgba(239,68,68,.12); }
</style>
"""

def shell(page_title: str, active: str, body: str):
    # active: 'dash' | 'settings' | 'preview' | 'status'
    def pill(name, href, key):
        cls = "pill active" if active == key else "pill"
        return f'<a class="{cls}" href="{href}">{name}</a>'

    nav = (
        pill("Dashboard", "/dashboard", "dash")
        + pill("Settings", "/settings", "settings")
        + pill("Preview", "/preview", "preview")
        + pill("Status", "/status", "status")
    )

    return f"""
<!doctype html>
<html>
<head>
  <title>{page_title}</title>
  {BASE_HEAD}
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <div class="brand">
        <div class="logo"></div>
        <div class="title">
          <h1>agregarr-cleanarr</h1>
          <div class="sub">Radarr tag + age cleanup • WebUI • cron apply • dashboard</div>
        </div>
      </div>
      <div class="nav">{nav}</div>
    </div>

    {body}
  </div>
</body>
</html>
"""

# --------------------------
# Pages
# --------------------------
def render_alerts():
    # Inject flash messages
    html = ""
    for category, message in get_flashed_messages(with_categories=True):
        cls = "success" if category == "success" else "error"
        html += f'<div class="alert {cls}">{message}</div>'
    return html

# --------------------------
# Routes
# --------------------------

# Default page: dashboard
@app.get("/")
def home():
    return redirect("/dashboard")

@app.get("/settings")
def settings():
    cfg = load_config()

    alerts = render_alerts()
    body = f"""
      <div class="grid">
        <div class="card">
          <div class="hd">
            <h2>Settings</h2>
            <div class="btnrow">
              <form method="post" action="/run-now"><button class="btn good" type="submit">Run Now</button></form>
              <form method="post" action="/apply-cron"><button class="btn warn" type="submit">Apply Cron</button></form>
            </div>
          </div>
          <div class="bd">
            <div class="muted">Saved to <code>/config/config.json</code>. Cron changes need <b>Apply Cron</b>.</div>
            {alerts}

            <form method="post" action="/save" style="margin-top:14px;">
              <div class="form">
                <div class="field">
                  <label>Radarr URL</label>
                  <input type="text" name="RADARR_URL" value="{cfg["RADARR_URL"]}">
                </div>
                <div class="field">
                  <label>Radarr API Key</label>
                  <input type="password" name="RADARR_API_KEY" value="{cfg["RADARR_API_KEY"]}">
                </div>

                <div class="field">
                  <label>Tag Label</label>
                  <input type="text" name="TAG_LABEL" value="{cfg["TAG_LABEL"]}">
                </div>
                <div class="field">
                  <label>Days Old</label>
                  <input type="number" min="1" name="DAYS_OLD" value="{cfg["DAYS_OLD"]}">
                </div>

                <div class="field">
                  <label>Cron Schedule</label>
                  <input type="text" name="CRON_SCHEDULE" value="{cfg["CRON_SCHEDULE"]}">
                </div>
                <div class="field">
                  <label>HTTP Timeout Seconds</label>
                  <input type="number" min="5" name="HTTP_TIMEOUT_SECONDS" value="{cfg["HTTP_TIMEOUT_SECONDS"]}">
                </div>
              </div>

              <div class="checks" style="margin-top:12px;">
                <label class="check">
                  <input type="checkbox" name="DRY_RUN" {"checked" if cfg["DRY_RUN"] else ""}>
                  <div>
                    <div style="font-weight:700;">Dry Run</div>
                    <div class="muted">Log only; no deletes.</div>
                  </div>
                </label>

                <label class="check">
                  <input type="checkbox" name="DELETE_FILES" {"checked" if cfg["DELETE_FILES"] else ""}>
                  <div>
                    <div style="font-weight:700;">Delete Files</div>
                    <div class="muted">Remove movie files from disk.</div>
                  </div>
                </label>

                <label class="check">
                  <input type="checkbox" name="ADD_IMPORT_EXCLUSION" {"checked" if cfg["ADD_IMPORT_EXCLUSION"] else ""}>
                  <div>
                    <div style="font-weight:700;">Add Import Exclusion</div>
                    <div class="muted">Prevents Radarr re-import.</div>
                  </div>
                </label>

                <label class="check">
                  <input type="checkbox" name="RUN_ON_STARTUP" {"checked" if cfg["RUN_ON_STARTUP"] else ""}>
                  <div>
                    <div style="font-weight:700;">Run on startup</div>
                    <div class="muted">Run once when container starts.</div>
                  </div>
                </label>
              </div>

              <div class="btnrow" style="margin-top:14px;">
                <button class="btn primary" type="submit">Save Settings</button>
                <a class="btn" href="/preview" style="display:inline-flex; align-items:center;">Preview Candidates</a>
              </div>
            </form>
          </div>
        </div>
      </div>
    """

    return render_template_string(shell("agregarr-cleanarr • Settings", "settings", body))

@app.post("/save")
def save():
    cfg = load_config()

    cfg["RADARR_URL"] = (request.form.get("RADARR_URL") or "").rstrip("/")
    cfg["RADARR_API_KEY"] = request.form.get("RADARR_API_KEY") or ""
    cfg["TAG_LABEL"] = request.form.get("TAG_LABEL") or "autodelete30"
    cfg["DAYS_OLD"] = int(request.form.get("DAYS_OLD") or "30")
    cfg["CRON_SCHEDULE"] = request.form.get("CRON_SCHEDULE") or "15 3 * * *"
    cfg["HTTP_TIMEOUT_SECONDS"] = int(request.form.get("HTTP_TIMEOUT_SECONDS") or "30")

    cfg["DRY_RUN"] = checkbox("DRY_RUN")
    cfg["DELETE_FILES"] = checkbox("DELETE_FILES")
    cfg["ADD_IMPORT_EXCLUSION"] = checkbox("ADD_IMPORT_EXCLUSION")
    cfg["RUN_ON_STARTUP"] = checkbox("RUN_ON_STARTUP")

    save_config(cfg)
    flash("Settings saved ✔", "success")
    return redirect("/settings")

@app.post("/run-now")
def run_now():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (CONFIG_DIR / "run_now.flag").write_text("1", encoding="utf-8")
    flash("Run Now triggered ✔ (check Dashboard/logs)", "success")
    return redirect("/dashboard")

@app.post("/apply-cron")
def apply_cron():
    cfg = load_config()
    schedule = (cfg.get("CRON_SCHEDULE") or "15 3 * * *").strip()
    log_path = "/var/log/agregarr-cleanarr.log"

    cron_line = f"{schedule} python /app/app.py >> {log_path} 2>&1\n"

    try:
        with open("/etc/crontabs/root", "w", encoding="utf-8") as f:
            f.write(cron_line)

        # BusyBox crond is PID 1 (entrypoint execs it)
        os.kill(1, signal.SIGHUP)
        flash("Cron schedule applied successfully ✔", "success")
    except Exception as e:
        flash(f"Failed to apply cron: {e}", "error")

    return redirect("/settings")

@app.get("/preview")
def preview():
    cfg = load_config()
    alerts = render_alerts()

    try:
        result = preview_candidates(cfg)
        error = result.get("error")
        candidates = result.get("candidates", [])
        cutoff = result.get("cutoff", "")

        rows = ""
        for c in candidates[:500]:
            rows += f"""
              <tr>
                <td>{c["age_days"]}</td>
                <td>{c.get("title","")}</td>
                <td>{c.get("year","")}</td>
                <td><code>{c.get("added","")}</code></td>
                <td>{c.get("id","")}</td>
                <td class="muted">{(c.get("path","") or "")}</td>
              </tr>
            """

        table = ""
        if error:
            table = f'<div class="alert error">{error}</div>'
        else:
            table = f"""
              <div class="muted">Found <b>{len(candidates)}</b> candidate(s). Preview only (no deletes).</div>
              <div class="muted" style="margin-top:6px;">Cutoff: <code>{cutoff}</code></div>
              <div class="tablewrap" style="margin-top:12px;">
                <table>
                  <thead>
                    <tr>
                      <th>Age (days)</th>
                      <th>Title</th>
                      <th>Year</th>
                      <th>Added</th>
                      <th>ID</th>
                      <th>Path</th>
                    </tr>
                  </thead>
                  <tbody>{rows}</tbody>
                </table>
              </div>
              <div class="muted" style="margin-top:10px;">Showing up to 500.</div>
            """

        body = f"""
          <div class="grid">
            <div class="card">
              <div class="hd">
                <h2>Preview candidates</h2>
                <div class="btnrow">
                  <a class="btn" href="/settings">Adjust settings</a>
                  <form method="post" action="/run-now"><button class="btn good" type="submit">Run Now</button></form>
                </div>
              </div>
              <div class="bd">
                {alerts}
                {table}
              </div>
            </div>
          </div>
        """

        return render_template_string(shell("agregarr-cleanarr • Preview", "preview", body))

    except Exception as e:
        body = f"""
          <div class="grid">
            <div class="card">
              <div class="hd"><h2>Preview candidates</h2></div>
              <div class="bd">
                {alerts}
                <div class="alert error">{str(e)}</div>
              </div>
            </div>
          </div>
        """
        return render_template_string(shell("agregarr-cleanarr • Preview", "preview", body)), 500

@app.get("/dashboard")
def dashboard():
    state = load_state()
    last_run = state.get("last_run")
    history = state.get("run_history") or []
    cfg = load_config()

    alerts = render_alerts()

    if not last_run:
        body = f"""
          <div class="grid">
            <div class="card">
              <div class="hd">
                <h2>Dashboard</h2>
                <div class="btnrow">
                  <a class="btn" href="/settings">Settings</a>
                  <a class="btn" href="/preview">Preview</a>
                  <form method="post" action="/run-now"><button class="btn good" type="submit">Run Now</button></form>
                </div>
              </div>
              <div class="bd">
                {alerts}
                <div class="muted">No runs recorded yet.</div>
                <div class="muted" style="margin-top:8px;">
                  Start with <b>Dry Run</b> enabled, use <a href="/preview">Preview</a>, then disable Dry Run.
                </div>
              </div>
            </div>
          </div>
        """
        return render_template_string(shell("agregarr-cleanarr • Dashboard", "dash", body))

    status = (last_run.get("status") or "").lower()
    if status == "ok":
        dot = "ok"
        status_text = "OK"
    elif status == "ok_with_errors":
        dot = "warn"
        status_text = "OK (with errors)"
    else:
        dot = "bad"
        status_text = "FAILED"

    finished_ago = time_ago(last_run.get("finished_at"))
    error_count = len(last_run.get("errors") or [])
    deleted_count = (
        len([d for d in (last_run.get("deleted") or []) if d.get("deleted_at")])
        if not last_run.get("dry_run") else len(last_run.get("deleted") or [])
    )

    # KPIs
    kpis = f"""
      <div class="kpi">
        <div class="k">
          <div class="l">Status</div>
          <div class="v">
            <span class="statusDot"><span class="dot {dot}"></span>{status_text}</span>
          </div>
        </div>
        <div class="k">
          <div class="l">Candidates</div>
          <div class="v">{last_run.get("candidates_found", 0)}</div>
        </div>
        <div class="k">
          <div class="l">Deleted (or would delete)</div>
          <div class="v">{deleted_count}</div>
        </div>
      </div>
    """

    # Details
    details = f"""
      <div class="kpi" style="margin-top:12px;">
        <div class="k half">
          <div class="l">Finished</div>
          <div class="v" style="font-size:14px;">
            <code>{last_run.get("finished_at","")}</code>
            <div class="muted" style="margin-top:6px;">{finished_ago}</div>
          </div>
        </div>
        <div class="k half">
          <div class="l">Rule</div>
          <div class="v" style="font-size:14px; font-weight:600;">
            Tag <code>{last_run.get("tag_label","")}</code> • older than <code>{last_run.get("days_old",0)}</code> days
            <div class="muted" style="margin-top:6px;">
              Dry-run: <b>{str(last_run.get("dry_run", False)).lower()}</b> • Delete files: <b>{str(last_run.get("delete_files", False)).lower()}</b>
            </div>
          </div>
        </div>
      </div>
    """

    # Errors
    errors_html = ""
    if error_count > 0:
        items = "".join([f"<li>{e}</li>" for e in (last_run.get("errors") or [])[-5:]])
        errors_html = f"""
          <div class="card" style="margin-top:14px;">
            <div class="hd"><h2>Last errors</h2></div>
            <div class="bd">
              <ul style="margin:0; padding-left: 18px;">{items}</ul>
            </div>
          </div>
        """

    # Deleted table
    del_rows = ""
    for d in (last_run.get("deleted") or [])[:50]:
        del_rows += f"""
          <tr>
            <td><code>{d.get("deleted_at") or ""}</code></td>
            <td>{d.get("age_days","")}</td>
            <td>{d.get("title","")}</td>
            <td>{d.get("year","")}</td>
            <td>{d.get("id","")}</td>
            <td class="muted">{d.get("path","") or ""}</td>
            <td>{str(d.get("dry_run", False)).lower()}</td>
          </tr>
        """

    deleted_table = f"""
      <div class="card" style="margin-top:14px;">
        <div class="hd">
          <h2>Last deleted (most recent run)</h2>
          <div class="muted">Showing up to 50</div>
        </div>
        <div class="bd">
          <div class="tablewrap">
            <table>
              <thead>
                <tr>
                  <th>Deleted at</th>
                  <th>Age</th>
                  <th>Title</th>
                  <th>Year</th>
                  <th>ID</th>
                  <th>Path</th>
                  <th>Dry</th>
                </tr>
              </thead>
              <tbody>
                {del_rows if del_rows else '<tr><td colspan="7" class="muted">No entries.</td></tr>'}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    """

    # History table
    ago_map = {}
    for r in history:
        fa = r.get("finished_at")
        if fa and fa not in ago_map:
            ago_map[fa] = time_ago(fa)

    hist_rows = ""
    for r in history[:20]:
        fa = r.get("finished_at") or ""
        dr = bool(r.get("dry_run"))
        delc = (len(r.get("deleted") or [])) if dr else int(r.get("deleted_count") or 0)
        hist_rows += f"""
          <tr>
            <td><code>{fa}</code></td>
            <td class="muted">{ago_map.get(fa,"")}</td>
            <td>{r.get("status","")}</td>
            <td><code>{r.get("tag_label","")}</code></td>
            <td>{r.get("days_old","")}</td>
            <td>{r.get("candidates_found","")}</td>
            <td>{delc}</td>
            <td>{str(dr).lower()}</td>
            <td>{r.get("duration_seconds","")}</td>
          </tr>
        """

    history_table = f"""
      <div class="card" style="margin-top:14px;">
        <div class="hd">
          <h2>Run history (latest 20 shown)</h2>
          <div class="btnrow">
            <form method="post" action="/clear-state" onsubmit="return confirm('Clear dashboard history/state?');">
              <button class="btn bad" type="submit">Clear state</button>
            </form>
          </div>
        </div>
        <div class="bd">
          <div class="tablewrap">
            <table>
              <thead>
                <tr>
                  <th>Finished</th>
                  <th>When</th>
                  <th>Status</th>
                  <th>Tag</th>
                  <th>Days</th>
                  <th>Candidates</th>
                  <th>Deleted</th>
                  <th>Dry</th>
                  <th>Dur (s)</th>
                </tr>
              </thead>
              <tbody>
                {hist_rows if hist_rows else '<tr><td colspan="9" class="muted">No history yet.</td></tr>'}
              </tbody>
            </table>
          </div>
          <div class="muted" style="margin-top:10px;">
            Current config: Tag <code>{cfg.get("TAG_LABEL","")}</code> • Days <code>{cfg.get("DAYS_OLD","")}</code> • Dry-run <b>{str(cfg.get("DRY_RUN", True)).lower()}</b>
          </div>
        </div>
      </div>
    """

    body = f"""
      <div class="grid">
        <div class="card">
          <div class="hd">
            <h2>Dashboard</h2>
            <div class="btnrow">
              <a class="btn" href="/preview">Preview</a>
              <a class="btn" href="/settings">Settings</a>
              <form method="post" action="/run-now"><button class="btn good" type="submit">Run Now</button></form>
            </div>
          </div>
          <div class="bd">
            {alerts}
            {kpis}
            {details}
          </div>
        </div>

        {errors_html}
        {deleted_table}
        {history_table}
      </div>
    """

    return render_template_string(shell("agregarr-cleanarr • Dashboard", "dash", body))

@app.post("/clear-state")
def clear_state():
    try:
        if STATE_PATH.exists():
            STATE_PATH.unlink()
        flash("State cleared ✔", "success")
    except Exception as e:
        flash(f"Failed to clear state: {e}", "error")
    return redirect("/dashboard")

@app.get("/status")
def status():
    cfg = load_config()
    state = load_state()

    body = f"""
      <div class="grid">
        <div class="card">
          <div class="hd"><h2>Status</h2></div>
          <div class="bd">
            {render_alerts()}
            <div class="muted">Config file: <code>{str(CONFIG_PATH)}</code> (exists: <b>{str(CONFIG_PATH.exists()).lower()}</b>)</div>
            <div class="muted" style="margin-top:8px;">State file: <code>{str(STATE_PATH)}</code> (exists: <b>{str(STATE_PATH.exists()).lower()}</b>)</div>

            <div style="margin-top:14px;" class="tablewrap">
              <table>
                <thead><tr><th>Key</th><th>Value</th></tr></thead>
                <tbody>
                  {''.join([f"<tr><td><code>{k}</code></td><td class='muted'>{str(v)}</td></tr>" for k,v in cfg.items()])}
                </tbody>
              </table>
            </div>

            <div style="margin-top:14px;" class="tablewrap">
              <table>
                <thead><tr><th>State</th><th>Value</th></tr></thead>
                <tbody>
                  {''.join([f"<tr><td><code>{k}</code></td><td class='muted'>{str(v)[:500]}</td></tr>" for k,v in state.items()])}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    """
    return render_template_string(shell("agregarr-cleanarr • Status", "status", body))

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=int(os.environ.get("WEBUI_PORT", "7575")))
    args = p.parse_args()
    app.run(host=args.host, port=args.port)
