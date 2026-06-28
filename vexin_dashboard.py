#!/usr/bin/env python3
"""
vexin_dashboard.py — Live AI Activity Dashboard

A single-file HTTP server that shows:
- All running AI jobs in real-time
- Memory, skills, suggestions counts
- Last log lines from each job
- Live auto-refresh every 2 seconds

Open http://localhost:7777 in your browser.

Usage:
  ./vexin_dashboard.py              # default port 7777
  ./vexin_dashboard.py --port 8000  # custom port
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECTS_DIR = Path("/home/vexin/projects")
SUGGESTIONS_DIR = PROJECTS_DIR / "self_upgrade_suggestions"
LOG_FILES = {
    "audit_all": "/tmp/audit-all-agents.log",
    "research_business": "/tmp/research-business.log",
    "deep_review": "/tmp/deep-review.log",
    "teach_prod": "/tmp/teach-prod.log",
    "research_paraguay": "/tmp/research-paraguay-deep.log",
    "business_plan": "/tmp/business-plan.log",
    "apply_best": "/tmp/apply-best.log",
    "generate_patches": "/tmp/generate-patches.log",
}


def get_jobs():
    """Get all running AI jobs."""
    r = subprocess.run(
        ["bash", "-c",
         "ps -ef | grep -E 'audit_all|research_business|deep_review|teach_prod|research_paraguay|business_plan|apply_best|generate_patches|ai_school.py' | grep -v grep"],
        capture_output=True, text=True, timeout=5,
    )
    jobs = []
    for line in r.stdout.strip().split("\n"):
        if not line:
            continue
        # pid, etime, cmd
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        pid = parts[1]
        etime = parts[4]
        cmd = parts[7]

        # Identify job name
        job_name = None
        for name in LOG_FILES.keys():
            if name in cmd:
                job_name = name
                break
        if not job_name and "ai_school.py" in cmd:
            job_name = "ai_school"
        if not job_name:
            continue

        jobs.append({
            "name": job_name,
            "pid": pid,
            "etime": etime,
            "log_file": LOG_FILES.get(job_name, ""),
        })
    return jobs


def get_log_tail(log_file, lines=15):
    """Get the last N lines of a log file."""
    if not log_file or not os.path.exists(log_file):
        return []
    try:
        with open(log_file, 'r', errors='ignore') as f:
            return f.read().splitlines()[-lines:]
    except Exception:
        return []


def get_suggestions():
    """Get suggestion files."""
    if not SUGGESTIONS_DIR.exists():
        return {"total": 0, "by_category": {}, "latest": []}
    files = list(SUGGESTIONS_DIR.glob("*.json"))
    by_category = {}
    latest = []
    for f in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)[:10]:
        try:
            data = json.loads(f.read_text())
            cat = data.get("category", "?")
            by_category[cat] = by_category.get(cat, 0) + 1
            latest.append({
                "file": f.name,
                "category": cat,
                "source": data.get("source_ai", "?"),
                "preview": data.get("content", "")[:100],
                "modified": time.ctime(f.stat().st_mtime),
            })
        except Exception:
            pass
    return {"total": len(files), "by_category": by_category, "latest": latest}


def get_memory_count():
    """Get memory entry count."""
    try:
        with open("/tmp/c.txt") as f:
            cookie = f.read().strip().replace("odysseus_session ", "")
        import urllib.request
        req = urllib.request.Request(
            "http://localhost:7000/api/memory/timeline?limit=1",
            headers={"Cookie": f"odysseus_session={cookie}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            d = json.loads(resp.read())
            return len(d.get("timeline", []))
    except Exception as e:
        return f"auth needed ({type(e).__name__})"


def get_skills_count():
    """Get skills count."""
    try:
        with open("/tmp/c.txt") as f:
            cookie = f.read().strip().replace("odysseus_session ", "")
        import urllib.request
        req = urllib.request.Request(
            "http://localhost:7000/api/skills",
            headers={"Cookie": f"odysseus_session={cookie}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            d = json.loads(resp.read())
            return len(d.get("skills", []))
    except Exception as e:
        return "?"


def get_vram():
    """Get current VRAM usage."""
    try:
        with open("/sys/class/drm/card1/device/mem_info_vram_used") as f:
            used = int(f.read()) / 1e9
        with open("/sys/class/drm/card1/device/mem_info_vram_total") as f:
            total = int(f.read()) / 1e9
        return {"used_gb": round(used, 2), "total_gb": round(total, 2),
                "free_gb": round(total - used, 2),
                "percent": round(used / total * 100, 1)}
    except Exception:
        return None


def get_state():
    """Get full state for the dashboard."""
    jobs = get_jobs()
    for j in jobs:
        j["log_tail"] = get_log_tail(j["log_file"], lines=8)
    return {
        "timestamp": time.time(),
        "timestamp_human": time.strftime("%H:%M:%S"),
        "jobs": jobs,
        "suggestions": get_suggestions(),
        "memory_count": get_memory_count(),
        "skills_count": get_skills_count(),
        "vram": get_vram(),
    }


# === HTML ===
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>VEXinWorks AI Dashboard</title>
<style>
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0a0e14;
    color: #c9d1d9;
    margin: 0;
    padding: 20px;
    line-height: 1.4;
  }
  h1 { color: #58a6ff; margin: 0 0 20px 0; font-size: 24px; }
  h2 { color: #79c0ff; margin: 20px 0 10px 0; font-size: 18px; }
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
    padding-bottom: 15px;
    border-bottom: 1px solid #21262d;
  }
  .stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
  }
  .stat {
    background: #161b22;
    padding: 12px 16px;
    border-radius: 6px;
    border: 1px solid #30363d;
  }
  .stat-label { font-size: 11px; color: #8b949e; text-transform: uppercase; }
  .stat-value { font-size: 22px; font-weight: 600; color: #f0f6fc; margin-top: 4px; }
  .stat.green .stat-value { color: #56d364; }
  .stat.blue .stat-value { color: #58a6ff; }
  .stat.yellow .stat-value { color: #d29922; }
  .stat.red .stat-value { color: #f85149; }

  .job {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 12px 16px;
    margin-bottom: 12px;
  }
  .job-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }
  .job-name {
    font-weight: 600;
    color: #f0f6fc;
    font-size: 15px;
  }
  .job-status {
    display: flex;
    gap: 8px;
    font-size: 12px;
    color: #8b949e;
  }
  .pulse {
    width: 8px;
    height: 8px;
    background: #56d364;
    border-radius: 50%;
    animation: pulse 1.5s infinite;
    display: inline-block;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
  .log-tail {
    background: #0d1117;
    border: 1px solid #21262d;
    border-radius: 4px;
    padding: 8px 12px;
    font-family: "SF Mono", Monaco, Consolas, monospace;
    font-size: 12px;
    color: #8b949e;
    max-height: 200px;
    overflow-y: auto;
    white-space: pre-wrap;
  }
  .log-tail .thinking { color: #d2a8ff; }
  .log-tail .summary { color: #56d364; }
  .log-tail .error { color: #f85149; }
  .log-tail .label { color: #58a6ff; font-weight: 600; }

  .suggestion {
    background: #0d1117;
    border: 1px solid #21262d;
    border-radius: 4px;
    padding: 8px 12px;
    margin-bottom: 6px;
    font-size: 13px;
  }
  .suggestion .meta {
    color: #8b949e;
    font-size: 11px;
    margin-bottom: 4px;
  }
  .suggestion .preview { color: #c9d1d9; }
  .category-tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 3px;
    font-size: 11px;
    margin-right: 6px;
    background: #1f6feb33;
    color: #79c0ff;
    border: 1px solid #1f6feb55;
  }
  .footer {
    margin-top: 30px;
    padding-top: 15px;
    border-top: 1px solid #21262d;
    color: #8b949e;
    font-size: 12px;
    text-align: center;
  }
</style>
</head>
<body>
  <div class="header">
    <h1>🧠 VEXinWorks AI Dashboard</h1>
    <div>
      <span class="pulse"></span>
      <span style="color:#8b949e;font-size:12px;">Live · refreshes every 2s · <span id="time">--:--:--</span></span>
    </div>
  </div>

  <div id="content">Loading...</div>

  <div class="footer">
    <a href="https://github.com/VEXinWorks/multi-ai-orchestrator" style="color:#58a6ff;">github.com/VEXinWorks/multi-ai-orchestrator</a>
  </div>

<script>
async function fetchState() {
  try {
    const r = await fetch('/api/state');
    const s = await r.json();
    render(s);
    document.getElementById('time').textContent = s.timestamp_human;
  } catch (e) {
    document.getElementById('content').innerHTML = '<div style="color:#f85149;">Error: ' + e + '</div>';
  }
}

function render(state) {
  const html = [];

  // Stats
  const vram = state.vram || {};
  const vramPct = vram.percent || 0;
  const vramClass = vramPct > 80 ? 'red' : vramPct > 50 ? 'yellow' : 'green';
  html.push('<div class="stats">');
  html.push(`<div class="stat blue"><div class="stat-label">Memory</div><div class="stat-value">${state.memory_count}</div></div>`);
  html.push(`<div class="stat green"><div class="stat-label">Skills</div><div class="stat-value">${state.skills_count}</div></div>`);
  html.push(`<div class="stat yellow"><div class="stat-label">Suggestions</div><div class="stat-value">${state.suggestions.total}</div></div>`);
  html.push(`<div class="stat ${vramClass}"><div class="stat-label">VRAM</div><div class="stat-value">${vram.used_gb || '?'} / ${vram.total_gb || '?'} GB</div></div>`);
  html.push(`<div class="stat blue"><div class="stat-label">Jobs Running</div><div class="stat-value">${state.jobs.length}</div></div>`);
  html.push('</div>');

  // Jobs
  html.push('<h2>🤖 Active AI Jobs</h2>');
  if (state.jobs.length === 0) {
    html.push('<div style="color:#8b949e;padding:20px;background:#161b22;border-radius:6px;">No autonomous jobs running. Start one with:<br><code>bash /tmp/audit_all.sh &</code></div>');
  } else {
    for (const j of state.jobs) {
      html.push('<div class="job">');
      html.push(`<div class="job-header">
        <div class="job-name"><span class="pulse"></span> ${j.name}</div>
        <div class="job-status">
          <span>PID ${j.pid}</span>
          <span>uptime ${j.etime}</span>
        </div>
      </div>`);
      // Log tail with highlighting
      const log = j.log_tail.map(line => {
        line = escapeHtml(line);
        if (line.includes('Thinking:')) line = `<span class="label">${line}</span>`;
        else if (line.includes('Summary:')) line = `<span class="label">${line}</span>`;
        else if (line.includes('--- GLM') || line.includes('--- minimax') || line.includes('--- nemotron')) line = `<span class="label">${line}</span>`;
        else if (line.includes('FAILED')) line = `<span class="error">${line}</span>`;
        return line;
      }).join('\\n');
      html.push(`<pre class="log-tail">${log || '(no output yet)'}</pre>`);
      html.push('</div>');
    }
  }

  // Suggestions
  html.push('<h2>💡 Latest Suggestions</h2>');
  if (state.suggestions.latest.length === 0) {
    html.push('<div style="color:#8b949e;">No suggestions yet</div>');
  } else {
    for (const s of state.suggestions.latest) {
      html.push(`<div class="suggestion">
        <div class="meta">
          <span class="category-tag">${s.category}</span>
          by ${escapeHtml(s.source)} · ${s.modified}
        </div>
        <div class="preview">${escapeHtml(s.preview)}...</div>
      </div>`);
    }
    const cats = Object.entries(state.suggestions.by_category);
    if (cats.length) {
      html.push('<div style="margin-top:8px;font-size:12px;color:#8b949e;">By category: ');
      cats.forEach(([k, v]) => html.push(`${escapeHtml(k)}: ${v} · `));
      html.push('</div>');
    }
  }

  document.getElementById('content').innerHTML = html.join('');
}

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

setInterval(fetchState, 2000);
fetchState();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass  # suppress access logs

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML.encode())
        elif self.path == "/api/state":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            state = get_state()
            self.wfile.write(json.dumps(state).encode())
        else:
            self.send_response(404)
            self.end_headers()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7777)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"=" * 60)
    print(f"🧠 VEXinWorks AI Dashboard")
    print(f"   Open: http://localhost:{args.port}")
    print(f"   API:  http://localhost:{args.port}/api/state")
    print(f"=" * 60)
    print(f"Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()