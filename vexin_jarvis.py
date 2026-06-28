#!/usr/bin/env python3
"""
vexin_jarvis.py — Personal AI Assistant (JARVIS-style) for João

Modes:
  briefing       Morning briefing: printer status, pending tasks, calendar, news
  inbox-triage   Triage: show what's important, defer the rest
  plan <goal>    Plan a task: identify steps, dependencies, time estimate
  decide <q>     Decision helper: pros/cons, second-order effects, recommendation
  brainstorm     Generate ideas on a topic
  learn <topic>  Save a learning to Odysseus memory
  reflect        End-of-day: what got done, what didn't, lessons learned

The assistant:
- Uses Odysseus memory + skills to know João's preferences
- Defers to user's tone (low-formality, direct)
- Never takes destructive actions without explicit consent
- Logs every interaction for future reference
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from urllib.parse import urlencode
from datetime import datetime

ODYSSEUS_URL = os.environ.get("ODYSSEUS_URL", "http://localhost:7000")
ADMIN_USER = "admin"

# === Boilerplate (Odysseus client) ===
def load_pw():
    for p in ["/tmp/_pw.txt", "/home/vexin/odysseus/.env"]:
        try:
            with open(p, 'rb') as f:
                content = f.read()
            if p.endswith(".env"):
                for line in content.splitlines():
                    if b'ADMIN_PASSWORD' in line and not line.startswith(b'#'):
                        return line.split(b'=', 1)[1].decode()
            return content.decode().strip()
        except FileNotFoundError:
            continue
    return None


class OdysseusClient:
    def __init__(self):
        self.cookie = None
        self.base = ODYSSEUS_URL
        self._login()

    def _request(self, method, path, data=None, params=None, timeout=60):
        url = f"{self.base}{path}"
        if params:
            url += "?" + urlencode(params)
        req = urllib.request.Request(url, method=method)
        req.add_header("Content-Type", "application/json")
        if self.cookie:
            req.add_header("Cookie", f"odysseus_session={self.cookie}")
        body = json.dumps(data).encode() if data is not None else None
        try:
            with urllib.request.urlopen(req, body, timeout=timeout) as resp:
                raw = resp.read().decode()
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return {"raw": raw}
        except urllib.error.HTTPError as e:
            return {"error": e.code, "body": e.read().decode()[:300]}
        except Exception as e:
            return {"error": str(e)}

    def _login(self):
        pw = load_pw()
        if not pw:
            return
        payload = json.dumps({"username": ADMIN_USER, "password": pw, "remember": True}).encode()
        req = urllib.request.Request(
            f"{self.base}/api/auth/login", data=payload, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            for h in resp.headers.get_all("Set-Cookie") or []:
                if "odysseus_session=" in h:
                    self.cookie = h.split("odysseus_session=", 1)[1].split(";", 1)[0]
                    break
        except Exception:
            pass

    def add_memory(self, text, source="jarvis", session_id=None):
        return self._request("POST", "/api/memory/add",
                             {"text": text, "source": source, "session_id": session_id})

    def list_skills(self):
        return self._request("GET", "/api/skills")

    def search_memory(self, query, limit=5):
        return self._request("GET", "/api/memory/search",
                             params={"q": query, "limit": limit})


# === MODES ===
def briefing(ody):
    """Morning briefing — printer, tasks, weather (placeholder), top memories."""
    print("=" * 60)
    print(f"☀️  GOOD MORNING — {datetime.now().strftime('%A, %d %B %Y')}")
    print("=" * 60)

    # 1. Printer status
    try:
        r = subprocess_run_printer_status()
        print(f"\n🖨️  PRINTER STATUS")
        for line in r.stdout.splitlines():
            print(f"   {line}")
    except Exception as e:
        print(f"\n🖨️  Printer: ({e})")

    # 2. Pending tasks (Odysseus)
    r = ody._request("GET", "/api/tasks")
    if isinstance(r, dict):
        tasks = r.get("tasks", [])
        pending = [t for t in tasks if t.get("status") not in ("completed", "cancelled")]
        print(f"\n📋 PENDING TASKS: {len(pending)}")
        for t in pending[:5]:
            print(f"   · {t.get('name')}")

    # 3. Top 3 memories (recent learnings)
    r = ody._request("GET", "/api/memory/timeline", params={"limit": 200})
    if isinstance(r, dict):
        timeline = r.get("timeline", [])
        recent_learnings = [e for e in timeline
                            if e.get("source") in ("user", "jarvis", "interactive_learn")
                            or "ai_school" in e.get("source", "")]
        if recent_learnings:
            print(f"\n🧠 RECENT LEARNINGS")
            for e in recent_learnings[:3]:
                text = e.get('text', '')[:100]
                print(f"   · {text}{'...' if len(e.get('text', '')) > 100 else ''}")

    # 4. Active skills (count)
    r = ody.list_skills()
    if isinstance(r, dict):
        total = len(r.get("skills", []))
        custom = sum(1 for s in r.get("skills", []) if s.get("source") and s.get("source") != "builtin")
        print(f"\n🛠️  SKILLS: {total} ({custom} custom)")

    # 5. School progress
    r = ody._request("GET", "/api/memory/timeline", params={"limit": 500})
    if isinstance(r, dict):
        lessons = sum(1 for e in r.get("timeline", [])
                      if e.get("source", "").startswith("ai_school_")
                      and "AI SCHOOL LESSON" in e.get("text", ""))
        print(f"\n🎓 AI SCHOOL: {lessons // 4} lessons completed out of 120")

    # 6. Quick tips based on day-of-week / context
    hour = datetime.now().hour
    if hour < 12:
        print(f"\n💡 TIP: Morning = high energy. Tackle hard problems first.")
    elif hour < 18:
        print(f"\n💡 TIP: Afternoon = admin and meetings. Save creative work for evening.")
    else:
        print(f"\n💡 TIP: Evening = creative and reflective. Plan tomorrow.")

    print()


def subprocess_run_printer_status():
    import subprocess
    return subprocess.run(['python3', '/home/vexin/projects/vexin_printer.py', 'status'],
                          capture_output=True, text=True, timeout=15)


def plan(goal, ody):
    """Plan a task: steps, dependencies, time estimate."""
    print(f"\n📋 PLAN: {goal}\n")
    prompt = f"""Plan this task for João (a 3D printing business owner in Paraguay):

Task: {goal}

Output a structured plan:
1. CLEAR GOAL (1 sentence — what does done look like?)
2. PREREQUISITES (what needs to exist or be true before starting?)
3. STEPS (numbered, each one concrete and time-bounded. Aim for 3-8 steps.)
4. DEPENDENCIES (which steps depend on others)
5. RISKS (what could go wrong + how to mitigate)
6. ESTIMATED TIME (total, with breakdown)

Be CONCISE — João prefers brief, actionable plans over essays. Use his language (low-formality English mixed with Portuguese/Spanish)."""

    r = ody._request("POST", "/api/chat",
                     {"message": prompt, "session": "plan-session"})
    if isinstance(r, dict):
        print(r.get("response", "(no response)"))
        # Save to memory
        ody.add_memory(f"PLAN: {goal}\n\n{r.get('response', '')[:1000]}",
                       source="jarvis_plan")


def decide(question, ody):
    """Decision helper: pros/cons, second-order effects, recommendation."""
    print(f"\n🤔 DECIDE: {question}\n")
    prompt = f"""Help João decide this. He's a small business owner in Paraguay, time-poor, prefers direct advice.

Question: {question}

Output:
1. KEY FACTS (3-5 facts that matter for this decision)
2. PROS (3-5, in priority order)
3. CONS (3-5, in priority order)
4. SECOND-ORDER EFFECTS (what happens AFTER you choose — 2-3 things)
5. RECOMMENDATION (1-2 sentences, your best advice)
6. WHAT WOULD CHANGE YOUR MIND (conditions that should make you reconsider)

Be CONCISE — João doesn't want essays. Be willing to commit to a recommendation."""

    r = ody._request("POST", "/api/chat",
                     {"message": prompt, "session": "decide-session"})
    if isinstance(r, dict):
        print(r.get("response", "(no response)"))
        ody.add_memory(f"DECISION: {question}\n\n{r.get('response', '')[:1000]}",
                       source="jarvis_decision")


def brainstorm(topic, ody):
    """Brainstorm ideas."""
    print(f"\n💡 BRAINSTORM: {topic}\n")
    prompt = f"""Brainstorm 10 ideas for João (3D printing business owner in Paraguay) about:

Topic: {topic}

For each idea:
- Title (short)
- 1-sentence description
- Effort (S/M/L)
- Impact (1-5 stars)
- Quickest first step

Be creative but practical. Prefer low-effort / high-impact. Mix safe bets with moonshots (mark which is which)."""

    r = ody._request("POST", "/api/chat",
                     {"message": prompt, "session": "brainstorm-session"})
    if isinstance(r, dict):
        print(r.get("response", "(no response)"))
        ody.add_memory(f"BRAINSTORM: {topic}\n\n{r.get('response', '')[:1500]}",
                       source="jarvis_brainstorm")


def learn(topic, ody):
    """Save a learning to memory."""
    print(f"\n🎓 LEARN: {topic}\n")
    text = input(f"What did you learn about '{topic}'? (1-3 sentences): ")
    if text.strip():
        result = ody.add_memory(
            f"LEARNING [{topic}]: {text.strip()}",
            source="jarvis_learn")
        print(f"\nsaved: {result}")


def reflect(ody):
    """End-of-day reflection."""
    print("\n🌙 END-OF-DAY REFLECTION\n")
    print("Quick prompts:")
    print("1. What got done today?")
    print("2. What didn't get done? Why?")
    print("3. What's the one thing to remember tomorrow?")
    print("4. Energy level: 1-10?")
    print()
    done = input("1. Done: ")
    not_done = input("2. Didn't: ")
    tomorrow = input("3. Tomorrow: ")
    energy = input("4. Energy: ")

    reflection = f"""DAILY REFLECTION ({datetime.now().strftime('%Y-%m-%d')})
✓ Done: {done}
✗ Didn't: {not_done}
→ Tomorrow: {tomorrow}
⚡ Energy: {energy}/10"""

    result = ody.add_memory(reflection, source="jarvis_reflection")
    print(f"\nsaved: {result}")


# === Main ===
def main():
    parser = argparse.ArgumentParser(description="VEXinWorks Personal Assistant")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("briefing", help="morning briefing")
    sub.add_parser("inbox-triage", help="triage your inbox")

    p_plan = sub.add_parser("plan", help="plan a task")
    p_plan.add_argument("goal", nargs="+")

    p_decide = sub.add_parser("decide", help="decision helper")
    p_decide.add_argument("question", nargs="+")

    p_brain = sub.add_parser("brainstorm", help="generate ideas")
    p_brain.add_argument("topic", nargs="+")

    p_learn = sub.add_parser("learn", help="save a learning")
    p_learn.add_argument("topic", nargs="+")

    sub.add_parser("reflect", help="end-of-day reflection")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    ody = OdysseusClient()

    if args.cmd == "briefing":
        briefing(ody)
    elif args.cmd == "inbox-triage":
        print("inbox-triage: TODO — needs email/IMAP config")
    elif args.cmd == "plan":
        plan(" ".join(args.goal), ody)
    elif args.cmd == "decide":
        decide(" ".join(args.question), ody)
    elif args.cmd == "brainstorm":
        brainstorm(" ".join(args.topic), ody)
    elif args.cmd == "learn":
        learn(" ".join(args.topic), ody)
    elif args.cmd == "reflect":
        reflect(ody)


if __name__ == "__main__":
    main()