#!/usr/bin/env python3
"""
VEXinWorks Local Agent Runner

A self-extending AI agent that:
1. Uses Ollama (llama3.1:8b) for local inference
2. Talks to Odysseus at localhost:7000 for memory, skills, and project context
3. Can be invoked from CLI, from Hermes (via delegate_task), or from a queue
4. Self-extends: can write its own tools/skills into Odysseus

Usage:
  python3 vexin_agent.py "what's the printer status?"                    # single-shot
  python3 vexin_agent.py --task add-skill name=X description=Y ...      # skill creation
  python3 vexin_agent.py --task recall-memory query="vexinworks"          # RAG query
  python3 vexin_agent.py --serve                                          # queue listener
  python3 vexin_agent.py --self-test                                      # end-to-end test
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
import socket
from functools import wraps
from urllib.parse import urlencode

# === SAFETY: HTTP retry with exponential backoff ===
def http_retry(timeout=15, max_retries=3, backoff_base=1.5):
    """Decorator: retry HTTP calls on URLError/socket.timeout with exponential backoff.
    Caps total wait at ~10s. Never retries on HTTP 4xx (those are caller errors)."""
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


# === CONFIG ===
ODYSSEUS_URL = os.environ.get("ODYSSEUS_URL", "http://localhost:7000")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
PRIMARY_MODEL = os.environ.get("PRIMARY_MODEL", "llama3.1:8b")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")

# Model selection by task type — each task picks the right model for the job
MODEL_BY_TASK = {
    "chat": "llama3.1:8b",                # general conversation
    "code": "qwen2.5-coder:7b",          # code review, generation, debugging
    "vision": "llava:7b",                 # image analysis, screenshots, webcam
    "reason": "llama3.1:8b",              # planning (deepseek too slow for interactive)
    "fast": "llama3.2:3b",                # parallel sessions, quick answers
    "embed": "nomic-embed-text",          # embeddings/RAG
}

# Cloud models (via Ollama Cloud endpoint) — use when local models are insufficient
CLOUD_MODEL_ALIASES = {
    "nemotron": "nemotron-3-super",
    "kimi": "kimi-k2.5",
    "deepseek-pro": "deepseek-v4-pro",
    "big-code": "qwen3-coder:480b",
    "big-reason": "deepseek-v3.1:671b",
}
ADMIN_USER = os.environ.get("ODY_USER", "admin")

# === HELPERS ===
def load_admin_pw():
    """Read admin password from the .env file (no env-var exposure)."""
    env_path = os.path.expanduser("~/odysseus/.env")
    if not os.path.exists(env_path):
        # try alternate paths
        for p in ["/home/vexin/odysseus/.env"]:
            if os.path.exists(p):
                env_path = p
                break
    try:
        with open(env_path) as f:
            for line in f:
                if line.startswith("ODYSSEUS_ADMIN_PASSWORD="):
                    return line.strip().split("=", 1)[1]
    except Exception as e:
        print(f"[!] could not read {env_path}: {e}", file=sys.stderr)
    return None

class OdysseusClient:
    """Talks to Odysseus's REST API. Holds session cookie."""

    def __init__(self, base_url=ODYSSEUS_URL):
        self.base = base_url.rstrip("/")
        self.cookie = None
        self._login()

    def _request(self, method, path, data=None, params=None, stream=False, timeout=60):
        url = f"{self.base}{path}"
        if params:
            url += "?" + urlencode(params)
        req = urllib.request.Request(url, method=method)
        req.add_header("Content-Type", "application/json")
        if self.cookie:
            req.add_header("Cookie", f"odysseus_session={self.cookie}")
        body = None
        if data is not None:
            body = json.dumps(data).encode()
        try:
            with urllib.request.urlopen(req, body, timeout=timeout) as resp:
                if stream:
                    return resp
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
        pw = load_admin_pw()
        if not pw:
            print("[!] No admin password found, running in unauthenticated mode")
            return
        result = self._request("POST", "/api/auth/login",
                               {"username": ADMIN_USER, "password": pw, "remember": True})
        if isinstance(result, dict) and result.get("ok"):
            # Cookie set via response headers normally; for urllib we need to capture
            # simpler: re-do request capturing cookie
            self._capture_cookie()
            print(f"[+] Logged into Odysseus as {ADMIN_USER}")
        else:
            print(f"[!] Login failed: {result}", file=sys.stderr)

    def _capture_cookie(self):
        """Make a fresh request and grab the Set-Cookie header."""
        pw = load_admin_pw()
        if not pw:
            return
        url = f"{self.base}/api/auth/login"
        body = json.dumps({"username": ADMIN_USER, "password": pw, "remember": True}).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            for header in resp.headers.get_all("Set-Cookie") or []:
                if "odysseus_session=" in header:
                    self.cookie = header.split("odysseus_session=", 1)[1].split(";", 1)[0]
                    break
        except Exception as e:
            print(f"[!] Cookie capture failed: {e}", file=sys.stderr)

    # === MEMORY ===
    def add_memory(self, text, source="local_agent", session_id=None):
        return self._request("POST", "/api/memory/add",
                             {"text": text, "source": source, "session_id": session_id})

    def recall_memories(self, limit=10):
        return self._request("GET", "/api/memory/timeline", params={"limit": limit})

    def search_memories(self, query, limit=10):
        return self._request("GET", "/api/memory/search", params={"q": query, "limit": limit})

    # === SKILLS ===
    def list_skills(self):
        """Returns ALL skills (built-in + user-created)."""
        result = self._request("GET", "/api/skills")
        if isinstance(result, dict) and "skills" in result:
            return {"builtin": result["skills"], "custom": [s for s in result["skills"] if s.get('source') != 'builtin']}
        # Fallback to builtin only
        return self._request("GET", "/api/skills/builtin")

    def add_skill(self, name, description, category, procedure, pitfalls, verification, **kwargs):
        skill = {
            "name": name,
            "description": description[:200],
            "category": category,
            "procedure": procedure if isinstance(procedure, list) else [procedure],
            "pitfalls": pitfalls if isinstance(pitfalls, list) else [pitfalls],
            "verification": verification if isinstance(verification, list) else [verification],
            "status": "active",
            "version": "1.0",
            "source": "local_agent_runner",
            **kwargs,
        }
        return self._request("POST", "/api/skills/add", skill)

    # === CHAT ===
    def ensure_session(self, name="vexin-local-agent", model=PRIMARY_MODEL):
        """Create a session if it doesn't exist."""
        existing = self._request("GET", "/api/sessions")
        if isinstance(existing, list):
            for s in existing:
                if s.get("name") == name:
                    return s.get("id")
        # Create new — Odysseus uses form-encoded for /api/session
        # Need endpoint_id or endpoint_url; we have the local Ollama endpoint registered as 262a8872
        endpoint_id = os.environ.get("ODY_ENDPOINT_ID", "262a8872")
        body = urlencode({
            "name": name,
            "model": model,
            "endpoint_id": endpoint_id,
        }).encode()
        req = urllib.request.Request(
            f"{self.base}/api/session",
            data=body,
            method="POST",
        )
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        if self.cookie:
            req.add_header("Cookie", f"odysseus_session={self.cookie}")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return data.get("id")
        except urllib.error.HTTPError as e:
            return None
        except Exception as e:
            return None

    def chat(self, message, session_id=None, model=PRIMARY_MODEL):
        sid = session_id or self.ensure_session()
        if not sid:
            return {"error": "could not create session"}
        return self._request("POST", "/api/chat",
                             {"message": message, "session": sid},
                             timeout=180)

    # === PERSONAL DOCS / RAG ===
    def reload_personal_docs(self):
        return self._request("POST", "/api/personal/reload", {})

    def list_personal_docs(self):
        return self._request("GET", "/api/personal")

    # === TASKS ===
    def list_tasks(self):
        return self._request("GET", "/api/tasks")

class OllamaClient:
    """Direct Ollama API calls (bypass Odysseus for raw inference)."""

    def __init__(self, base_url=OLLAMA_URL):
        self.base = base_url.rstrip("/")

    def generate(self, prompt, model=PRIMARY_MODEL, system=None, stream=False):
        body = {"model": model, "prompt": prompt, "stream": stream}
        if system:
            body["system"] = system
        req = urllib.request.Request(
            f"{self.base}/api/generate",
            data=json.dumps(body).encode(),
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                if stream:
                    return resp
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return {"error": e.code, "body": e.read().decode()[:500]}

    def embed(self, text, model=EMBED_MODEL):
        req = urllib.request.Request(
            f"{self.base}/api/embeddings",
            data=json.dumps({"model": model, "prompt": text}).encode(),
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return {"error": e.code, "body": e.read().decode()[:500]}

    def list_models(self):
        try:
            with urllib.request.urlopen(f"{self.base}/api/tags", timeout=5) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            return {"error": str(e)}

# === TASK HANDLERS ===
def task_chat(args, ody, oll):
    """Single-shot chat: prompt → Ollama (with memory context) → answer."""
    # Recall relevant memories
    print("[*] Recalling memories...", file=sys.stderr)
    memories = ody.recall_memories(limit=5)
    context = ""
    if isinstance(memories, dict) and memories.get("timeline"):
        context = "\n\n".join(
            m.get("text", m.get("content", str(m)))
            for m in memories["timeline"][:5]
            if isinstance(m, dict)
        )

    system_prompt = (
        "You are the VEXinWorks local AI agent, running on João's Ubuntu workstation. "
        "Use the recalled memories below as background context when relevant. "
        "Keep answers concise and actionable. Reply in English unless João writes in another language.\n\n"
        f"## Recalled memories:\n{context or '(none yet)'}"
    )

    print(f"[*] Calling {PRIMARY_MODEL} via Ollama...", file=sys.stderr)
    result = oll.generate(args.prompt, system=system_prompt)
    if isinstance(result, dict) and "response" in result:
        print(result["response"])
    else:
        print(json.dumps(result, indent=2)[:1000], file=sys.stderr)
        sys.exit(1)

def task_recall_memory(args, ody, oll):
    """Query memories by free-text."""
    query = getattr(args, "query", "")
    if not query:
        print("[!] --query required", file=sys.stderr)
        sys.exit(2)
    result = ody.search_memories(query=query, limit=10)
    print(json.dumps(result, indent=2))

def task_add_skill(args, ody, oll):
    """Add a new skill to Odysseus from CLI args."""
    fields = {
        "name": args.name,
        "description": args.description,
        "category": args.category or "general",
        "procedure": (args.procedure or "").split("|") if args.procedure else ["(no procedure)"],
        "pitfalls": (args.pitfalls or "").split("|") if args.pitfalls else [],
        "verification": (args.verification or "").split("|") if args.verification else [],
    }
    if not fields["name"] or not fields["description"]:
        print("[!] --name and --description required", file=sys.stderr)
        sys.exit(2)
    result = ody.add_skill(**fields)
    print(json.dumps(result, indent=2))

def task_add_memory(args, ody, oll):
    """Add a memory entry from CLI args."""
    if not args.text:
        print("[!] --text required", file=sys.stderr)
        sys.exit(2)
    result = ody.add_memory(args.text, source=args.source or "local_agent_cli")
    print(json.dumps(result, indent=2))

def task_serve(args, ody, oll):
    """Run as a queue listener. Reads tasks from ~/.vexin_agent/queue/*.json."""
    queue_dir = os.path.expanduser("~/.vexin_agent/queue")
    done_dir = os.path.join(queue_dir, "done")
    os.makedirs(queue_dir, exist_ok=True)
    os.makedirs(done_dir, exist_ok=True)
    print(f"[*] Serving on {queue_dir} (poll every {args.poll}s, Ctrl-C to stop)")
    while True:
        try:
            files = sorted(f for f in os.listdir(queue_dir) if f.endswith(".json"))
            for fname in files:
                fpath = os.path.join(queue_dir, fname)
                try:
                    with open(fpath) as f:
                        task = json.load(f)
                    print(f"[*] Processing {fname}: {task.get('type', '?')}")
                    result = handle_task(task, ody, oll)
                    out = {"input": task, "result": result, "processed_at": time.time()}
                    with open(os.path.join(done_dir, fname), "w") as f:
                        json.dump(out, f, indent=2)
                    os.remove(fpath)
                    print(f"[+] Done {fname}")
                except Exception as e:
                    print(f"[!] Error on {fname}: {e}", file=sys.stderr)
                    # move to dead letter
                    err_dir = os.path.join(queue_dir, "errors")
                    os.makedirs(err_dir, exist_ok=True)
                    os.rename(fpath, os.path.join(err_dir, fname + ".err"))
        except KeyboardInterrupt:
            print("\n[*] Stopped.")
            break
        time.sleep(args.poll)

def task_self_test(args, ody, oll):
    """End-to-end self test of all capabilities."""
    print("=" * 60)
    print("VEXIN AGENT — SELF TEST")
    print("=" * 60)

    print("\n[1/5] Ollama models:")
    models = oll.list_models()
    if isinstance(models, dict) and "models" in models:
        for m in models["models"][:5]:
            print(f"  - {m.get('name')} ({m.get('size', 0) // 1_000_000} MB)")
    else:
        print(f"  ERR: {models}")

    print("\n[2/5] Memory recall (last 3):")
    mems = ody.recall_memories(limit=3)
    if isinstance(mems, dict):
        for m in mems.get("timeline", [])[:3]:
            if isinstance(m, dict):
                txt = m.get("text", m.get("content", str(m)))[:80]
                print(f"  - {txt}")

    print("\n[3/5] Skills catalog:")
    skills = ody.list_skills()
    if isinstance(skills, dict):
        all_skills = skills.get("builtin", [])
        custom = [s for s in all_skills if s.get('source') and s.get('source') != 'builtin']
        print(f"  Builtins: {len(all_skills)}, Custom (user/agent added): {len(custom)}")
        for s in custom[:8]:
            print(f"  - {s.get('name')}: {s.get('description', '')[:60]}")

    print("\n[4/5] Personal docs:")
    docs = ody.list_personal_docs()
    if isinstance(docs, dict):
        files = docs.get("files", [])
        print(f"  Indexed files: {len(files)}")
        for f in files[:5]:
            print(f"  - {f.get('name')} ({f.get('size', 0) // 1024} KB)")

    print("\n[5/5] Single-shot chat test:")
    start = time.time()
    result = ody.chat("In one sentence: what's João's business called and what does it do?")
    dt = time.time() - start
    if isinstance(result, dict) and "response" in result:
        print(f"  ({dt:.1f}s) {result['response'][:200]}")
    else:
        print(f"  ERR: {result}")

    print("\n" + "=" * 60)
    print("SELF TEST COMPLETE")
    print("=" * 60)

def handle_task(task, ody, oll):
    """Route a queue task dict to the right handler."""
    t = task.get("type", "")
    if t == "chat":
        return oll.generate(task["prompt"], system=task.get("system", ""))
    elif t == "memory":
        return ody.add_memory(task["text"], source=task.get("source", "queue"))
    elif t == "skill":
        return ody.add_skill(**{k: v for k, v in task.items() if k != "type"})
    elif t == "recall":
        return ody.search_memories(query=task["query"], limit=task.get("limit", 10))
    elif t == "embed":
        return oll.embed(task["text"])
    elif t == "self_test":
        task_self_test(None, ody, oll)
        return {"ok": True}
    else:
        return {"error": f"unknown task type: {t}"}

# === MAIN ===
def main():
    parser = argparse.ArgumentParser(description="VEXinWorks local AI agent")
    sub = parser.add_subparsers(dest="cmd")

    p_chat = sub.add_parser("chat", help="single-shot chat")
    p_chat.add_argument("prompt", help="what to ask the local model")

    p_recall = sub.add_parser("recall", help="query memories")
    p_recall.add_argument("--query", "-q", required=True)

    p_addmem = sub.add_parser("remember", help="add a memory")
    p_addmem.add_argument("--text", "-t", required=True)
    p_addmem.add_argument("--source", "-s", default="local_agent_cli")

    p_skill = sub.add_parser("add-skill", help="add a skill")
    p_skill.add_argument("--name", required=True)
    p_skill.add_argument("--description", required=True)
    p_skill.add_argument("--category", default="general")
    p_skill.add_argument("--procedure", default="")
    p_skill.add_argument("--pitfalls", default="")
    p_skill.add_argument("--verification", default="")

    sub.add_parser("serve", help="run as queue listener").add_argument("--poll", type=int, default=2)
    sub.add_parser("self-test", help="end-to-end self test")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    ody = OdysseusClient()
    oll = OllamaClient()

    handlers = {
        "chat": task_chat,
        "recall": task_recall_memory,
        "remember": task_add_memory,
        "add-skill": task_add_skill,
        "serve": task_serve,
        "self-test": task_self_test,
    }
    handlers[args.cmd](args, ody, oll)

if __name__ == "__main__":
    main()