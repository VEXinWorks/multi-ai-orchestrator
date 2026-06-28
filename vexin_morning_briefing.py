#!/usr/bin/env python3
"""
vexin_morning_briefing.py — Generate a morning summary of all autonomous work

Shows:
- What was learned (new memory entries)
- Skills created
- Pending suggestions (for human review)
- School progress
- VRAM/safety status
- Any errors

Usage: python3 vexin_morning_briefing.py
"""

import json
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


def get_ody_session():
    import re as _re
    try:
        with open("/tmp/c.txt") as f:
            content = f.read().strip()
        m = _re.search(r"odysseus_session\s+(\S+)", content)
        return m.group(1) if m else content
    except FileNotFoundError:
        return None


def call_ody(path):
    cookie = get_ody_session()
    if not cookie:
        return None
    import urllib.request
    req = urllib.request.Request(
        f"http://localhost:7000{path}",
        headers={"Cookie": f"odysseus_session={cookie}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"API error for {path}: {e}", file=sys.stderr)
        return None


def main():
    print("=" * 70)
    print(f"☀️ GOOD MORNING JOÃO — {datetime.now().strftime('%A %B %d, %Y — %H:%M')}")
    print("=" * 70)

    # 1. Memory stats
    mem = call_ody("/api/memory/timeline?limit=1500")
    if mem:
        entries = mem.get("timeline", [])
        print(f"\n📚 MEMORY: {len(entries)} total entries")
        # Count by source
        sources = Counter()
        for e in entries:
            src = e.get("source", "") or "?"
            sources[src] += 1
        print("\n  By source:")
        for s, c in sources.most_common(10):
            print(f"    {c:5} {s}")

        # Recent additions (last 24h)
        recent = [e for e in entries if (e.get("created_at", "") or "").startswith(
            datetime.now().strftime("%Y-%m-%d"))]
        if not recent:
            recent = entries[-50:]  # fallback to last 50
        print(f"\n  Last 50 entries: {len(recent)}")
        if recent:
            print("\n  Most recent memory entries:")
            for e in recent[-5:]:
                t = e.get("text", "")[:100].replace("\n", " ")
                src = e.get("source", "?")
                print(f"    [{src}] {t}...")

    # 2. Skills
    sk = call_ody("/api/skills")
    if sk:
        skills = sk.get("skills", [])
        print(f"\n🎯 SKILLS: {sk.get('count', len(skills))} total")
        # Count by category
        cats = Counter()
        for s in skills:
            cats[s.get("category", "?")] += 1
        print("\n  By category:")
        for c, n in cats.most_common():
            print(f"    {n:3} {c}")

    # 3. School progress
    print("\n📖 AI SCHOOL:")
    r = subprocess.run(
        ["python3", "/home/vexin/projects/ai_school.py", "status"],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode == 0:
        print(r.stdout)

    # 4. Pending suggestions
    sug_dir = Path("/home/vexin/projects/self_upgrade_suggestions")
    if sug_dir.exists():
        suggestions = sorted(sug_dir.glob("*.json"))
        print(f"\n💡 PENDING SUGGESTIONS (for your review): {len(suggestions)}")
        if suggestions:
            # Group by category
            cats = Counter()
            for s in suggestions:
                try:
                    d = json.loads(s.read_text())
                    cats[d.get("category", "?")] += 1
                except:
                    pass
            for cat, count in cats.most_common():
                print(f"  {count:3} {cat}")
            print("\n  Most recent (last 5):")
            for s in suggestions[-5:]:
                try:
                    d = json.loads(s.read_text())
                    print(f"    [{d.get('category')}] by {d.get('source_ai')}: {d.get('content', '')[:80]}...")
                except:
                    pass

    # 5. VRAM + system status
    print("\n💻 SYSTEM STATUS:")
    try:
        with open("/sys/class/drm/card1/device/mem_info_vram_used") as f:
            vram_used = int(f.read()) / 1e9
        with open("/sys/class/drm/card1/device/mem_info_vram_total") as f:
            vram_total = int(f.read()) / 1e9
        print(f"  VRAM: {vram_used:.2f} GB / {vram_total:.2f} GB ({vram_total - vram_used:.2f} GB free)")
    except:
        pass
    r = subprocess.run(["free", "-h"], capture_output=True, text=True)
    print(f"\n  RAM:\n{r.stdout.split(chr(10))[1]}")
    r = subprocess.run(["df", "-h", "/home"], capture_output=True, text=True)
    lines = r.stdout.split("\n")
    if len(lines) > 1:
        print(f"  Disk: {lines[1]}")

    # 6. What's running
    print("\n🔄 RUNNING PROCESSES:")
    r = subprocess.run(["ps", "-eo", "pid,etime,cmd"], capture_output=True, text=True)
    interesting = []
    for line in r.stdout.split("\n"):
        if any(k in line for k in ["ai_school", "vexin_self_upgrade", "upgrade_self", "cpu_teacher", "ollama serve"]):
            interesting.append(line)
    for line in interesting[:10]:
        print(f"  {line.strip()}")

    # 7. Recent errors (from monitor)
    print("\n⚠️  ALERTS (last 24h):")
    if Path("/tmp/monitor.log").exists():
        log = Path("/tmp/monitor.log").read_text()
        # Find WARNING/FAILED/ERROR lines
        alerts = [l for l in log.split("\n") if any(w in l for w in ["WARNING", "FAILED", "killed"])]
        if alerts:
            for a in alerts[-10:]:
                print(f"  {a}")
        else:
            print("  ✓ No alerts")

    # 8. Next steps
    print("\n" + "=" * 70)
    print("📋 WHAT TO DO NEXT:")
    print("=" * 70)
    print("  1. Review pending suggestions: /home/vexin/projects/self_upgrade_suggestions/")
    print("  2. Check school log: tail -f /tmp/school-batch-night.log")
    print("  3. Check monitor log: tail -f /tmp/monitor.log")
    print("  4. Talk to AI: python3 /home/vexin/projects/vexin_talk.py")
    print("  5. Run self-upgrade: python3 /home/vexin/projects/vexin_self_upgrade.py upgrade-self")
    print("=" * 70)


if __name__ == "__main__":
    main()