# webui.py
# Stylish dark-first UI + optional light theme, Radarr setup grouping, Test Connection workflow,
# Save disabled unless settings changed AND Radarr tested OK, confirm modal for Run Now when DRY_RUN is off.

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Tuple

import requests
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template_string,
    request,
    send_from_directory,
    url_for,
)

APP_TITLE = "MediaReaparr"
CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.json")

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


# ----------------------------
# Config
# ----------------------------

@dataclass
class Settings:
    # App behaviour
    DRY_RUN: bool = True

    # Radarr
    RADARR_URL: str = ""
    RADARR_API_KEY: str = ""

    # Sonarr (optional; kept for compatibility if your backend uses it)
    SONARR_URL: str = ""
    SONARR_API_KEY: str = ""

    # Tag + retention (example)
    TAG_NAME: str = "autoreap"
    DELETE_AFTER_DAYS: int = 7


def _default_settings() -> Settings:
    return Settings()


def load_settings() -> Settings:
    if not os.path.exists(CONFIG_PATH):
        s = _default_settings()
        save_settings(s)
        return s

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f) or {}
    except Exception:
        # If config is malformed, fall back to defaults rather than crashing the UI
        raw = {}

    base = asdict(_default_settings())
    base.update({k: v for k, v in raw.items() if k in base})
    # type-safe-ish coercions
    base["DRY_RUN"] = bool(base.get("DRY_RUN", True))
    try:
        base["DELETE_AFTER_DAYS"] = int(base.get("DELETE_AFTER_DAYS", 7))
    except Exception:
        base["DELETE_AFTER_DAYS"] = 7

    return Settings(**base)


def save_settings(s: Settings) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(asdict(s), f, indent=2)


# ----------------------------
# Simple background run stub
# (replace run_reaper() with your actual logic)
# ----------------------------

RUN_STATE = {
    "running": False,
    "last_run_at": None,       # epoch seconds
    "last_status": "Never ran",
    "last_details": "",
}


def run_reaper(dry_run: bool) -> Tuple[bool, str]:
    """
    Stub for your actual Radarr/Sonarr delete logic.
    Return (success, details).
    """
    # simulate some work
    time.sleep(1.2)
    if dry_run:
        return True, "DRY_RUN enabled: simulated cleanup completed."
    return True, "Cleanup completed: deleted items that matched criteria."


def _run_worker(dry_run: bool) -> None:
    RUN_STATE["running"] = True
    RUN_STATE["last_status"] = "Running…"
    RUN_STATE["last_details"] = ""
    try:
        ok, details = run_reaper(dry_run=dry_run)
        RUN_STATE["last_run_at"] = int(time.time())
        RUN_STATE["last_status"] = "Success" if ok else "Failed"
        RUN_STATE["last_details"] = details
    except Exception as e:
        RUN_STATE["last_run_at"] = int(time.time())
        RUN_STATE["last_status"] = "Failed"
        RUN_STATE["last_details"] = f"Exception: {e}"
    finally:
        RUN_STATE["running"] = False


# ----------------------------
# Radarr Test
# ----------------------------

def test_radarr_connection(url: str, api_key: str, timeout: float = 6.0) -> Tuple[bool, str]:
    url = (url or "").strip().rstrip("/")
    api_key = (api_key or "").strip()

    if not url:
        return False, "Radarr URL is required."
    if not api_key:
        return False, "Radarr API key is required."

    # Tests /api/v3/system/status with URL + API key (but we do NOT show that helper text in the UI)
    test_url = f"{url}/api/v3/system/status"
    try:
        r = requests.get(test_url, headers={"X-Api-Key": api_key}, timeout=timeout)
        if r.status_code == 200:
            try:
                data = r.json()
                ver = data.get("version", "unknown")
                inst = data.get("instanceName", "") or ""
                extra = f" (v{ver})" if ver else ""
                if inst:
                    extra += f" • {inst}"
                return True, f"Connected{extra}"
            except Exception:
                return True, "Connected"
        if r.status_code in (401, 403):
            return False, "Unauthorized. Check API key."
        return False, f"Radarr returned HTTP {r.status_code}."
    except requests.exceptions.RequestException as e:
        return False, f"Connection failed: {e}"


# ----------------------------
# Static (logo)
# ----------------------------

@app.route("/logo/<path:filename>")
def logo_files(filename: str):
    # expects ./logo/logo.png (or other files) on disk
    return send_from_directory("logo", filename)


# ----------------------------
# Pages
# ----------------------------

BASE_TEMPLATE = r"""
<!doctype html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>{{ title }}</title>

  <!-- Bootstrap (no external theme; we override via CSS variables) -->
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">

  <style>
    /* -------------------------------------------------
       Theme tokens (colour changes)
       - dark-first, minimal, high contrast
       - accent + success tuned for "grim reaper" vibe
       ------------------------------------------------- */
    :root{
      --bg: #0b0f14;
      --bg2:#0f1620;
      --card:#101a26;
      --muted:#9aa8b6;
      --text:#eaf2ff;
      --border: rgba(255,255,255,.08);

      --accent:#7c3aed; /* purple */
      --accent2:#06b6d4; /* cyan */
      --success:#22c55e; /* green */
      --danger:#ef4444;
      --warning:#f59e0b;

      --shadow: 0 12px 40px rgba(0,0,0,.45);
      --radius: 18px;
    }

    html[data-theme="light"]{
      --bg:#f7f8fb;
      --bg2:#ffffff;
      --card:#ffffff;
      --muted:#556070;
      --text:#0b1220;
      --border: rgba(13,18,32,.10);

      --accent:#6d28d9;
      --accent2:#0891b2;
      --success:#16a34a;
      --danger:#dc2626;
      --warning:#d97706;

      --shadow: 0 10px 28px rgba(0,0,0,.08);
    }

    body{
      background: radial-gradient(1200px 900px at 10% 0%, rgba(124,58,237,.20), transparent 55%),
                  radial-gradient(900px 700px at 95% 10%, rgba(6,182,212,.18), transparent 60%),
                  linear-gradient(180deg, var(--bg), var(--bg2));
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji","Segoe UI Emoji";
      min-height: 100vh;
    }

    .app-shell{
      max-width: 1100px;
      margin: 26px auto;
      padding: 0 16px 32px;
    }

    .topbar{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap: 12px;
      padding: 14px 16px;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: rgba(16,26,38,.55);
      backdrop-filter: blur(10px);
      box-shadow: var(--shadow);
    }
    html[data-theme="light"] .topbar{
      background: rgba(255,255,255,.72);
    }

    .brand{
      display:flex;
      align-items:center;
      gap: 12px;
      user-select:none;
    }
    .brand img{
      width: 38px;
      height: 38px;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,.04);
      padding: 6px;
    }
    .brand .title{
      font-weight: 800;
      letter-spacing:.2px;
      line-height: 1.05;
      margin: 0;
    }
    .brand .subtitle{
      margin:0;
      color: var(--muted);
      font-size: .9rem;
    }

    .navpill{
      display:flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items:center;
      justify-content:flex-end;
    }

    .pill{
      border: 1px solid var(--border);
      padding: 9px 12px;
      border-radius: 999px;
      text-decoration:none;
      color: var(--text);
      background: rgba(255,255,255,.03);
      transition: transform .08s ease, background .15s ease;
      font-weight: 600;
      font-size: .95rem;
      display:inline-flex;
      gap: 8px;
      align-items:center;
    }
    .pill:hover{
      transform: translateY(-1px);
      background: rgba(124,58,237,.10);
      color: var(--text);
    }
    .pill.active{
      border-color: rgba(124,58,237,.55);
      background: rgba(124,58,237,.16);
    }

    .content{
      margin-top: 18px;
      display:grid;
      grid-template-columns: 1.2fr .8fr;
      gap: 16px;
    }
    @media (max-width: 980px){
      .content{ grid-template-columns: 1fr; }
    }

    .cardx{
      border: 1px solid var(--border);
      background: rgba(16,26,38,.55);
      backdrop-filter: blur(10px);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      overflow:hidden;
    }
    html[data-theme="light"] .cardx{
      background: rgba(255,255,255,.78);
    }

    .cardx .hd{
      padding: 14px 16px;
      border-bottom: 1px solid var(--border);
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap: 10px;
    }
    .cardx .hd h5{
      margin:0;
      font-weight: 800;
      letter-spacing:.2px;
    }
    .cardx .bd{
      padding: 16px;
    }

    .muted{ color: var(--muted); }

    .badge-dot{
      display:inline-flex;
      gap:8px;
      align-items:center;
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 6px 10px;
      background: rgba(255,255,255,.03);
      font-weight: 700;
      font-size: .9rem;
      white-space: nowrap;
    }
    .dot{
      width:10px;height:10px;border-radius:50%;
      background: var(--muted);
      box-shadow: 0 0 0 3px rgba(154,168,182,.18);
    }
    .dot.ok{ background: var(--success); box-shadow: 0 0 0 3px rgba(34,197,94,.22); }
    .dot.bad{ background: var(--danger); box-shadow: 0 0 0 3px rgba(239,68,68,.20); }
    .dot.run{ background: var(--accent2); box-shadow: 0 0 0 3px rgba(6,182,212,.20); }

    .btnx{
      border-radius: 12px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,.03);
      color: var(--text);
      padding: 10px 12px;
      font-weight: 800;
      transition: transform .08s ease, background .15s ease, border-color .15s ease;
    }
    .btnx:hover{ transform: translateY(-1px); background: rgba(124,58,237,.12); border-color: rgba(124,58,237,.40); }
    .btnx:disabled{ opacity:.55; transform:none; cursor:not-allowed; }

    .btn-accent{
      border-color: rgba(124,58,237,.45);
      background: rgba(124,58,237,.16);
    }
    .btn-dangerx{
      border-color: rgba(239,68,68,.45);
      background: rgba(239,68,68,.14);
    }
    .btn-successx{
      border-color: rgba(34,197,94,.55);
      background: rgba(34,197,94,.14);
    }

    .form-control, .form-select{
      background: rgba(255,255,255,.03);
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 12px;
      padding: 10px 12px;
    }
    html[data-theme="light"] .form-control,
    html[data-theme="light"] .form-select{
      background: rgba(255,255,255,.95);
    }
    .form-control:focus, .form-select:focus{
      border-color: rgba(124,58,237,.55);
      box-shadow: 0 0 0 .25rem rgba(124,58,237,.18);
    }
    .form-label{ font-weight: 800; }
    .smallhelp{ color: var(--muted); font-size: .9rem; margin-top: 6px; }

    .section{
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 14px;
      background: rgba(255,255,255,.02);
    }

    .hrx{ border-top: 1px solid var(--border); opacity: 1; margin: 16px 0; }

    .toastx{
      position: fixed;
      right: 16px;
      bottom: 16px;
      min-width: 260px;
      max-width: 440px;
      border: 1px solid var(--border);
      border-radius: 16px;
      background: rgba(16,26,38,.88);
      box-shadow: var(--shadow);
      padding: 12px 12px;
      display: none;
      z-index: 1056;
    }
    html[data-theme="light"] .toastx{ background: rgba(255,255,255,.94); }
    .toastx.show{ display: block; }
    .toastx .t1{ font-weight: 900; margin:0; }
    .toastx .t2{ margin:6px 0 0; color: var(--muted); }

    .theme-toggle{
      display:inline-flex;
      gap: 10px;
      align-items:center;
      cursor:pointer;
      user-select:none;
    }
    .switch{
      width: 48px;
      height: 28px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,.03);
      position: relative;
    }
    .knob{
      width: 22px;height:22px;border-radius: 50%;
      background: rgba(255,255,255,.12);
      position:absolute; top: 50%; transform: translateY(-50%);
      left: 4px;
      transition: left .18s ease, background .18s ease;
      border: 1px solid var(--border);
    }
    html[data-theme="light"] .knob{ left: 22px; background: rgba(13,18,32,.10); }
  </style>
</head>
<body>
  <div class="app-shell">

    <div class="topbar">
      <div class="brand">
        <img src="{{ url_for('logo_files', filename='logo.png') }}" alt="logo" onerror="this.style.display='none'">
        <div>
          <p class="title h5 mb-0">{{ app_title }}</p>
          <p class="subtitle">Auto-reap tagged media after a set time</p>
        </div>
      </div>

      <div class="navpill">
        <a class="pill {{ 'active' if active_page=='dashboard' else '' }}" href="{{ url_for('dashboard') }}">Dashboard</a>
        <a class="pill {{ 'active' if active_page=='settings' else '' }}" href="{{ url_for('settings_page') }}">Settings</a>

        <div class="theme-toggle pill" id="themeToggle" title="Toggle light/dark">
          <span id="themeLabel">Dark</span>
          <div class="switch"><div class="knob"></div></div>
        </div>
      </div>
    </div>

    {{ body|safe }}

  </div>

  <!-- Modal -->
  <div class="modal fade" id="confirmRunModal" tabindex="-1" aria-hidden="true">
    <div class="modal-dialog modal-dialog-centered">
      <div class="modal-content" style="border-radius:18px; border:1px solid var(--border); background: rgba(16,26,38,.92); color: var(--text);">
        <div class="modal-header" style="border-bottom: 1px solid var(--border);">
          <h5 class="modal-title" style="font-weight:900;">Confirm Run</h5>
          <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"
                  style="filter: invert(1);"></button>
        </div>
        <div class="modal-body">
          <div class="section">
            <div style="font-weight:900;">DRY_RUN is OFF</div>
            <div class="muted" style="margin-top:6px;">This will make real deletions. Are you sure you want to run now?</div>
          </div>
        </div>
        <div class="modal-footer" style="border-top: 1px solid var(--border);">
          <button type="button" class="btnx" data-bs-dismiss="modal">Cancel</button>
          <button type="button" class="btnx btn-dangerx" id="confirmRunBtn">Run Anyway</button>
        </div>
      </div>
    </div>
  </div>

  <div class="toastx" id="toast">
    <p class="t1" id="toastTitle">Done</p>
    <p class="t2" id="toastBody">Saved.</p>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>

  <script>
    // Theme preference
    const themeKey = "mediareaparr.theme";
    function applyTheme(t){
      document.documentElement.setAttribute("data-theme", t);
      document.getElementById("themeLabel").textContent = (t === "light") ? "Light" : "Dark";
    }
    const savedTheme = localStorage.getItem(themeKey) || "dark";
    applyTheme(savedTheme);
    document.getElementById("themeToggle").addEventListener("click", () => {
      const cur = document.documentElement.getAttribute("data-theme") || "dark";
      const next = (cur === "dark") ? "light" : "dark";
      localStorage.setItem(themeKey, next);
      applyTheme(next);
    });

    // Toast
    function toast(title, body){
      const t = document.getElementById("toast");
      document.getElementById("toastTitle").textContent = title;
      document.getElementById("toastBody").textContent = body;
      t.classList.add("show");
      setTimeout(() => t.classList.remove("show"), 2400);
    }

    // Helpers for Settings page (no-op on dashboard)
    window.__toast = toast;
  </script>

  {{ scripts|safe }}
</body>
</html>
"""

DASHBOARD_BODY = r"""
<div class="content">
  <div class="cardx">
    <div class="hd">
      <h5>Overview</h5>
      <div class="badge-dot" id="runBadge">
        <span class="dot {{ 'run' if state.running else ('ok' if state.last_status=='Success' else ('bad' if state.last_status=='Failed' else '')) }}"></span>
        <span id="runBadgeText">
          {% if state.running %}Running…{% else %}{{ state.last_status }}{% endif %}
        </span>
      </div>
    </div>
    <div class="bd">
      <div class="row g-3">
        <div class="col-md-6">
          <div class="section">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:10px;">
              <div>
                <div style="font-weight:900;">DRY_RUN</div>
                <div class="muted" style="margin-top:6px;">
                  {% if settings.DRY_RUN %}
                    Enabled — no deletes will occur.
                  {% else %}
                    Disabled — real deletes will occur.
                  {% endif %}
                </div>
              </div>
              <span class="badge-dot">
                <span class="dot {{ 'ok' if settings.DRY_RUN else 'bad' }}"></span>
                {{ 'ON' if settings.DRY_RUN else 'OFF' }}
              </span>
            </div>
          </div>
        </div>

        <div class="col-md-6">
          <div class="section">
            <div style="font-weight:900;">Last run</div>
            <div class="muted" style="margin-top:6px;">
              {% if state.last_run_at %}
                {{ state.last_run_at_human }}
              {% else %}
                Never
              {% endif %}
            </div>
          </div>
        </div>

        <div class="col-12">
          <div class="section">
            <div style="font-weight:900;">Details</div>
            <div class="muted" style="margin-top:6px; white-space: pre-wrap;">{{ state.last_details or '—' }}</div>
          </div>
        </div>
      </div>

      <hr class="hrx"/>

      <div style="display:flex; gap:10px; flex-wrap:wrap;">
        <button class="btnx btn-accent" id="runNowBtn" {{ 'disabled' if state.running else '' }}>
          Run Now
        </button>
        <a class="btnx" href="{{ url_for('settings_page') }}">Open Settings</a>
      </div>

      <div class="smallhelp" style="margin-top:10px;">
        “Run Now” will start a single pass of cleanup using the current settings.
      </div>
    </div>
  </div>

  <div class="cardx">
    <div class="hd">
      <h5>Quick stats</h5>
    </div>
    <div class="bd">
      <div class="section">
        <div style="font-weight:900;">Tag</div>
        <div class="muted" style="margin-top:6px;">{{ settings.TAG_NAME }}</div>
      </div>

      <div style="height:12px;"></div>

      <div class="section">
        <div style="font-weight:900;">Retention</div>
        <div class="muted" style="margin-top:6px;">{{ settings.DELETE_AFTER_DAYS }} day(s)</div>
      </div>

      <div style="height:12px;"></div>

      <div class="section">
        <div style="font-weight:900;">Radarr URL</div>
        <div class="muted" style="margin-top:6px; word-break: break-word;">
          {{ settings.RADARR_URL or '—' }}
        </div>
      </div>
    </div>
  </div>
</div>
"""

DASHBOARD_SCRIPTS = r"""
<script>
  // Dashboard "Run Now" + confirm modal when DRY_RUN is off
  const runNowBtn = document.getElementById("runNowBtn");
  if (runNowBtn){
    runNowBtn.addEventListener("click", async () => {
      const dryRun = {{ 'true' if settings.DRY_RUN else 'false' }};
      if (!dryRun){
        const modal = new bootstrap.Modal(document.getElementById('confirmRunModal'));
        modal.show();
        const confirmBtn = document.getElementById("confirmRunBtn");
        confirmBtn.onclick = async () => {
          confirmBtn.disabled = true;
          await triggerRun();
          confirmBtn.disabled = false;
          modal.hide();
        };
        return;
      }
      await triggerRun();
    });
  }

  async function triggerRun(){
    try{
      runNowBtn.disabled = true;
      const r = await fetch("{{ url_for('run_now') }}", { method: "POST" });
      const j = await r.json();
      if (j.ok){
        window.__toast("Started", "Run queued.");
      } else {
        window.__toast("Error", j.error || "Failed to start run.");
      }
      setTimeout(() => location.reload(), 650);
    } catch(e){
      window.__toast("Error", String(e));
      runNowBtn.disabled = false;
    }
  }
</script>
"""

SETTINGS_BODY = r"""
<div class="content">
  <div class="cardx">
    <div class="hd">
      <h5>Settings</h5>
      <div class="badge-dot" id="saveStateBadge">
        <span class="dot" id="saveDot"></span>
        <span id="saveStateText">Not saved</span>
      </div>
    </div>
    <div class="bd">
      <form id="settingsForm" method="post" action="{{ url_for('save_settings_route') }}">
        <input type="hidden" name="__csrf" value="noop" />

        <div class="row g-3">

          <div class="col-12">
            <div class="section">
              <div style="display:flex; align-items:flex-start; justify-content:space-between; gap:10px; flex-wrap:wrap;">
                <div>
                  <div style="font-weight:900;">General</div>
                  <div class="muted" style="margin-top:6px;">Core behaviour.</div>
                </div>
              </div>

              <div class="row g-3" style="margin-top:6px;">
                <div class="col-md-4">
                  <label class="form-label">DRY_RUN</label>
                  <select class="form-select" name="DRY_RUN" id="DRY_RUN">
                    <option value="true" {{ 'selected' if settings.DRY_RUN else '' }}>true</option>
                    <option value="false" {{ 'selected' if not settings.DRY_RUN else '' }}>false</option>
                  </select>
                  <div class="smallhelp">If false, deletions are real.</div>
                </div>

                <div class="col-md-4">
                  <label class="form-label">Tag name</label>
                  <input class="form-control" name="TAG_NAME" id="TAG_NAME" value="{{ settings.TAG_NAME }}">
                </div>

                <div class="col-md-4">
                  <label class="form-label">Delete after (days)</label>
                  <input class="form-control" type="number" min="1" name="DELETE_AFTER_DAYS" id="DELETE_AFTER_DAYS" value="{{ settings.DELETE_AFTER_DAYS }}">
                </div>
              </div>
            </div>
          </div>

          <!-- Radarr setup group (URL + API together) -->
          <div class="col-12">
            <div class="section">
              <div style="display:flex; align-items:flex-start; justify-content:space-between; gap:10px; flex-wrap:wrap;">
                <div>
                  <div style="font-weight:900;">Radarr setup</div>
                  <div class="muted" style="margin-top:6px;">Connection details.</div>
                </div>
                <div class="badge-dot" id="radarrBadge">
                  <span class="dot" id="radarrDot"></span>
                  <span id="radarrBadgeText">Not tested</span>
                </div>
              </div>

              <div class="row g-3" style="margin-top:6px;">
                <div class="col-md-6">
                  <label class="form-label">Radarr URL</label>
                  <input class="form-control" name="RADARR_URL" id="RADARR_URL" placeholder="http://radarr:7878" value="{{ settings.RADARR_URL }}">
                </div>
                <div class="col-md-6">
                  <label class="form-label">Radarr API key</label>
                  <input class="form-control" name="RADARR_API_KEY" id="RADARR_API_KEY" placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" value="{{ settings.RADARR_API_KEY }}">
                </div>

                <!-- Test button inside group after all fields -->
                <div class="col-12" style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
                  <button type="button" class="btnx btn-successx" id="testRadarrBtn">Test Connection</button>
                  <div class="muted" id="radarrTestMsg" style="font-weight:700;"></div>
                </div>
              </div>
            </div>
          </div>

          <!-- Sonarr kept optional -->
          <div class="col-12">
            <div class="section">
              <div style="font-weight:900;">Sonarr (optional)</div>
              <div class="muted" style="margin-top:6px;">If your backend uses Sonarr too.</div>

              <div class="row g-3" style="margin-top:6px;">
                <div class="col-md-6">
                  <label class="form-label">Sonarr URL</label>
                  <input class="form-control" name="SONARR_URL" id="SONARR_URL" placeholder="http://sonarr:8989" value="{{ settings.SONARR_URL }}">
                </div>
                <div class="col-md-6">
                  <label class="form-label">Sonarr API key</label>
                  <input class="form-control" name="SONARR_API_KEY" id="SONARR_API_KEY" value="{{ settings.SONARR_API_KEY }}">
                </div>
              </div>
            </div>
          </div>

        </div>

        <hr class="hrx"/>

        <div style="display:flex; gap:10px; flex-wrap:wrap;">
          <button class="btnx btn-accent" type="submit" id="saveBtn" disabled>Save Settings</button>
          <a class="btnx" href="{{ url_for('dashboard') }}">Back to Dashboard</a>
        </div>

        <div class="smallhelp" style="margin-top:10px;">
          Save is disabled until Radarr tests OK, and only becomes enabled when you change something.
        </div>
      </form>
    </div>
  </div>

  <div class="cardx">
    <div class="hd"><h5>Notes</h5></div>
    <div class="bd">
      <div class="section">
        <div style="font-weight:900;">Workflow</div>
        <div class="muted" style="margin-top:6px;">
          1) Update Radarr fields<br/>
          2) Click <b>Test Connection</b> (button will show <b>Connected</b> when success)<br/>
          3) Modify any setting you want<br/>
          4) Save
        </div>
      </div>

      <div style="height:12px;"></div>

      <div class="section">
        <div style="font-weight:900;">Why save is disabled</div>
        <div class="muted" style="margin-top:6px;">
          Prevents saving bad Radarr details and avoids accidental writes when nothing changed.
        </div>
      </div>
    </div>
  </div>
</div>
"""

SETTINGS_SCRIPTS = r"""
<script>
  // --- Settings logic:
  // - Save disabled unless (a) settings changed AND (b) Radarr tested OK in current session
  // - Test button turns to "Connected" when success (no success flash alert)
  // - Keep "Not tested" status when fields are edited after a successful test

  const form = document.getElementById("settingsForm");
  const saveBtn = document.getElementById("saveBtn");
  const saveDot = document.getElementById("saveDot");
  const saveStateText = document.getElementById("saveStateText");

  const testBtn = document.getElementById("testRadarrBtn");
  const radarrDot = document.getElementById("radarrDot");
  const radarrBadgeText = document.getElementById("radarrBadgeText");
  const radarrTestMsg = document.getElementById("radarrTestMsg");

  const radarrUrl = document.getElementById("RADARR_URL");
  const radarrKey = document.getElementById("RADARR_API_KEY");

  // Initial values snapshot (data-initial attributes concept, applied here)
  const initial = {};
  Array.from(form.elements).forEach(el => {
    if (!el.name) return;
    initial[el.name] = (el.type === "checkbox") ? (el.checked ? "true" : "false") : (el.value ?? "");
  });

  let radarrOk = false;
  let dirty = false;

  function setSaveState(){
    // Save enabled only when dirty AND radarrOk
    saveBtn.disabled = !(dirty && radarrOk);

    // Badge
    if (!dirty){
      saveDot.className = "dot";
      saveStateText.textContent = "No changes";
    } else if (!radarrOk){
      saveDot.className = "dot bad";
      saveStateText.textContent = "Radarr not verified";
    } else {
      saveDot.className = "dot ok";
      saveStateText.textContent = "Ready to save";
    }
  }

  function setRadarrState(state, msg){
    // state: "idle" | "ok" | "bad" | "testing"
    if (state === "idle"){
      radarrDot.className = "dot";
      radarrBadgeText.textContent = "Not tested";
      radarrTestMsg.textContent = msg || "";
      testBtn.textContent = "Test Connection";
      testBtn.classList.add("btn-successx");
      testBtn.disabled = false;
      radarrOk = false;
    }
    if (state === "testing"){
      radarrDot.className = "dot run";
      radarrBadgeText.textContent = "Testing…";
      radarrTestMsg.textContent = msg || "";
      testBtn.textContent = "Testing…";
      testBtn.disabled = true;
      radarrOk = false;
    }
    if (state === "ok"){
      radarrDot.className = "dot ok";
      radarrBadgeText.textContent = "Connected";
      radarrTestMsg.textContent = msg || "Connected";
      testBtn.textContent = "Connected";
      testBtn.disabled = true; // lock in until user edits fields again
      radarrOk = true;
    }
    if (state === "bad"){
      radarrDot.className = "dot bad";
      radarrBadgeText.textContent = "Failed";
      radarrTestMsg.textContent = msg || "Connection failed";
      testBtn.textContent = "Test Connection";
      testBtn.disabled = false;
      radarrOk = false;
    }
    setSaveState();
  }

  function computeDirty(){
    dirty = false;
    Array.from(form.elements).forEach(el => {
      if (!el.name) return;
      const cur = (el.type === "checkbox") ? (el.checked ? "true" : "false") : (el.value ?? "");
      if (String(cur) !== String(initial[el.name] ?? "")) dirty = true;
    });
    setSaveState();
  }

  // Any change makes form dirty and (if it affects Radarr fields) invalidates Radarr test
  form.addEventListener("input", (e) => {
    computeDirty();

    const target = e.target;
    if (target && (target.id === "RADARR_URL" || target.id === "RADARR_API_KEY")){
      // invalidate test on edit
      setRadarrState("idle");
      testBtn.disabled = false;
      testBtn.textContent = "Test Connection";
    }
  });

  // Test connection
  testBtn.addEventListener("click", async () => {
    const url = (radarrUrl.value || "").trim();
    const key = (radarrKey.value || "").trim();

    setRadarrState("testing", "Checking Radarr…");
    try{
      const r = await fetch("{{ url_for('api_test_radarr') }}", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, api_key: key })
      });
      const j = await r.json();
      if (j.ok){
        // No flash alert on success; just update UI
        setRadarrState("ok", j.message || "Connected");
        window.__toast("Connected", "Radarr connection OK.");
      } else {
        setRadarrState("bad", j.error || "Connection failed");
        window.__toast("Failed", j.error || "Radarr test failed.");
      }
    } catch(e){
      setRadarrState("bad", String(e));
      window.__toast("Error", String(e));
    }
  });

  // On load, start as "Not tested" and compute dirty
  setRadarrState("idle");
  computeDirty();

  // On submit, let server save; show toast quickly (page redirects anyway)
  form.addEventListener("submit", () => {
    window.__toast("Saving", "Writing configuration…");
  });
</script>
"""


# ----------------------------
# Routes
# ----------------------------

@app.route("/")
def dashboard():
    s = load_settings()

    # add human time
    state = dict(RUN_STATE)
    if state.get("last_run_at"):
        # render as local-ish; keep it simple
        state["last_run_at_human"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(state["last_run_at"]))
    else:
        state["last_run_at_human"] = "Never"

    html = render_template_string(
        BASE_TEMPLATE,
        title=f"{APP_TITLE} • Dashboard",
        app_title=APP_TITLE,
        active_page="dashboard",
        body=render_template_string(DASHBOARD_BODY, settings=s, state=state),
        scripts=render_template_string(DASHBOARD_SCRIPTS, settings=s),
    )
    return html


@app.route("/settings", methods=["GET"])
def settings_page():
    s = load_settings()
    html = render_template_string(
        BASE_TEMPLATE,
        title=f"{APP_TITLE} • Settings",
        app_title=APP_TITLE,
        active_page="settings",
        body=render_template_string(SETTINGS_BODY, settings=s),
        scripts=render_template_string(SETTINGS_SCRIPTS, settings=s),
    )
    return html


@app.route("/settings", methods=["POST"])
def save_settings_route():
    s = load_settings()

    # Parse form
    form = request.form
    s.DRY_RUN = (form.get("DRY_RUN", "true").lower() == "true")
    s.RADARR_URL = (form.get("RADARR_URL", "") or "").strip()
    s.RADARR_API_KEY = (form.get("RADARR_API_KEY", "") or "").strip()
    s.SONARR_URL = (form.get("SONARR_URL", "") or "").strip()
    s.SONARR_API_KEY = (form.get("SONARR_API_KEY", "") or "").strip()
    s.TAG_NAME = (form.get("TAG_NAME", "autoreap") or "autoreap").strip() or "autoreap"
    try:
        s.DELETE_AFTER_DAYS = int(form.get("DELETE_AFTER_DAYS", s.DELETE_AFTER_DAYS))
    except Exception:
        pass

    save_settings(s)
    return redirect(url_for("settings_page"))


@app.route("/api/test_radarr", methods=["POST"])
def api_test_radarr():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    api_key = (data.get("api_key") or "").strip()

    ok, msg = test_radarr_connection(url, api_key)
    if ok:
        return jsonify({"ok": True, "message": msg})
    return jsonify({"ok": False, "error": msg})


@app.route("/run_now", methods=["POST"])
def run_now():
    if RUN_STATE["running"]:
        return jsonify({"ok": False, "error": "Already running."})

    s = load_settings()
    t = threading.Thread(target=_run_worker, args=(s.DRY_RUN,), daemon=True)
    t.start()
    return jsonify({"ok": True})


# ----------------------------
# Entry
# ----------------------------

if __name__ == "__main__":
    # Bind on all interfaces for Docker
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    app.run(host=host, port=port, debug=False)
