#!/usr/bin/env python3
"""
vexin_dashboard.py — V3: Ultra-visual Multi-AI Dashboard

Features:
- Live system stats: CPU/RAM/VRAM/GPU temp with animated progress bars
- Real-time graphs (sparklines) for CPU/RAM/VRAM
- Beautiful AI profile cards with avatars and personality
- Modal popup for AI details (click any AI)
- AI-to-AI interaction visualization
- Emoji-rich, color-coded, animated

Open: http://localhost:7777
"""

import argparse
import collections
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
# marked with 'local' = runs on your hardware, 'cloud' = Ollama Cloud
AI_PROFILES = {
    "GLM-5.2": {
        "name": "GLM-5.2",
        "type": "cloud",
        "emoji": "🟢",
        "avatar_color": "#10a37f",
        "role": "Cloud Professor",
        "personality": "Careful, structured, gives detailed step-by-step reasoning",
        "specialty": "Software architecture, debugging, code review",
        "avatar_svg": '''<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="g1" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#10a37f"/><stop offset="100%" stop-color="#1a7f64"/>
  </linearGradient></defs>
  <circle cx="50" cy="50" r="48" fill="url(#g1)"/>
  <circle cx="35" cy="45" r="6" fill="#fff" opacity="0.95"/>
  <circle cx="65" cy="45" r="6" fill="#fff" opacity="0.95"/>
  <circle cx="35" cy="46" r="3" fill="#0a0e14"/><circle cx="65" cy="46" r="3" fill="#0a0e14"/>
  <path d="M 32 65 Q 50 75 68 65" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round"/>
  <text x="50" y="92" text-anchor="middle" font-size="9" font-weight="700" fill="#fff" font-family="sans-serif">GLM</text>
</svg>''',
    },
    "minimax-m3": {
        "name": "minimax-m3",
        "type": "cloud",
        "emoji": "🟣",
        "avatar_color": "#a855f7",
        "role": "Cloud Chat Specialist",
        "personality": "Fast, conversational, builds on others' answers",
        "specialty": "Conversational AI, synthesis, practical answers",
        "avatar_svg": '''<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="g2" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#a855f7"/><stop offset="100%" stop-color="#7c3aed"/>
  </linearGradient></defs>
  <circle cx="50" cy="50" r="48" fill="url(#g2)"/>
  <circle cx="35" cy="45" r="6" fill="#fff" opacity="0.95"/>
  <circle cx="65" cy="45" r="6" fill="#fff" opacity="0.95"/>
  <circle cx="35" cy="46" r="3" fill="#0a0e14"/><circle cx="65" cy="46" r="3" fill="#0a0e14"/>
  <path d="M 35 68 Q 50 60 65 68" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round"/>
  <text x="50" y="92" text-anchor="middle" font-size="8" font-weight="700" fill="#fff" font-family="sans-serif">M3</text>
</svg>''',
    },
    "nemotron-3-ultra": {
        "name": "nemotron-3-ultra",
        "type": "cloud",
        "emoji": "🔴",
        "avatar_color": "#ef4444",
        "role": "Cloud Deep Reasoner",
        "personality": "Thorough, logical, catches subtle errors, pushes back on weak arguments",
        "specialty": "Reasoning, math, finding bugs in others' thinking",
        "avatar_svg": '''<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="g3" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#ef4444"/><stop offset="100%" stop-color="#b91c1c"/>
  </linearGradient></defs>
  <circle cx="50" cy="50" r="48" fill="url(#g3)"/>
  <circle cx="35" cy="45" r="6" fill="#fff" opacity="0.95"/>
  <circle cx="65" cy="45" r="6" fill="#fff" opacity="0.95"/>
  <circle cx="35" cy="46" r="3" fill="#0a0e14"/><circle cx="65" cy="46" r="3" fill="#0a0e14"/>
  <path d="M 30 65 L 70 65" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round"/>
  <text x="50" y="92" text-anchor="middle" font-size="7" font-weight="700" fill="#fff" font-family="sans-serif">N3U</text>
</svg>''',
    },
    "deepseek-r1:1.5b": {
        "name": "deepseek-r1:1.5b",
        "type": "local",
        "emoji": "🟠",
        "avatar_color": "#f59e0b",
        "role": "🖥️ LOCAL · CPU Meta-Reasoner",
        "personality": "Quick, concise, focused — plans the approach, doesn't answer",
        "specialty": "Thinking/planning, fast local pre-processing",
        "avatar_svg": '''<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="g4" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#fbbf24"/><stop offset="100%" stop-color="#d97706"/>
  </linearGradient></defs>
  <circle cx="50" cy="50" r="48" fill="url(#g4)"/>
  <circle cx="35" cy="45" r="5" fill="#fff" opacity="0.95"/>
  <circle cx="65" cy="45" r="5" fill="#fff" opacity="0.95"/>
  <circle cx="35" cy="46" r="2.5" fill="#0a0e14"/><circle cx="65" cy="46" r="2.5" fill="#0a0e14"/>
  <text x="50" y="78" text-anchor="middle" font-size="20" fill="#fff" font-weight="700" font-family="monospace">{ }</text>
  <text x="50" y="92" text-anchor="middle" font-size="8" font-weight="700" fill="#fff" font-family="sans-serif">R1.5</text>
</svg>''',
    },
    "llama3.1:8b": {
        "name": "llama3.1:8b",
        "type": "local",
        "emoji": "🔵",
        "avatar_color": "#3b82f6",
        "role": "🖥️ LOCAL · GPU Executor",
        "personality": "Reliable workhorse, follows plans, gives thorough answers",
        "specialty": "General execution, RAG, business logic",
        "avatar_svg": '''<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="g5" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#60a5fa"/><stop offset="100%" stop-color="#2563eb"/>
  </linearGradient></defs>
  <circle cx="50" cy="50" r="48" fill="url(#g5)"/>
  <circle cx="35" cy="45" r="6" fill="#fff" opacity="0.95"/>
  <circle cx="65" cy="45" r="6" fill="#fff" opacity="0.95"/>
  <circle cx="35" cy="46" r="3" fill="#0a0e14"/><circle cx="65" cy="46" r="3" fill="#0a0e14"/>
  <path d="M 32 65 Q 50 75 68 65" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round"/>
  <text x="50" y="92" text-anchor="middle" font-size="9" font-weight="700" fill="#fff" font-family="sans-serif">L31</text>
</svg>''',
    },
}


# Global state for time-series data (last N samples)
class History:
    def __init__(self, maxlen=60):
        self.cpu = collections.deque(maxlen=maxlen)
        self.ram = collections.deque(maxlen=maxlen)
        self.vram = collections.deque(maxlen=maxlen)
        self.gpu_temp = collections.deque(maxlen=maxlen)
        self.cpu_temp = collections.deque(maxlen=maxlen)
        self.disk = collections.deque(maxlen=maxlen)

    def update(self, cpu, ram, vram, gpu_temp, cpu_temp, disk):
        self.cpu.append(cpu)
        self.ram.append(ram)
        self.vram.append(vram)
        self.gpu_temp.append(gpu_temp)
        self.cpu_temp.append(cpu_temp)
        self.disk.append(disk)


HISTORY = History()


def get_cpu():
    """Get CPU usage percent."""
    try:
        r = subprocess.run(['bash', '-c',
                           '''top -bn1 | grep "Cpu(s)" | sed "s/.*, *\\([0-9.]*\\)%* id.*/\\1/" | awk '{print 100 - $1}' '''],
                          capture_output=True, text=True, timeout=3)
        return float(r.stdout.strip() or 0)
    except Exception:
        return 0


def get_ram():
    """Get RAM usage percent."""
    try:
        r = subprocess.run(['free'], capture_output=True, text=True, timeout=3)
        lines = r.stdout.split('\n')
        if len(lines) > 1:
            parts = lines[1].split()
            total = int(parts[1])
            used = int(parts[2])
            return round(used / total * 100, 1)
    except Exception:
        pass
    return 0


def get_vram():
    """Get VRAM usage."""
    try:
        with open("/sys/class/drm/card1/device/mem_info_vram_used") as f:
            used = int(f.read()) / 1e9
        with open("/sys/class/drm/card1/device/mem_info_vram_total") as f:
            total = int(f.read()) / 1e9
        return {"used_gb": round(used, 2), "total_gb": round(total, 2),
                "free_gb": round(total - used, 2), "percent": round(used / total * 100, 1)}
    except Exception:
        return {"used_gb": 0, "total_gb": 17.16, "free_gb": 17.16, "percent": 0}


def get_temps():
    """Get CPU and GPU temperatures."""
    cpu_temp = 0
    gpu_temp = 0
    try:
        # CPU temp from coretemp
        for h in os.listdir('/sys/class/hwmon/'):
            name_file = f'/sys/class/hwmon/{h}/name'
            if os.path.exists(name_file):
                with open(name_file) as f:
                    name = f.read().strip()
                if name in ('coretemp', 'k10temp'):
                    temp_files = [f for f in os.listdir(f'/sys/class/hwmon/{h}/') if f.startswith('temp') and f.endswith('_input')]
                    if temp_files:
                        with open(f'/sys/class/hwmon/{h}/{temp_files[0]}') as f:
                            cpu_temp = max(cpu_temp, int(f.read()) // 1000)
                if name == 'amdgpu':
                    temp_files = [f for f in os.listdir(f'/sys/class/hwmon/{h}/') if f.startswith('temp') and f.endswith('_input')]
                    if temp_files:
                        with open(f'/sys/class/hwmon/{h}/{temp_files[0]}') as f:
                            gpu_temp = int(f.read()) // 1000
    except Exception:
        pass
    return cpu_temp, gpu_temp


def get_disk():
    """Get disk usage percent."""
    try:
        r = subprocess.run(['df', '-h', '/home'], capture_output=True, text=True, timeout=3)
        lines = r.stdout.split('\n')
        if len(lines) > 1:
            parts = lines[1].split()
            used_pct = parts[4].replace('%', '')
            return int(used_pct)
    except Exception:
        pass
    return 0


def get_load():
    """Get system load average."""
    try:
        with open('/proc/loadavg') as f:
            parts = f.read().split()
            return {
                "1min": float(parts[0]),
                "5min": float(parts[1]),
                "15min": float(parts[2]),
            }
    except Exception:
        return {"1min": 0, "5min": 0, "15min": 0}


def get_processes():
    """Get top CPU processes."""
    try:
        r = subprocess.run(['ps', '-eo', 'pid,pcpu,pmem,comm', '--sort=-pcpu'],
                          capture_output=True, text=True, timeout=3)
        lines = r.stdout.split('\n')[1:6]  # top 5
        procs = []
        for line in lines:
            parts = line.split(None, 3)
            if len(parts) >= 4:
                procs.append({
                    "pid": parts[0],
                    "cpu": float(parts[1]),
                    "mem": float(parts[2]),
                    "name": parts[3][:30],
                })
        return procs
    except Exception:
        return []


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
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        pid = parts[1]
        etime = parts[4]
        cmd = parts[7]
        # Get CPU/mem for this PID
        try:
            with open(f'/proc/{pid}/stat') as f:
                stat = f.read().split()
            cpu_pct = float(stat[13]) / max(1, int(stat[14])) * 100
        except Exception:
            cpu_pct = 0

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

        # Identify active AIs in log
        active_ais, current_topic = identify_active_ais(log_file)
        log_tail = []
        if log_file and os.path.exists(log_file):
            try:
                with open(log_file, 'r', errors='ignore') as f:
                    log_tail = f.read().splitlines()[-15:]
            except Exception:
                pass

        jobs.append({
            "name": job_name,
            "pid": pid,
            "etime": etime,
            "cpu_pct": round(cpu_pct, 1),
            "log_file": log_file,
            "log_tail": log_tail,
            "active_ais": active_ais,
            "current_topic": current_topic,
        })
    return jobs


def identify_active_ais(log_file, lines=20):
    if not log_file or not os.path.exists(log_file):
        return [], ""
    try:
        with open(log_file, 'r', errors='ignore') as f:
            content = f.read()
        recent = content.splitlines()[-lines * 3:]
        active = set()
        last_topic = ""
        for line in recent:
            for ai_name in AI_PROFILES.keys():
                if ai_name in line or ai_name.replace("-", "") in line.replace("-", ""):
                    active.add(ai_name)
            if "=== " in line and "===" in line[4:]:
                m = re.search(r'===\s*([^=]+?)\s*===', line)
                if m:
                    last_topic = m.group(1).strip()
        return list(active), last_topic
    except Exception:
        return [], ""


def get_suggestions():
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
            ai_name = src.split('_')[0] if '_' in src else src
            by_ai[ai_name] = by_ai.get(ai_name, 0) + 1
            latest.append({
                "file": f.name,
                "category": cat,
                "source": src,
                "ai": ai_name,
                "preview": data.get("content", "")[:200],
                "modified": time.ctime(f.stat().st_mtime),
            })
        except Exception:
            pass
    return {"total": len(files), "by_category": by_category, "by_ai": by_ai, "latest": latest}


def get_interactions():
    interactions = []
    for job_name, log_file in LOG_FILES.items():
        if not os.path.exists(log_file):
            continue
        try:
            with open(log_file, 'r', errors='ignore') as f:
                lines = f.read().splitlines()
            for i, line in enumerate(lines):
                if i < 5:
                    continue
                m = re.match(r'^---\s+(\S+)\s+---', line)
                if m:
                    speaker = m.group(1)
                    text = '\n'.join(lines[i+1:i+8])
                    for other_ai in AI_PROFILES.keys():
                        if other_ai != speaker and (other_ai in text or other_ai.split('-')[0] in text):
                            interactions.append({
                                "speaker": speaker,
                                "responds_to": other_ai,
                                "job": job_name,
                                "preview": text[:200],
                            })
        except Exception:
            pass
    return interactions[:10]


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
    except Exception:
        return "?"


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
    except Exception:
        return "?"


def get_state():
    cpu = get_cpu()
    ram = get_ram()
    vram = get_vram()
    cpu_temp, gpu_temp = get_temps()
    disk = get_disk()
    HISTORY.update(cpu, ram, vram["percent"], gpu_temp, cpu_temp, disk)

    # Other local models installed but not in active profiles
    active_profile_names = set(AI_PROFILES.keys())
    other_models = []
    try:
        r = subprocess.run(['ollama', 'list'], capture_output=True, text=True, timeout=5)
        lines = r.stdout.split('\n')
        if len(lines) > 1:
            header = lines[0].split()
            # Find SIZE column
            try:
                size_col = header.index('SIZE')
            except ValueError:
                size_col = 2
            for line in lines[1:]:
                parts = line.split()
                if len(parts) <= size_col:
                    continue
                name = parts[0]
                size_str = parts[size_col]
                if name in active_profile_names:
                    continue
                # Parse size (handles "1.1", "4.7", "274M", etc.)
                size_gb = 0
                try:
                    if size_str.endswith('GB'):
                        size_gb = float(size_str[:-2])
                    elif size_str.endswith('MB') or size_str.endswith('M'):
                        size_gb = float(size_str.rstrip('MB').rstrip('M')) / 1024
                    elif size_str.endswith('B'):
                        size_gb = float(size_str[:-1]) / 1e9
                    else:
                        size_gb = float(size_str)
                except Exception:
                    size_gb = 0
                # Skip cloud placeholders with 0 size
                if size_gb == 0 and ':cloud' in name:
                    continue
                # Determine emoji by purpose
                emoji = '📦'
                use = ''
                if 'vision' in name or 'llava' in name or 'moondream' in name:
                    emoji = '👁️'
                    use = 'vision'
                elif 'coder' in name or 'qwen' in name:
                    emoji = '⌨️'
                    use = 'code'
                elif 'embed' in name:
                    emoji = '🔢'
                    use = 'embeddings'
                elif 'r1' in name:
                    emoji = '🤔'
                    use = 'reasoning'
                else:
                    use = 'general'
                other_models.append({
                    'name': name,
                    'size_gb': f'{size_gb:.1f}' if size_gb else '?',
                    'use': use,
                    'emoji': emoji,
                })
    except Exception:
        pass

    return {
        "timestamp": time.time(),
        "timestamp_human": time.strftime("%H:%M:%S"),
        # System stats
        "cpu": cpu,
        "ram": ram,
        "vram": vram,
        "cpu_temp": cpu_temp,
        "gpu_temp": gpu_temp,
        "disk": disk,
        "load": get_load(),
        "processes": get_processes(),
        "history": {
            "cpu": list(HISTORY.cpu),
            "ram": list(HISTORY.ram),
            "vram": list(HISTORY.vram),
            "gpu_temp": list(HISTORY.gpu_temp),
            "cpu_temp": list(HISTORY.cpu_temp),
        },
        # AI data
        "jobs": get_jobs(),
        "suggestions": get_suggestions(),
        "interactions": get_interactions(),
        "memory_count": get_memory_count(),
        "skills_count": get_skills_count(),
        "other_local_models": other_models,
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
    background: linear-gradient(135deg, #0a0e14 0%, #0d1117 100%);
    color: #c9d1d9;
    margin: 0;
    padding: 20px;
    line-height: 1.4;
    min-height: 100vh;
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

  /* System stats grid with progress bars */
  .system-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 14px;
    margin-bottom: 20px;
  }
  .system-card {
    background: #161b22;
    padding: 14px;
    border-radius: 10px;
    border: 1px solid #30363d;
    position: relative;
    overflow: hidden;
  }
  .system-card .header-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 10px;
  }
  .system-card .title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: #c9d1d9;
    font-weight: 600;
  }
  .system-card .value {
    font-size: 22px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }
  .system-card .sparkline {
    margin-top: 8px;
    width: 100%;
    height: 30px;
    background: #0d1117;
    border-radius: 4px;
    border: 1px solid #21262d;
  }
  .progress-bar {
    width: 100%;
    height: 8px;
    background: #21262d;
    border-radius: 4px;
    overflow: hidden;
    margin: 8px 0 4px;
  }
  .progress-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.5s ease;
    background: linear-gradient(90deg, #56d364, #58a6ff);
    position: relative;
  }
  .progress-fill.warn { background: linear-gradient(90deg, #d29922, #f59e0b); }
  .progress-fill.danger { background: linear-gradient(90deg, #f85149, #ef4444); }
  .progress-fill.gpu {
    background: linear-gradient(90deg, #a371f7, #ec4899);
  }
  .progress-fill.temp-cool { background: linear-gradient(90deg, #56d364, #58a6ff); }
  .progress-fill.temp-warm { background: linear-gradient(90deg, #d29922, #f59e0b); }
  .progress-fill.temp-hot { background: linear-gradient(90deg, #f85149, #ef4444); }

  .stat-meta {
    display: flex;
    justify-content: space-between;
    font-size: 11px;
    color: #8b949e;
    margin-top: 4px;
  }

  /* Top processes */
  .processes {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 14px;
    margin-bottom: 20px;
  }
  .process-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 0;
    font-family: "SF Mono", Monaco, monospace;
    font-size: 12px;
  }
  .process-name { flex: 1; color: #c9d1d9; }
  .process-pid { color: #8b949e; min-width: 50px; }
  .process-bar {
    flex: 1;
    height: 6px;
    background: #21262d;
    border-radius: 3px;
    overflow: hidden;
  }
  .process-bar-fill { height: 100%; background: linear-gradient(90deg, #58a6ff, #56d364); }

  /* AI Profile Cards */
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
    box-shadow: 0 0 20px rgba(86, 211, 100, 0.3);
  }
  .ai-card.busy::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: linear-gradient(90deg, #56d364, #58a6ff, #a371f7, #ec4899, #56d364);
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
    width: 56px;
    height: 56px;
    border-radius: 50%;
    flex-shrink: 0;
    background: #0d1117;
    position: relative;
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
    font-size: 15px;
    margin-bottom: 2px;
    display: flex;
    align-items: center;
    gap: 6px;
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
  .busy-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    background: #56d364;
    border-radius: 50%;
    animation: pulse 1.5s infinite;
    margin-right: 4px;
    box-shadow: 0 0 8px rgba(86, 211, 100, 0.6);
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.4; transform: scale(0.9); }
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

  /* Jobs */
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
  .job-name {
    font-weight: 600;
    color: #f0f6fc;
    font-size: 14px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .job-name .emoji { font-size: 16px; }
  .job-meta { font-size: 11px; color: #8b949e; display: flex; gap: 12px; align-items: center; }
  .job-cpu { color: #58a6ff; font-weight: 600; }

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
    transition: border-color 0.2s;
  }
  .suggestion:hover { border-color: #30363d; }
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
    color: #58a6ff;
    font-size: 14px;
    animation: bounce 1.5s infinite;
  }
  @keyframes bounce {
    0%, 100% { transform: translateX(0); }
    50% { transform: translateX(4px); }
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
    background: rgba(0, 0, 0, 0.8);
    backdrop-filter: blur(4px);
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
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
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
    <div class="modal" id="modal"></div>
  </div>

  <div class="footer">
    <a href="https://github.com/VEXinWorks/multi-ai-orchestrator" style="color:#58a6ff;">github.com/VEXinWorks/multi-ai-orchestrator</a>
  </div>

<script>
let state = {};

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

function getBarClass(percent, type) {
  if (type === 'temp') {
    if (percent < 60) return 'temp-cool';
    if (percent < 80) return 'temp-warm';
    return 'temp-hot';
  }
  if (type === 'gpu') {
    return percent < 70 ? '' : (percent < 90 ? 'warn' : 'danger');
  }
  if (percent < 60) return '';
  if (percent < 85) return 'warn';
  return 'danger';
}

function makeSparkline(data, color, max=100) {
  if (!data || data.length < 2) return '';
  const w = 200, h = 30;
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - (Math.min(v, max) / max) * h;
    return `${x},${y}`;
  });
  // Create gradient fill below line
  const last = data.length - 1;
  const polyline = points.join(' ');
  const fillPoints = `0,${h} ${polyline} ${w},${h}`;
  return `<svg class="sparkline" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <polygon points="${fillPoints}" fill="${color}" opacity="0.15"/>
    <polyline points="${polyline}" fill="none" stroke="${color}" stroke-width="1.5"/>
    <circle cx="${(last / (data.length-1)) * w}" cy="${h - (Math.min(data[last], max)/max)*h}" r="2" fill="${color}"/>
  </svg>`;
}

function renderAiGrid(html, profiles, activeAIs, currentTopics, aiSuggestionCounts, jobs) {
  for (const [key, profile] of profiles) {
    const isBusy = activeAIs.has(key);
    const suggestionCount = aiSuggestionCounts[key] || 0;
    const currentJob = jobs.find(j => j.active_ais.includes(key));

    html.push(`<div class="ai-card ${isBusy ? 'busy' : ''}" onclick='showModal("${key}")'>`);
    html.push(`<div class="ai-header">`);
    html.push(`<div class="ai-avatar">${profile.avatar_svg}</div>`);
    html.push(`<div class="ai-info">`);
    html.push(`<div class="ai-name">${profile.emoji} ${profile.name}</div>`);
    html.push(`<div class="ai-role">${escapeHtml(profile.role)}</div>`);
    html.push(`</div></div>`);
    html.push(`<div class="ai-status">`);
    if (isBusy) {
      html.push(`<span class="busy-dot"></span> Working now${currentJob ? ` on <strong>${currentJob.name}</strong>` : ''}`);
    } else {
      html.push(`<span style="color:#6e7681;">💤 Idle</span>`);
    }
    if (suggestionCount > 0) {
      html.push(`<div style="margin-top:4px;font-size:11px;color:#8b949e;">💡 ${suggestionCount} suggestions contributed</div>`);
    }
    html.push(`</div>`);

    if (currentJob && currentJob.current_topic) {
      html.push(`<div class="ai-current-task">`);
      html.push(`<span class="label">📍 Current task</span>`);
      html.push(escapeHtml(currentJob.current_topic));
      html.push(`</div>`);
    }

    html.push(`<div style="margin-top:8px;font-size:11px;color:#6e7681;">${escapeHtml(profile.personality)}</div>`);
    html.push(`</div>`);
  }
}

function render() {
  const html = [];

  // Active AIs (computed early so AI cards can use them)
  const activeAIs = new Set();
  state.jobs.forEach(j => j.active_ais.forEach(a => activeAIs.add(a)));
  const currentTopics = {};
  state.jobs.forEach(j => {
    if (j.current_topic) currentTopics[j.name] = j.current_topic;
  });
  const aiSuggestionCounts = state.suggestions.by_ai || {};

  // === SYSTEM STATS SECTION ===
  html.push('<h2>🖥️ System</h2>');
  html.push('<div class="system-grid">');

  // CPU card
  const cpuPct = state.cpu || 0;
  const cpuLoad = state.load || {};
  html.push(`<div class="system-card">
    <div class="header-row">
      <div class="title">🔥 CPU</div>
      <div class="value" style="color:#58a6ff;">${cpuPct.toFixed(1)}%</div>
    </div>
    <div class="progress-bar">
      <div class="progress-fill ${getBarClass(cpuPct)}" style="width:${Math.min(cpuPct, 100)}%"></div>
    </div>
    ${makeSparkline(state.history.cpu, '#58a6ff')}
    <div class="stat-meta">
      <span>Load: ${cpuLoad['1min'] || 0} / ${cpuLoad['5min'] || 0} / ${cpuLoad['15min'] || 0}</span>
      <span>🌡️ ${state.cpu_temp || 0}°C</span>
    </div>
  </div>`);

  // RAM card
  const ramPct = state.ram || 0;
  html.push(`<div class="system-card">
    <div class="header-row">
      <div class="title">💾 RAM</div>
      <div class="value" style="color:#56d364;">${ramPct.toFixed(1)}%</div>
    </div>
    <div class="progress-bar">
      <div class="progress-fill ${getBarClass(ramPct)}" style="width:${Math.min(ramPct, 100)}%"></div>
    </div>
    ${makeSparkline(state.history.ram, '#56d364')}
    <div class="stat-meta">
      <span>Used: ${(ramPct * 15 / 100).toFixed(1)} GB</span>
      <span>Free: ${(15 - ramPct * 15 / 100).toFixed(1)} GB</span>
    </div>
  </div>`);

  // VRAM card
  const vram = state.vram || {};
  const vramPct = vram.percent || 0;
  html.push(`<div class="system-card">
    <div class="header-row">
      <div class="title">🎮 GPU VRAM</div>
      <div class="value" style="color:#a371f7;">${vram.used_gb || 0} GB</div>
    </div>
    <div class="progress-bar">
      <div class="progress-fill gpu ${getBarClass(vramPct, 'gpu')}" style="width:${Math.min(vramPct, 100)}%"></div>
    </div>
    ${makeSparkline(state.history.vram, '#a371f7')}
    <div class="stat-meta">
      <span>Free: ${vram.free_gb || 0} GB</span>
      <span>🌡️ ${state.gpu_temp || 0}°C</span>
    </div>
  </div>`);

  // GPU Temp card
  const gpuTemp = state.gpu_temp || 0;
  const gpuTempPct = Math.min(gpuTemp, 100);
  html.push(`<div class="system-card">
    <div class="header-row">
      <div class="title">🌡️ GPU Temp</div>
      <div class="value" style="color:#ec4899;">${gpuTemp}°C</div>
    </div>
    <div class="progress-bar">
      <div class="progress-fill ${getBarClass(gpuTempPct, 'temp')}" style="width:${gpuTempPct}%"></div>
    </div>
    ${makeSparkline(state.history.gpu_temp, '#ec4899', 100)}
    <div class="stat-meta">
      <span>${gpuTemp < 60 ? '❄️ Cool' : gpuTemp < 80 ? '🌤️ Warm' : '🔥 Hot'}</span>
      <span>Target: <70°C</span>
    </div>
  </div>`);

  // Disk card
  const diskPct = state.disk || 0;
  html.push(`<div class="system-card">
    <div class="header-row">
      <div class="title">💽 Disk</div>
      <div class="value" style="color:#d29922;">${diskPct}%</div>
    </div>
    <div class="progress-bar">
      <div class="progress-fill ${getBarClass(diskPct)}" style="width:${Math.min(diskPct, 100)}%"></div>
    </div>
    <div class="stat-meta">
      <span>Used: ${(diskPct * 389 / 100).toFixed(0)} GB</span>
      <span>Free: ${(389 - diskPct * 389 / 100).toFixed(0)} GB</span>
    </div>
  </div>`);

  // AI Memory card
  html.push(`<div class="system-card">
    <div class="header-row">
      <div class="title">🧠 AI Memory</div>
      <div class="value" style="color:#79c0ff;">${state.memory_count}</div>
    </div>
    <div class="progress-bar">
      <div class="progress-fill" style="width:${Math.min(state.memory_count/2000*100, 100)}%"></div>
    </div>
    <div class="stat-meta">
      <span>Skills: ${state.skills_count}</span>
      <span>Suggestions: ${state.suggestions.total}</span>
    </div>
  </div>`);

  html.push('</div>');

  // === TOP PROCESSES ===
  if (state.processes && state.processes.length > 0) {
    html.push('<h2>⚡ Top CPU Processes</h2>');
    html.push('<div class="processes">');
    state.processes.forEach(p => {
      html.push(`<div class="process-row">
        <span class="process-pid">${p.pid}</span>
        <span class="process-name">${escapeHtml(p.name)}</span>
        <div class="process-bar">
          <div class="process-bar-fill" style="width:${Math.min(p.cpu, 100)}%"></div>
        </div>
        <span style="min-width:60px;text-align:right;font-weight:600;color:#58a6ff;">${p.cpu.toFixed(1)}%</span>
      </div>`);
    });
    html.push('</div>');
  }

  // === AI PROFILES — separated by LOCAL vs CLOUD ===
  const localProfiles = Object.entries(state.ai_profiles).filter(([k, p]) => p.type === 'local');
  const cloudProfiles = Object.entries(state.ai_profiles).filter(([k, p]) => p.type === 'cloud');

  html.push('<h2>🖥️ LOCAL AI Models (yours)</h2>');
  html.push('<div class="ai-grid">');
  renderAiGrid(html, localProfiles, activeAIs, currentTopics, aiSuggestionCounts, state.jobs);
  html.push('</div>');

  html.push('<h2>☁️ Cloud AI Models (3 teachers)</h2>');
  html.push('<div class="ai-grid">');
  renderAiGrid(html, cloudProfiles, activeAIs, currentTopics, aiSuggestionCounts, state.jobs);
  html.push('</div>');

  // === OTHER LOCAL MODELS (installed but not in active use) ===
  if (state.other_local_models && state.other_local_models.length > 0) {
    html.push('<h2>📦 Other Installed Local Models</h2>');
    html.push('<div style="display:flex;flex-wrap:wrap;gap:8px;">');
    state.other_local_models.forEach(m => {
      html.push(`<div style="background:#161b22;border:1px solid #30363d;border-radius:6px;padding:8px 12px;font-size:12px;color:#8b949e;display:flex;gap:8px;align-items:center;">
        <span>${m.emoji}</span>
        <span style="color:#c9d1d9;font-weight:600;">${escapeHtml(m.name)}</span>
        <span>${m.size_gb} GB</span>
        <span style="color:#6e7681;font-size:10px;">${escapeHtml(m.use)}</span>
      </div>`);
    });
    html.push('</div>');
  }

  // === AI-TO-AI INTERACTIONS ===
  if (state.interactions && state.interactions.length > 0) {
    html.push('<h2>🔄 AI ↔ AI Interactions</h2>');
    state.interactions.slice(0, 6).forEach(i => {
      const speakerProfile = state.ai_profiles[i.speaker];
      const responderProfile = state.ai_profiles[i.responds_to];
      const speakerSvg = speakerProfile ? speakerProfile.avatar_svg : '';
      const responderSvg = responderProfile ? responderProfile.avatar_svg : '';
      html.push(`<div class="interaction">`);
      html.push(`<div class="ai-mini-avatar">${speakerSvg}</div>`);
      html.push(`<span class="text"><strong>${escapeHtml(i.speaker)}</strong> ↔ <strong>${escapeHtml(i.responds_to)}</strong></span>`);
      html.push(`<span class="arrow">⟶</span>`);
      html.push(`<div class="ai-mini-avatar">${responderSvg}</div>`);
      html.push(`<div class="text">${escapeHtml(i.job)}</div>`);
      html.push(`</div>`);
    });
  }

  // === ACTIVE JOBS ===
  html.push('<h2>⚙️ Active Jobs</h2>');
  if (state.jobs.length === 0) {
    html.push('<div style="color:#8b949e;padding:16px;background:#161b22;border-radius:8px;">😴 No jobs running right now. Start one with:<br><code style="color:#79c0ff;">bash /tmp/audit_all.sh &</code></div>');
  } else {
    state.jobs.forEach(j => {
      html.push('<div class="job">');
      html.push(`<div class="job-header">
        <div class="job-name"><span class="pulse"></span> <span class="emoji">⚙️</span> ${j.name}</div>
        <div class="job-meta">
          <span>PID ${j.pid}</span>
          <span>uptime ${j.etime}</span>
          <span class="job-cpu">CPU ${j.cpu_pct}%</span>
        </div>
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

  // === LATEST SUGGESTIONS ===
  html.push('<h2>💡 Latest Suggestions</h2>');
  state.suggestions.latest.slice(0, 8).forEach(s => {
    const aiProfile = state.ai_profiles[s.ai] || {};
    const aiColor = aiProfile.avatar_color || '#8b949e';
    const aiEmoji = aiProfile.emoji || '🤖';
    html.push(`<div class="suggestion">`);
    html.push(`<div class="meta">
      <span class="category-tag">${s.category}</span>
      <span class="ai-tag"><span class="ai-tag-dot" style="background:${aiColor}"></span>${aiEmoji} ${escapeHtml(s.ai)}</span>
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
        <h2>${profile.emoji} ${profile.name}</h2>
        <div style="color:#8b949e;font-size:13px;">${profile.role}</div>
      </div>
      <button class="modal-close" onclick="closeModal()">×</button>
    </div>
    <div class="modal-section">
      <h3>🧠 Personality</h3>
      <div style="color:#c9d1d9;">${escapeHtml(profile.personality)}</div>
    </div>
    <div class="modal-section">
      <h3>🎯 Specialty</h3>
      <div style="color:#c9d1d9;">${escapeHtml(profile.specialty)}</div>
    </div>
    <div class="modal-section">
      <h3>📊 Status</h3>
      <div>${isBusy ? '<span style="color:#56d364;">● Busy</span>' : '<span style="color:#8b949e;">💤 Idle</span>'}</div>
      ${currentJob ? `<div style="color:#8b949e;font-size:12px;margin-top:4px;">Currently working on: <strong>${currentJob.name}</strong></div>` : ''}
      ${currentJob && currentJob.current_topic ? `<div style="color:#c9d1d9;font-size:12px;margin-top:4px;">Topic: ${escapeHtml(currentJob.current_topic)}</div>` : ''}
    </div>
    <div class="modal-section">
      <h3>💡 Contributions</h3>
      <div style="color:#c9d1d9;">${suggestionCount} suggestions in the queue</div>
    </div>
    <div class="modal-section">
      <h3>📜 Live Output</h3>
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
    print(f"🧠 VEXinWorks AI Dashboard v3 (with system stats + sparklines)")
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