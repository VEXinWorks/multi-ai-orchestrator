#!/usr/bin/env python3
"""
VEXinWorks Multi-AI Orchestrator
Coordinates 3 cloud AIs + local Ollama models + local agents.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
import socket
import subprocess
from functools import wraps
from urllib.parse import urlencode


# === SAFETY: HTTP retry with exponential backoff ===
def http_retry(timeout=15, max_retries=3, backoff_base=1.5):
    """Decorator: retry HTTP calls on transient failures with exponential backoff."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            delay = 0.5
            last_err = None
            for attempt in range(max_retries + 1):
                try:
                    kwargs['timeout'] = min(timeout * (1 + attempt), timeout * 3)
                    return fn(*args, **kwargs)
                except (urllib.error.URLError, socket.timeout, ConnectionError, TimeoutError) as e:
                    last_err = e
                    if attempt == max_retries:
                        break
                    time.sleep(delay)
                    delay *= backoff_base
            raise last_err
        return wrapper
    return deco


# === SAFETY: VRAM guard for local model loading ===
def safe_load_local_model(model_name, max_vram_gb=10.0):
    """Refuse to load a local model if it would exceed VRAM budget.
    Returns True if safe to load, False if rejected with reason."""
    current = subprocess.run(['ollama', 'ps'], capture_output=True, text=True)
    used_gb = 0.0
    for line in current.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[0] != 'NAME':
            try:
                # SIZE column like "5.3 GB" - parse it
                size_str = parts[2] if 'GB' in parts[2] else parts[1]
                if 'GB' in size_str:
                    used_gb += float(size_str.replace('GB', '').strip())
            except (ValueError, IndexError):
                pass

    # Approximate model size (in GB) — could read from ollama list
    size_map = {
        'llama3.1:8b': 5.3, 'llama3.2:3b': 2.6, 'llama3.2:vision:11b': 8.5,
        'qwen2.5-coder:7b': 5.3, 'deepseek-r1:8b': 5.5,
        'llava:7b': 5.3, 'moondream': 1.7, 'nomic-embed-text': 0.3,
    }
    new_size = size_map.get(model_name, 5.0)

    if used_gb + new_size > max_vram_gb:
        print(f"[!] REFUSED to load {model_name} ({new_size} GB): would exceed {max_vram_gb} GB "
              f"(current: {used_gb:.1f} GB used). Unload other models first via 'ollama stop'.",
              file=sys.stderr)
        return False
    return True


# === SAFETY: disk space check ===
def check_disk_free(path="/home", min_free_gb=50):
    """Refuse operations that would consume too much disk space."""
    s = os.statvfs(path)
    free_gb = (s.f_bavail * s.f_frsize) / (1024 ** 3)
    if free_gb < min_free_gb:
        print(f"[!] REFUSED: only {free_gb:.1f} GB free at {path} (min: {min_free_gb} GB)",
              file=sys.stderr)
        return False
    return True

ODYSSEUS_URL = os.environ.get("ODYSSEUS_URL", "http://localhost:7000")
ADMIN_USER = "admin"
CLOUD_ENDPOINT_ID = "d2947ec9"
LOCAL_ENDPOINT_ID = "262a8872"

CLOUD_AIS = {
    "glm-5.2": {"model": "glm-5.2", "endpoint": CLOUD_ENDPOINT_ID,
                "specialty": "research, analysis, broad knowledge",
                "strengths": ["deep research", "summarization", "broad reasoning"]},
    "minimax-m3": {"model": "minimax-m3", "endpoint": CLOUD_ENDPOINT_ID,
                "specialty": "general chat, conversational, agentic workflows",
                "strengths": ["natural conversation", "tool use", "agentic loops"]},
    "nemotron-3-ultra": {"model": "nemotron-3-ultra", "endpoint": CLOUD_ENDPOINT_ID,
                "specialty": "code generation, technical reasoning, math",
                "strengths": ["code review", "math", "technical docs", "debugging"]},
}

LOCAL_AIS = {
    "llama3.1:8b": "primary local chat",
    "llama3.2:3b": "fast lightweight",
    "qwen2.5-coder:7b": "code generation local",
    "llava:7b": "vision local",
    "nomic-embed-text": "embeddings",
}

ROUTING_RULES = [
    (["code review", "review this code", "is this code", "code quality",
      "bug in", "debug", "refactor", "rewrite this"],
     "nemotron-3-ultra", "code tasks go to NVIDIA Nemotron"),
    (["research", "find out", "what is the latest", "investigate",
      "compare", "analyze", "deep dive"],
     "glm-5.2", "research/analysis tasks go to GLM"),
    (["chat", "tell me about", "explain", "summarize",
      "draft", "write me", "help me with"],
     "minimax-m3", "general chat tasks go to default"),
    (["kimi", "large", "huge context", "very long"],
     "minimax-m3", "large-context tasks go to minimax-m3"),
]


def load_pw():
    for p in ["/tmp/_pw.txt", "/home/vexin/odysseus/.env"]:
        try:
            with open(p, 'rb') as f:
                content = f.read()
            if p.endswith(".env"):
                for line in content.splitlines():
                    if b'ADMIN_PASSWORD' in line and not line.startswith(b'#'):
                        return line.split(b'=', 1)[1].decode()
            else:
                return content.decode().strip()
        except FileNotFoundError:
            continue
    return None


class OdysseusClient:
    def __init__(self):
        self.cookie = None
        self.base = ODYSSEUS_URL
        self._login()

    def _request(self, method, path, data=None, params=None, timeout=120):
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
            return {"error": e.code, "body": e.read().decode()[:500]}
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
        except Exception as e:
            print(f"[!] login failed: {e}", file=sys.stderr)

    def create_session(self, name, model, endpoint_id):
        body = urlencode({"name": name, "model": model, "endpoint_id": endpoint_id}).encode()
        req = urllib.request.Request(
            f"{self.base}/api/session", data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        if self.cookie:
            req.add_header("Cookie", f"odysseus_session={self.cookie}")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            return {"error": str(e)}

    def chat(self, message, session_id, timeout=120):
        return self._request("POST", "/api/chat",
                             {"message": message, "session": session_id}, timeout=timeout)

    def add_memory(self, text, source="multi_ai_orchestrator", session_id=None):
        return self._request("POST", "/api/memory/add",
                             {"text": text, "source": source, "session_id": session_id})

    def add_skill(self, name, description, category, procedure, pitfalls, verification):
        skill = {
            "name": name,
            "description": description[:200],
            "category": category,
            "procedure": procedure if isinstance(procedure, list) else [procedure],
            "pitfalls": pitfalls if isinstance(pitfalls, list) else [pitfalls],
            "verification": verification if isinstance(verification, list) else [verification],
            "status": "active",
            "version": "1.0",
            "source": "multi_ai_orchestrator",
        }
        return self._request("POST", "/api/skills/add", skill)


def classify_task(task_text):
    task_lower = task_text.lower()
    for patterns, ai_name, reason in ROUTING_RULES:
        if any(p in task_lower for p in patterns):
            return ai_name, reason
    return "minimax-m3", "default routing"


def delegate(task, ody, prefer_local=False, save_to_memory=True):
    ai_name, reason = classify_task(task)
    if prefer_local:
        ai_name = "llama3.1:8b"
        reason = "user requested local"

    if ai_name in CLOUD_AIS:
        cfg = CLOUD_AIS[ai_name]
        endpoint_id = cfg["endpoint"]
        model = cfg["model"]
        kind = "cloud"
    else:
        endpoint_id = LOCAL_ENDPOINT_ID
        model = ai_name
        kind = "local"

    print(f"[→ {ai_name}] ({kind}): {reason}", file=sys.stderr)

    session = ody.create_session(f"orch-{ai_name}-{int(time.time())}", model, endpoint_id)
    sid = session.get("id") if isinstance(session, dict) else None
    if not sid:
        return {"error": "no session", "ai": ai_name, "raw": session}

    start = time.time()
    result = ody.chat(task, sid)
    dt = time.time() - start
    response = result.get("response", "(no response)") if isinstance(result, dict) else str(result)

    if save_to_memory and response and not response.startswith("("):
        try:
            ody.add_memory(
                f"[{ai_name}] Q: {task[:200]}... A: {response[:300]}...",
                source=f"orchestrator_{ai_name}")
        except Exception:
            pass

    return {"ai": ai_name, "reason": reason, "task": task,
            "response": response, "elapsed_s": round(dt, 2)}


def consensus(question, ody):
    answers = {}
    for ai_name in CLOUD_AIS:
        print(f"  asking {ai_name}...", file=sys.stderr)
        result = delegate(question, ody, save_to_memory=False)
        answers[ai_name] = {"response": result.get("response", "(error)"),
                            "elapsed_s": result.get("elapsed_s")}
    return answers


def self_improve(ody):
    print("\n=== SELF-IMPROVEMENT CYCLE ===\n", file=sys.stderr)
    agent_path = "/home/vexin/projects/vexin_agent.py"
    try:
        with open(agent_path) as f:
            current_code = f.read()
    except FileNotFoundError:
        return {"error": f"can't read {agent_path}"}

    print("[1/3] Querying 3 cloud AIs for improvements...", file=sys.stderr)
    improvements = {}
    for ai_name in CLOUD_AIS:
        prompt = (
            f"You are {ai_name}. Review this Python agent script and suggest 3 specific, "
            f"small improvements that would make it more robust. Be CONCISE. "
            f"For each improvement: (1) what to change, (2) why, (3) exact code snippet.\n\n"
            f"```python\n{current_code[:3000]}\n```")
        result = delegate(prompt, ody, save_to_memory=False)
        improvements[ai_name] = result.get("response", "(empty)")

    print("[2/3] Storing improvement proposals in memory...", file=sys.stderr)
    summary = "Self-improvement cycle proposals (2026-06-28):\n\n"
    for ai_name, text in improvements.items():
        summary += f"=== {ai_name} ===\n{text[:600]}\n\n"
    ody.add_memory(summary, source="self_improvement_proposals")

    print("[3/3] Manual review recommended. Run 'show-improvements' to view.", file=sys.stderr)
    return improvements


def status(ody):
    print("=" * 60)
    print("MULTI-AI ORCHESTRATOR — SYSTEM STATUS")
    print("=" * 60)
    print("\n[Cloud AIs]")
    for name, cfg in CLOUD_AIS.items():
        print(f"  {name}: {cfg['specialty']}")
        print(f"    strengths: {', '.join(cfg['strengths'])}")

    print("\n[Local Models]")
    r = subprocess.run(['ollama', 'list'], capture_output=True, text=True)
    for line in r.stdout.splitlines()[1:]:
        if line.strip():
            print(f"  {line}")

    print("\n[Odysseus]")
    r = subprocess.run(['curl', '-sS', '-b', '/tmp/c.txt',
                        'http://localhost:7000/api/memory/timeline?limit=1'],
                       capture_output=True, text=True, timeout=10)
    try:
        data = json.loads(r.stdout)
        print(f"  memory entries: {data.get('total', '?')}")
    except Exception:
        print("  memory: (couldn't read)")

    r = subprocess.run(['curl', '-sS', '-b', '/tmp/c.txt',
                        'http://localhost:7000/api/skills'],
                       capture_output=True, text=True, timeout=10)
    try:
        data = json.loads(r.stdout)
        skills = data.get('skills', [])
        custom = [s for s in skills if s.get('source') and s.get('source') != 'builtin']
        print(f"  skills: {len(skills)} total, {len(custom)} custom")
    except Exception:
        print("  skills: (couldn't read)")


def main():
    parser = argparse.ArgumentParser(description="VEXinWorks multi-AI orchestrator")
    sub = parser.add_subparsers(dest="cmd")

    p_del = sub.add_parser("delegate", help="send task to best AI")
    p_del.add_argument("task")
    p_del.add_argument("--local", action="store_true")

    p_cons = sub.add_parser("consensus", help="ask all 3 cloud AIs")
    p_cons.add_argument("question")

    sub.add_parser("self-improve", help="AI rewrites local agents")
    sub.add_parser("show-improvements", help="view recent improvement proposals")
    sub.add_parser("status", help="show AI states")
    sub.add_parser("serve", help="queue listener")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    ody = OdysseusClient()

    if args.cmd == "delegate":
        result = delegate(args.task, ody, prefer_local=args.local)
        print(f"\n[{result['ai']} | {result['elapsed_s']}s | {result['reason']}]")
        print(result.get("response", "(no response)"))
    elif args.cmd == "consensus":
        answers = consensus(args.question, ody)
        for ai_name, data in answers.items():
            print(f"\n=== {ai_name} ({data['elapsed_s']}s) ===")
            print(data["response"][:800])
    elif args.cmd == "self-improve":
        result = self_improve(ody)
        if result:
            for ai_name, text in result.items():
                print(f"\n=== {ai_name} ===")
                print(text[:800])
    elif args.cmd == "show-improvements":
        r = subprocess.run(['curl', '-sS', '-b', '/tmp/c.txt',
                            'http://localhost:7000/api/memory/search?q=self_improvement'],
                           capture_output=True, text=True, timeout=10)
        print(r.stdout[:3000])
    elif args.cmd == "status":
        status(ody)
    elif args.cmd == "serve":
        print("queue listener not yet implemented", file=sys.stderr)


if __name__ == "__main__":
    main()
