import os
import json
import signal
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

import requests
from flask import (
    Flask, request, redirect, render_template_string,
    flash, get_flashed_messages
)

# --------------------------
# Paths
# --------------------------
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))
CONFIG_PATH = CONFIG_DIR / "config.json"
STATE_PATH = CONFIG_DIR / "state.json"

CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# --------------------------
# App
# --------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "mediareaparr")

# --------------------------
# Helpers
# --------------------------
def load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text("utf-8"))
    except Exception:
        pass
    return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


config: Dict[str, Any] = load_json(CONFIG_PATH, {})
state: Dict[str, Any] = load_json(STATE_PATH, {})


def cfg(key, default=""):
    return str(config.get(key, os.environ.get(key, default)))


def now_utc():
    return datetime.now(timezone.utc)


# --------------------------
# Base HTML + CSS
# --------------------------
BASE_HEAD = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>MediaReaparr</title>
<meta name="viewport" content="width=device-width, initial-scale=1">

<style>
/* -------------------------
   Variables ONLY
--------------------------*/
:root{
  --ui: 1;
  --bg:#0b1220;
  --panel:#0f172a;
  --panel2:#111827;
  --line:#1f2937;
  --text:#e5e7eb;
  --muted:#9ca3af;
  --accent:#22c55e;
  --accent2:#16a34a;
  --danger:#ef4444;

  --radius:16px;
  --radius-sm:10px;
  --shadow:0 10px 30px rgba(0,0,0,.35);

  --switch-w:42px;
  --switch-h:20px;
  --switch-thumb:16px;
  --switch-pad:2px;
  --switch-travel: calc(var(--switch-w) - var(--switch-thumb) - (var(--switch-pad) * 2));
}

/* -------------------------
   Global fixes (NOT in :root)
--------------------------*/
*, *::before, *::after{ box-sizing:border-box; }

html,body{
  height:100%;
  margin:0;
  background:
    radial-gradient(1200px 500px at 50% -200px, rgba(34,197,94,.25), transparent),
    linear-gradient(#060b16, #060b16);
  color:var(--text);
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont;
}

a{ color:var(--accent); text-decoration:none; }
a:hover{ text-decoration:underline; }

.page{
  min-height:100vh;
  display:flex;
  flex-direction:column;
}

header{
  padding:16px 24px;
  display:flex;
  align-items:center;
  gap:14px;
  border-bottom:1px solid var(--line);
}

.logo{
  font-weight:700;
  font-size:20px;
  letter-spacing:.4px;
}

main{
  flex:1;
  padding:20px;
}

footer{
  padding:16px;
  color:var(--muted);
  border-top:1px solid var(--line);
  text-align:center;
}

/* -------------------------
   Buttons
--------------------------*/
button{
  background:var(--panel2);
  border:1px solid var(--line);
  color:var(--text);
  padding:8px 12px;
  border-radius:10px;
  cursor:pointer;
}
button:hover{ border-color:var(--accent); }
button.primary{
  background:linear-gradient(180deg, var(--accent), var(--accent2));
  color:#052e16;
  border:none;
}
button.danger{ color:var(--danger); }

/* -------------------------
   Forms / fields
--------------------------*/
.form{
  display:grid;
  gap:14px;
  grid-template-columns: minmax(0,1fr);
}
@media (min-width:900px){
  .form{
    grid-template-columns: minmax(0,1fr) minmax(0,1fr);
  }
}

.field{
  display:flex;
  flex-direction:column;
  gap:6px;
  min-width:0;
}

label{ font-size:13px; color:var(--muted); }

.field input[type=text],
.field input[type=password],
.field input[type=number],
.field select,
.field textarea{
  width:100%;
  max-width:100%;
  min-width:0;
  display:block;
  padding:10px 12px;
  border-radius:10px;
  background:#020617;
  border:1px solid var(--line);
  color:var(--text);
}

/* -------------------------
   Checkbox / switch
--------------------------*/
.check{
  display:flex;
  align-items:center;
  gap:10px;
}
.check input{
  transform: scale(calc(1.2 * var(--ui)));
}

/* -------------------------
   Job grid (RADARR LAYOUT)
--------------------------*/
.jobsGrid{
  display:grid;
  gap:14px;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  align-items:stretch;
}

.jobCard{
  display:grid;
  grid-template-columns:80px 1fr;
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:var(--radius);
  overflow:hidden;
}

.jobRail{
  background:linear-gradient(180deg,#020617,#020617);
  border-right:1px solid var(--line);
  display:flex;
  flex-direction:column;
  align-items:center;
  padding:10px 0;
  gap:10px;
}

.jobBody{
  padding:14px;
  display:flex;
  flex-direction:column;
  gap:10px;
  min-width:0;
}

.jobHeader{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
}

.jobName{ font-weight:600; }

.meta{
  display:grid;
  grid-template-columns: auto 1fr;
  gap:6px 10px;
  font-size:13px;
}
.metaVal{
  font-weight:600;
  min-width:0;
  word-break:break-word;
}

/* -------------------------
   Switch
--------------------------*/
.switch{
  width:var(--switch-w);
  height:var(--switch-h);
  background:#020617;
  border:1px solid var(--line);
  border-radius:999px;
  position:relative;
}
.switch::after{
  content:"";
  position:absolute;
  top:var(--switch-pad);
  left:var(--switch-pad);
  width:var(--switch-thumb);
  height:var(--switch-thumb);
  background:#334155;
  border-radius:50%;
  transition:transform .15s ease, background .15s ease;
}
.switch.on{
  background:rgba(34,197,94,.15);
  border-color:var(--accent);
}
.switch.on::after{
  transform:translateX(var(--switch-travel));
  background:var(--accent);
}

/* -------------------------
   Flash
--------------------------*/
.flash{
  background:#020617;
  border:1px solid var(--line);
  padding:10px 14px;
  border-radius:12px;
  margin-bottom:14px;
}
</style>
</head>
<body>
<div class="page">
<header>
  <div class="logo">☠ MediaReaparr</div>
</header>
<main>
"""

BASE_FOOT = """
</main>
<footer>
  MediaReaparr • Auto cleanup for Radarr & Sonarr
</footer>
</div>
</body>
</html>
"""

# --------------------------
# Routes
# --------------------------
@app.route("/")
def index():
    jobs = config.get("jobs", [])
    return render_template_string(
        BASE_HEAD + """
{% for m in get_flashed_messages() %}
<div class="flash">{{ m }}</div>
{% endfor %}

<div class="jobsGrid">
{% for j in jobs %}
  <div class="jobCard">
    <div class="jobRail">
      <button>▶</button>
      <button>Edit</button>
      <button class="danger">✖</button>
    </div>
    <div class="jobBody">
      <div class="jobHeader">
        <div class="jobName">{{ j.name }}</div>
        <div class="switch {{ 'on' if j.enabled }}"></div>
      </div>
      <div class="meta">
        <div>App</div><div class="metaVal">{{ j.app }}</div>
        <div>Tag</div><div class="metaVal">{{ j.tag }}</div>
        <div>Older than</div><div class="metaVal">{{ j.days }} days</div>
        <div>Dry run</div><div class="metaVal">{{ 'Yes' if j.dry else 'No' }}</div>
      </div>
    </div>
  </div>
{% endfor %}
</div>
""" + BASE_FOOT,
        jobs=jobs
    )


# --------------------------
# Entrypoint
# --------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
