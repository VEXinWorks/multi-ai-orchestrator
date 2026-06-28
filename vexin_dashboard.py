#!/usr/bin/env python3
"""
vexin_dashboard.py — V2: Live Multi-AI Interaction Dashboard

Shows each AI as a profile card with:
- SVG avatar (unique per AI)
- Role/status (what they're doing)
- Recent outputs
- Click to expand → modal with full log

Plus:
- Real-time activity feed
- AI-to-AI interaction visualization
- Memory, skills, suggestions counters
- VRAM/RAM/DISK stats

Open http://localhost:7777 in your browser.
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

# AI Profiles — each AI gets a distinct persona
AI_PROFILES = {
    "GLM-5.2": {
        "name": "GLM-5.2",
        "avatar_color": "#10a37f",
        "role": "General-Purpose Professor",
        "personality": "Careful, structured, gives detailed step-by-step reasoning",
        "specialty": "Software architecture, debugging, code review",
        "avatar_svg": '''<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="g1" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#10a37f"/>
      <stop offset="100%" stop-color="#1a7f64"/>
    </linearGradient>
  </defs>
  <circle cx="50" cy="50" r="48" fill="url(#g1)"/>
  <circle cx="35" cy="45" r="6" fill="#fff" opacity="0.95"/>
  <circle cx="65" cy="45" r="6" fill="#fff" opacity="0.95"/>
  <circle cx="35" cy="46" r="3" fill="#0a0e14"/>
  <circle cx="65" cy="46" r="3" fill="#0a0e14"/>
  <path d="M 32 65 Q 50 75 68 65" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round"/>
  <text x="50" y="92" text-anchor="middle" font-size="9" font-weight="700" fill="#fff" font-family="sans-serif">GLM</text>
</svg>''',
    },
    "minimax-m3": {
        "name": "minimax-m3",
        "avatar_color": "#8e44ad",
        "role": "Chat Specialist",
        "personality": "Fast, conversational, builds on others' answers",
        "specialty": "Conversational AI, synthesis, practical answers",
        "avatar_svg": '''<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="g2" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#a855f7"/>
      <stop offset="100%" stop-color="#7c3aed"/>
    </linearGradient>
  </defs>
  <circle cx="50" cy="50" r="48" fill="url(#g2)"/>
  <circle cx="35" cy="45" r="6" fill="#fff" opacity="0.95"/>
  <circle cx="65" cy="45" r="6" fill="#fff" opacity="0.95"/>
  <circle cx="35" cy="46" r="3" fill="#0a0e14"/>
  <circle cx="65" cy="46" r="3" fill="#0a0e14"/>
  <path d="M 35 68 Q 50 60 65 68" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round"/>
  <text x="50" y="92" text-anchor="middle" font-size="8" font-weight="700" fill="#fff" font-family="sans-serif">M3</text>
</svg>''',
    },
    "nemotron-3-ultra": {
        "name": "nemotron-3-ultra",
        "avatar_color": "#dc2626",
        "role": "Deep Reasoner",
        "personality": "Thorough, logical, catches subtle errors, pushes back on weak arguments",
        "specialty": "Reasoning, math, finding bugs in others' thinking",
        "avatar_svg": '''<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="g3" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#ef4444"/>
      <stop offset="100%" stop-color="#b91c1c"/>
    </linearGradient>
  </defs>
  <circle cx="50" cy="50" r="48" fill="url(#g3)"/>
  <circle cx="35" cy="45" r="6" fill="#fff" opacity="0.95"/>
  <circle cx="65" cy="45" r="6" fill="#fff" opacity="0.95"/>
  <circle cx="35" cy="46" r="3" fill="#0a0e14"/>
  <circle cx="65" cy="46" r="3" fill="#0a0e14"/>
  <path d="M 30 65 L 70 65" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round"/>
  <text x="50" y="92" text-anchor="middle" font-size="7" font-weight="700" fill="#fff" font-family="sans-serif">N3U</text>
</svg>''',
    },
    "deepseek-r1:1.5b": {
        "name": "deepseek-r1:1.5b",
        "avatar_color": "#f59e0b",
        "role": "CPU Meta-Reasoner",
        "personality": "Quick, concise, focused — plans the approach, doesn't answer",
        "specialty": "Thinking/planning, fast local pre-processing",
        "avatar_svg": '''<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="g4" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#fbbf24"/>
      <stop offset="100%" stop-color="#d97706"/>
    </linearGradient>
  </defs>
  <circle cx="50" cy="50" r="48" fill="url(#g4)"/>
  <circle cx="35" cy="45" r="5" fill="#fff" opacity="0.95"/>
  <circle cx="65" cy="45" r="5" fill="#fff" opacity="0.95"/>
  <circle cx="35" cy="46" r="2.5" fill="#0a0e14"/>
  <circle cx="65" cy="46" r="2.5" fill="#0a0e14"/>
  <text x="50" y="78" text-anchor="middle" font-size="20" fill="#fff" font-weight="700" font-family="monospace">{ }</text>
  <text x="50" y="92" text-anchor="middle" font-size="8" font-weight="700" fill="#fff" font-family="sans-serif">R1.5</text>
</svg>''',
    },
    "llama3.1:8b": {
        "name": "llama3.1:8b",
        "avatar_color": "#3b82f6",
        "role": "Local Executor (GPU)",
        "personality": "Reliable workhorse, follows plans, gives thorough answers",
        "specialty": "General execution, RAG, business logic",
        "avatar_svg": '''<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="g5" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#60a5fa"/>
      <stop offset="100%" stop-color="#2563eb"/>
    </linearGradient>
  </defs>
  <circle cx="50" cy="50" r="48" fill="url(#g5)"/>
  <circle cx="35" cy="45" r="6" fill="#fff" opacity="0.95"/>
  <circle cx="65" cy="45" r="6" fill="#fff" opacity="0.95"/>
  <circle cx="35" cy="46" r="3" fill="#0a0e14"/>
  <circle cx="65" cy="46" r="3" fill="#0a0e14"/>
  <path d="M 32 65 Q 50 75 68 65" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round"/>
  <text x="50" y="92" text-anchor="middle" font-size="9" font-weight="700" fill="#fff" font-family="sans-serif">L31</text>
</svg>''',
    },
}

# Local "AI helper" for João
JOAO_AVATAR = '''<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="gj" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#ec4899"/>
      <stop offset="100%" stop-color="#be185d"/>
    </linearGradient>
  </defs>
  <circle cx="50" cy="50" r="48" fill="url(#gj)"/>
  <text x="50" y="58" text-anchor="middle" font-size="32" fill="#fff" font-family="sans-serif">👤</text>
  <text x="50" y="92" text-anchor="middle" font-size="9" font-weight="700" fill="#fff" font-family="sans-serif">JOÃO</text>
</svg>'''


def identify_active_ais(log_file, lines=20):
    """Identify which AIs are currently active in a log file."""
    if not log_file or not os.path.exists(log_file):
        return []
    try:
        with open(log_file, 'r', errors='ignore') as f:
            content = f.read()
        # Find recent AI mentions
        recent = content.splitlines()[-lines * 3:]
        active = set()
        last_topic = ""
        for line in recent:
            for ai_name in AI_PROFILES.keys():
                if ai_name in line or ai_name.replace("-", "") in line.replace("-", ""):
                    active.add(ai_name)
            # Track current topic
            if "=== " in line and "===" in line[4:]:
                # Try to extract topic
                m = re.search(r'===\s*([^=]+?)\s*===', line)
                if m:
                    last_topic = m.group(1).strip()
        return list(active), last_topic
    except Exception:
        return [], ""


def get_jobs():
    """Get all running AI jobs with rich metadata."""
    r = subprocess.run(
        ["bash", "-c",
         "ps -ef | grep -E 'audit_all|research_business|deep_review|teach_prod|research_paraguay|business_plan|apply_best|generate_patches|ai_school.py' | grep -v grep"],
        capture_output=True, text=True, timeout=5,
    )
    jobs = []
    for line in r.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        pid = parts[1]
        etime = parts[4]
        cmd = parts[7]

        job_name = None
        for name in LOG_FILES.keys():
            if name in cmd:
                job_name = name
                break
        if not job_name and "ai_school.py" in cmd:
            job_name = "ai_school"
        if not job_name:
            continue

        log_file = LOG_FILES.get(job_name, "")
        active_ais, current_topic = identify_active_ais(log_file)

        # Get log tail
        log_tail = []
        if log_file and os.path.exists(log_file):
            try:
                with open(log_file, 'r', errors='ignore') as f:
                    log_tail = f.read().splitlines()[-12:]
            except Exception:
                pass

        jobs.append({
            "name": job_name,
            "pid": pid,
            "etime": etime,
            "log_file": log_file,
            "log_tail": log_tail,
            "active_ais": active_ais,
            "current_topic": current_topic,
        })
    return jobs


def get_suggestions():
    """Get suggestion files with categorization."""
    if not SUGGESTIONS_DIR.exists():
        return {"total": 0, "by_category": {}, "by_ai": {}, "latest": []}
    files = list(SUGGESTIONS_DIR.glob("*.json"))
    by_category = {}
    by_ai = {}
    latest = []
    for f in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
        try:
            data = json.loads(f.read_text())
            cat = data.get("category", "?")
            src = data.get("source_ai", "?")
            by_category[cat] = by_category.get(cat, 0) + 1
            # Extract AI name from source like "GLM-5.2_vexin_self_upgrade.py"
            ai_name = src.split('_')[0] if '_' in src else src
            by_ai[ai_name] = by_ai.get(ai_name, 0) + 1
            latest.append({
                "file": f.name,
                "category": cat,
                "source": src,
                "ai": ai_name,
                "preview": data.get("content", "")[:200],
                "modified": time.ctime(f.stat().st_mtime),
                "ts": f.stat().st_mtime,
            })
        except Exception:
            pass
    return {"total": len(files), "by_category": by_category, "by_ai": by_ai, "latest": latest}


def get_interactions():
    """Find recent AI-to-AI interactions in logs."""
    interactions = []
    for job_name, log_file in LOG_FILES.items():
        if not os.path.exists(log_file):
            continue
        try:
            with open(log_file, 'r', errors='ignore') as f:
                lines = f.read().splitlines()
            # Find sections where one AI cites another
            for i, line in enumerate(lines):
                if i < 5:  # skip header
                    continue
                # Look for patterns like "--- GLM-5.2 ---" followed by text mentioning other AIs
                m = re.match(r'^---\s+(\S+)\s+---', line)
                if m:
                    speaker = m.group(1)
                    # Check next 5 lines for mentions of other AIs
                    text = '\n'.join(lines[i+1:i+8])
                    for other_ai in AI_PROFILES.keys():
                        if other_ai != speaker and (other_ai in text or other_ai.split('-')[0] in text):
                            if len(interactions) < 20:  # limit
                                interactions.append({
                                    "speaker": speaker,
                                    "responds_to": other_ai,
                                    "job": job_name,
                                    "preview": text[:200],
                                    "ts": time.time(),
                                })
        except Exception:
            pass
    return interactions


def get_memory_count():
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
        return f"? ({type(e).__name__})"


def get_skills_count():
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
    try:
        with open("/sys/class/drm/card1/device/mem_info_vram_used") as f:
            used = int(f.read()) / 1e9
        with open("/sys/class/drm/card1/device/mem_info_vram_total") as f:
            total = int(f.read()) / 1e9
        return {"used_gb": round(used, 2), "total_gb": round(total, 2),
                "free_gb": round(total - used, 2), "percent": round(used / total * 100, 1)}
    except Exception:
        return None


def get_state():
    return {
        "timestamp": time.time(),
        "timestamp_human": time.strftime("%H:%M:%S"),
        "jobs": get_jobs(),
        "suggestions": get_suggestions(),
        "interactions": get_interactions(),
        "memory_count": get_memory_count(),
        "skills_count": get_skills_count(),
        "vram": get_vram(),
        "ai_profiles": AI_PROFILES,
    }


HTML = r"""<!DOCTYPE html>
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
  h1 { color: #58a6ff; margin: 0 0 8px 0; font-size: 26px; }
  h2 { color: #79c0ff; margin: 24px 0 12px 0; font-size: 18px; }
  h3 { color: #c9d1d9; margin: 12px 0 8px 0; font-size: 14px; }
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid #21262d;
  }
  .subtitle { color: #8b949e; font-size: 13px; }

  .stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 10px;
    margin-bottom: 20px;
  }
  .stat {
    background: #161b22;
    padding: 12px 14px;
    border-radius: 8px;
    border: 1px solid #30363d;
  }
  .stat-label { font-size: 11px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; }
  .stat-value { font-size: 24px; font-weight: 700; margin-top: 4px; }
  .stat.green .stat-value { color: #56d364; }
  .stat.blue .stat-value { color: #58a6ff; }
  .stat.yellow .stat-value { color: #d29922; }
  .stat.red .stat-value { color: #f85149; }
  .stat.purple .stat-value { color: #a371f7; }

  /* AI Profiles Grid */
  .ai-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 14px;
    margin-bottom: 20px;
  }
  .ai-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 14px;
    cursor: pointer;
    transition: all 0.2s;
    position: relative;
    overflow: hidden;
  }
  .ai-card:hover {
    border-color: #58a6ff;
    transform: translateY(-2px);
    box-shadow: 0 8px 20px rgba(88, 166, 255, 0.15);
  }
  .ai-card.busy {
    border-color: #56d364;
    box-shadow: 0 0 12px rgba(86, 211, 100, 0.2);
  }
  .ai-card.busy::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: linear-gradient(90deg, #56d364, #58a6ff, #a371f7, #56d364);
    background-size: 200% 100%;
    animation: shimmer 2s linear infinite;
  }
  @keyframes shimmer {
    0% { background-position: 0% 0; }
    100% { background-position: 200% 0; }
  }
  .ai-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 10px;
  }
  .ai-avatar {
    width: 50px;
    height: 50px;
    border-radius: 50%;
    flex-shrink: 0;
    background: #0d1117;
  }
  .ai-avatar svg {
    width: 100%;
    height: 100%;
    border-radius: 50%;
  }
  .ai-info { flex: 1; min-width: 0; }
  .ai-name {
    font-weight: 700;
    color: #f0f6fc;
    font-size: 14px;
    margin-bottom: 2px;
  }
  .ai-role {
    font-size: 11px;
    color: #8b949e;
  }
  .ai-status {
    font-size: 11px;
    margin-top: 6px;
    color: #8b949e;
  }
  .ai-status .busy-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    background: #56d364;
    border-radius: 50%;
    animation: pulse 1.5s infinite;
    margin-right: 4px;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
  .ai-current-task {
    background: #0d1117;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 12px;
    color: #c9d1d9;
    margin-top: 8px;
    border-left: 3px solid #58a6ff;
  }
  .ai-current-task .label {
    color: #58a6ff;
    font-weight: 600;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    display: block;
    margin-bottom: 3px;
  }

  /* Jobs Section */
  .job {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 12px 14px;
    margin-bottom: 10px;
  }
  .job-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }
  .job-name { font-weight: 600; color: #f0f6fc; font-size: 14px; }
  .job-meta { font-size: 11px; color: #8b949e; }

  .log-tail {
    background: #0d1117;
    border: 1px solid #21262d;
    border-radius: 6px;
    padding: 10px 12px;
    font-family: "SF Mono", Monaco, Consolas, monospace;
    font-size: 11px;
    color: #c9d1d9;
    max-height: 240px;
    overflow-y: auto;
    white-space: pre-wrap;
    line-height: 1.5;
  }
  .log-tail .ai-label { color: #58a6ff; font-weight: 600; }
  .log-tail .thinking { color: #d2a8ff; }
  .log-tail .summary { color: #56d364; }
  .log-tail .error { color: #f85149; }

  /* Suggestions */
  .suggestion {
    background: #0d1117;
    border: 1px solid #21262d;
    border-radius: 6px;
    padding: 8px 12px;
    margin-bottom: 6px;
    font-size: 12px;
  }
  .suggestion .meta {
    color: #8b949e;
    font-size: 10px;
    margin-bottom: 4px;
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .category-tag {
    display: inline-block;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 10px;
    background: #1f6feb33;
    color: #79c0ff;
    border: 1px solid #1f6feb55;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .ai-tag {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 10px;
    background: #30363d;
    color: #c9d1d9;
  }
  .ai-tag-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
  }
  .suggestion .preview { color: #c9d1d9; line-height: 1.4; }

  /* Interactions */
  .interaction {
    background: #0d1117;
    border: 1px solid #21262d;
    border-radius: 6px;
    padding: 8px 12px;
    margin-bottom: 6px;
    font-size: 12px;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .interaction .ai-mini-avatar {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .interaction .arrow {
    color: #8b949e;
    font-size: 14px;
  }
  .interaction .text {
    flex: 1;
    color: #8b949e;
    font-size: 11px;
  }
  .interaction .text strong { color: #c9d1d9; }

  /* Modal */
  .modal-overlay {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.7);
    display: none;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    padding: 20px;
  }
  .modal-overlay.active { display: flex; }
  .modal {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 12px;
    padding: 24px;
    max-width: 800px;
    width: 100%;
    max-height: 90vh;
    overflow-y: auto;
  }
  .modal-header {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 16px;
    padding-bottom: 16px;
    border-bottom: 1px solid #30363d;
  }
  .modal-avatar {
    width: 80px;
    height: 80px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .modal-title { flex: 1; }
  .modal-title h2 { margin: 0; }
  .modal-close {
    background: #30363d;
    border: none;
    color: #c9d1d9;
    font-size: 18px;
    width: 32px;
    height: 32px;
    border-radius: 6px;
    cursor: pointer;
  }
  .modal-close:hover { background: #484f58; }
  .modal-section { margin: 16px 0; }
  .modal-section h3 {
    color: #79c0ff;
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .modal-log {
    background: #0d1117;
    border: 1px solid #21262d;
    border-radius: 6px;
    padding: 12px;
    font-family: "SF Mono", Monaco, Consolas, monospace;
    font-size: 12px;
    max-height: 400px;
    overflow-y: auto;
    white-space: pre-wrap;
  }

  .footer {
    margin-top: 30px;
    padding-top: 15px;
    border-top: 1px solid #21262d;
    color: #8b949e;
    font-size: 11px;
    text-align: center;
  }
  .pulse {
    display: inline-block;
    width: 8px;
    height: 8px;
    background: #56d364;
    border-radius: 50%;
    animation: pulse 1.5s infinite;
    margin-right: 4px;
  }
</style>
</head>
<body>
  <div class="header">
    <div>
      <h1>🧠 VEXinWorks AI Dashboard</h1>
      <div class="subtitle">Live multi-AI orchestration · click any AI to see details</div>
    </div>
    <div>
      <span class="pulse"></span>
      <span style="color:#8b949e;font-size:12px;">Live · refreshes 2s · <span id="time">--:--:--</span></span>
    </div>
  </div>

  <div id="content">Loading...</div>

  <div class="modal-overlay" id="modal-overlay" onclick="if(event.target===this) closeModal()">
    <div class="modal" id="modal">
      <!-- Modal content will be injected here -->
    </div>
  </div>

  <div class="footer">
    <a href="https://github.com/VEXinWorks/multi-ai-orchestrator" style="color:#58a6ff;">github.com/VEXinWorks/multi-ai-orchestrator</a>
  </div>

<script>
let state = {};
let modalData = null;

async function fetchState() {
  try {
    const r = await fetch('/api/state');
    state = await r.json();
    render();
    document.getElementById('time').textContent = state.timestamp_human;
  } catch (e) {
    document.getElementById('content').innerHTML = '<div style="color:#f85149;">Error: ' + e + '</div>';
  }
}

function render() {
  const html = [];

  // Stats row
  const vram = state.vram || {};
  const vramPct = vram.percent || 0;
  const vramClass = vramPct > 80 ? 'red' : vramPct > 50 ? 'yellow' : 'green';
  html.push('<div class="stats">');
  html.push(`<div class="stat blue"><div class="stat-label">Memory</div><div class="stat-value">${state.memory_count}</div></div>`);
  html.push(`<div class="stat green"><div class="stat-label">Skills</div><div class="stat-value">${state.skills_count}</div></div>`);
  html.push(`<div class="stat yellow"><div class="stat-label">Suggestions</div><div class="stat-value">${state.suggestions.total}</div></div>`);
  html.push(`<div class="stat ${vramClass}"><div class="stat-label">VRAM</div><div class="stat-value">${vram.used_gb || '?'} / ${vram.total_gb || '?'}</div></div>`);
  html.push(`<div class="stat purple"><div class="stat-label">Jobs</div><div class="stat-value">${state.jobs.length}</div></div>`);
  html.push('</div>');

  // AI Profiles Section
  html.push('<h2>🤖 Your AI Team</h2>');
  html.push('<div class="ai-grid">');

  // Which AIs are currently active
  const activeAIs = new Set();
  state.jobs.forEach(j => j.active_ais.forEach(a => activeAIs.add(a)));
  const currentTopics = {};
  state.jobs.forEach(j => {
    if (j.current_topic) currentTopics[j.name] = j.current_topic;
  });

  // Get suggestion counts per AI
  const aiSuggestionCounts = state.suggestions.by_ai || {};

  // Render each AI profile
  for (const [key, profile] of Object.entries(state.ai_profiles)) {
    const isBusy = activeAIs.has(key);
    const suggestionCount = aiSuggestionCounts[key] || 0;
    const currentJob = state.jobs.find(j => j.active_ais.includes(key));

    html.push(`<div class="ai-card ${isBusy ? 'busy' : ''}" onclick='showModal("${key}")'>`);
    html.push(`<div class="ai-header">`);
    html.push(`<div class="ai-avatar">${profile.avatar_svg}</div>`);
    html.push(`<div class="ai-info">`);
    html.push(`<div class="ai-name">${profile.name}</div>`);
    html.push(`<div class="ai-role">${profile.role}</div>`);
    html.push(`</div></div>`);
    html.push(`<div class="ai-status">`);
    if (isBusy) {
      html.push(`<span class="busy-dot"></span> Working now${currentJob ? ` on <strong>${currentJob.name}</strong>` : ''}`);
    } else {
      html.push(`<span style="color:#6e7681;">○ Idle</span>`);
    }
    if (suggestionCount > 0) {
      html.push(`<div style="margin-top:4px;font-size:11px;color:#8b949e;">💡 ${suggestionCount} suggestions contributed</div>`);
    }
    html.push(`</div>`);

    if (currentJob && currentJob.current_topic) {
      html.push(`<div class="ai-current-task">`);
      html.push(`<span class="label">Current task</span>`);
      html.push(escapeHtml(currentJob.current_topic));
      html.push(`</div>`);
    }

    html.push(`<div style="margin-top:8px;font-size:11px;color:#6e7681;">${escapeHtml(profile.personality)}</div>`);
    html.push(`</div>`);
  }

  html.push('</div>');

  // AI-to-AI interactions
  if (state.interactions && state.interactions.length > 0) {
    html.push('<h2>🔄 AI ↔ AI Interactions</h2>');
    state.interactions.slice(0, 6).forEach(i => {
      const speakerProfile = state.ai_profiles[i.speaker];
      const responderProfile = state.ai_profiles[i.responds_to];
      const speakerSvg = speakerProfile ? speakerProfile.avatar_svg : '';
      const responderSvg = responderProfile ? responderProfile.avatar_svg : '';
      html.push(`<div class="interaction">`);
      html.push(`<div class="ai-mini-avatar">${speakerSvg}</div>`);
      html.push(`<span class="text"><strong>${escapeHtml(i.speaker)}</strong> responds to <strong>${escapeHtml(i.responds_to)}</strong></span>`);
      html.push(`<span class="arrow">→</span>`);
      html.push(`<div class="ai-mini-avatar">${responderSvg}</div>`);
      html.push(`<div class="text">${escapeHtml(i.job)}</div>`);
      html.push(`</div>`);
    });
  }

  // Active jobs
  html.push('<h2>⚙️ Active Jobs</h2>');
  if (state.jobs.length === 0) {
    html.push('<div style="color:#8b949e;padding:16px;background:#161b22;border-radius:8px;">No jobs running.</div>');
  } else {
    state.jobs.forEach(j => {
      html.push('<div class="job">');
      html.push(`<div class="job-header">
        <div class="job-name"><span class="pulse"></span> ${j.name}</div>
        <div class="job-meta">PID ${j.pid} · uptime ${j.etime}</div>
      </div>`);
      const log = j.log_tail.map(line => {
        let escaped = escapeHtml(line);
        if (line.includes('--- GLM') || line.includes('--- minimax') || line.includes('--- nemotron')) {
          escaped = `<span class="ai-label">${escaped}</span>`;
        } else if (line.includes('Thinking:') || line.includes('Summary:')) {
          escaped = `<span class="ai-label">${escaped}</span>`;
        } else if (line.includes('FAILED')) {
          escaped = `<span class="error">${escaped}</span>`;
        }
        return escaped;
      }).join('\n');
      html.push(`<pre class="log-tail">${log || '(no output yet)'}</pre>`);
      html.push('</div>');
    });
  }

  // Latest suggestions
  html.push('<h2>💡 Latest Suggestions</h2>');
  state.suggestions.latest.slice(0, 8).forEach(s => {
    const aiProfile = state.ai_profiles[s.ai] || {};
    const aiColor = aiProfile.avatar_color || '#8b949e';
    html.push(`<div class="suggestion">`);
    html.push(`<div class="meta">
      <span class="category-tag">${s.category}</span>
      <span class="ai-tag"><span class="ai-tag-dot" style="background:${aiColor}"></span>${escapeHtml(s.ai)}</span>
      <span>${s.modified}</span>
    </div>`);
    html.push(`<div class="preview">${escapeHtml(s.preview)}...</div>`);
    html.push(`</div>`);
  });

  document.getElementById('content').innerHTML = html.join('');
}

function showModal(aiKey) {
  const profile = state.ai_profiles[aiKey];
  if (!profile) return;

  const isBusy = state.jobs.some(j => j.active_ais.includes(aiKey));
  const currentJob = state.jobs.find(j => j.active_ais.includes(aiKey));
  const logText = currentJob ? currentJob.log_tail.join('\n') : 'No active log.';
  const suggestionCount = state.suggestions.by_ai[aiKey] || 0;

  const modalHtml = `
    <div class="modal-header">
      <div class="modal-avatar">${profile.avatar_svg}</div>
      <div class="modal-title">
        <h2>${profile.name}</h2>
        <div style="color:#8b949e;font-size:13px;">${profile.role}</div>
      </div>
      <button class="modal-close" onclick="closeModal()">×</button>
    </div>
    <div class="modal-section">
      <h3>Personality</h3>
      <div style="color:#c9d1d9;">${escapeHtml(profile.personality)}</div>
    </div>
    <div class="modal-section">
      <h3>Specialty</h3>
      <div style="color:#c9d1d9;">${escapeHtml(profile.specialty)}</div>
    </div>
    <div class="modal-section">
      <h3>Status</h3>
      <div>${isBusy ? '<span style="color:#56d364;">● Busy</span>' : '<span style="color:#8b949e;">○ Idle</span>'}</div>
      ${currentJob ? `<div style="color:#8b949e;font-size:12px;margin-top:4px;">Currently working on: <strong>${currentJob.name}</strong></div>` : ''}
      ${currentJob && currentJob.current_topic ? `<div style="color:#c9d1d9;font-size:12px;margin-top:4px;">Topic: ${escapeHtml(currentJob.current_topic)}</div>` : ''}
    </div>
    <div class="modal-section">
      <h3>Contributions</h3>
      <div style="color:#c9d1d9;">${suggestionCount} suggestions in the queue</div>
    </div>
    <div class="modal-section">
      <h3>Live Output</h3>
      <pre class="modal-log">${escapeHtml(logText)}</pre>
    </div>
  `;

  document.getElementById('modal').innerHTML = modalHtml;
  document.getElementById('modal-overlay').classList.add('active');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('active');
}

function escapeHtml(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
});

setInterval(fetchState, 2000);
fetchState();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass

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
            self.wfile.write(json.dumps(get_state()).encode())
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
    print(f"🧠 VEXinWorks AI Dashboard v2 (with AI profiles & modal)")
    print(f"   Open: http://localhost:{args.port}")
    print(f"   API:  http://localhost:{args.port}/api/state")
    print(f"=" * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()