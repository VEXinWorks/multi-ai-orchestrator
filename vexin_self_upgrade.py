#!/usr/bin/env python3
"""
vexin_self_upgrade.py — Self-improvement loop with multi-AI collaboration.

Workflow:
  1. Pick a task the local AI failed at
  2. Get suggestions from 3 cloud AIs (GLM-5.2, minimax-m3, nemotron-3-ultra)
  3. Local AI retries with cloud feedback
  4. If success, save the new knowledge to memory + skills
  5. If still failing, search the web for solutions
  6. Generate self-rewrite patches (NEVER auto-applied - diff + flag for human)

Commands:
  ./vexin_self_upgrade.py task "your task"     # full loop
  ./vexin_self_upgrade.py teach "lesson text"  # ask 3 cloud AIs to teach local
  ./vexin_self_upgrade.py research "topic"     # web search for AI agent patterns
  ./vexin_self_upgrade.py code-review FILE     # 3 AIs review code
  ./vexin_self_upgrade.py upgrade-self         # scan + improve all local agents
  ./vexin_self_upgrade.py discuss "topic"      # multi-AI discussion on a topic
  ./vexin_self_upgrade.py status               # show all suggestions queue
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

# Endpoints
LOCAL_ENDPOINT = "262a8872"
CLOUD_ENDPOINT = "d2947ec9"
ODYSSEUS_URL = "http://localhost:7000"
COOKIE_FILE = "/tmp/c.txt"
PROJECTS_DIR = Path("/home/vexin/projects")

# Load model config (always check vexin_model_config.yaml)
import yaml as _yaml2
_CONFIG_PATH = PROJECTS_DIR / "vexin_model_config.yaml"
try:
    with open(_CONFIG_PATH) as _f:
        _CFG = _yaml2.safe_load(_f)
    LOCAL_FORBIDDEN = _CFG["LOCAL_MODELS"].get("do_not_suggest_local", [])
    CLOUD_TEACHERS = _CFG["CLOUD_MODELS"].get("cloud_teachers_used_by_school", [])
except Exception:
    LOCAL_FORBIDDEN = ["gpt-oss:120b", "mistral-large-3:675b", "devstral-2:123b",
                       "qwen3-coder:480b", "qwen3.5:397b", "deepseek-v3.1:671b"]
    CLOUD_TEACHERS = ["glm-5.2", "minimax-m3", "nemotron-3-ultra"]

# Cloud AIs (use base model names, not :cloud suffix)
# Always pull from config to stay in sync with school teachers
CLOUD_AIS = []
for teacher in CLOUD_TEACHERS:
    if "glm" in teacher.lower():
        CLOUD_AIS.append({"name": "GLM-5.2", "model": teacher, "personality": "general"})
    elif "minimax" in teacher.lower():
        CLOUD_AIS.append({"name": "minimax-m3", "model": teacher, "personality": "chat"})
    elif "nemotron" in teacher.lower():
        CLOUD_AIS.append({"name": "nemotron-3-ultra", "model": teacher, "personality": "reasoning"})
    else:
        CLOUD_AIS.append({"name": teacher, "model": teacher, "personality": "general"})

# Local AI (for retry with feedback)
LOCAL_AI = "llama3.1:8b"


def is_model_safe(model):
    """Check if a model fits in our 16GB VRAM."""
    if model in LOCAL_FORBIDDEN:
        return False, f"{model} exceeds 16GB VRAM"
    return True, "OK"

# Suggestions storage
SUGGESTIONS_DIR = Path("/home/vexin/projects/self_upgrade_suggestions")
SUGGESTIONS_DIR.mkdir(parents=True, exist_ok=True)


def get_ody_session():
    """Get Odysseus session cookie."""
    import urllib.request
    import urllib.error

    try:
        with open(COOKIE_FILE) as f:
            content = f.read().strip()
        m = re.search(r'odysseus_session\s+(\S+)', content)
        return m.group(1) if m else content
    except FileNotFoundError:
        pass

    # Login
    pw = Path("/tmp/_pw.txt").read_text().strip()
    data = json.dumps({"username": "admin", "password": pw}).encode()
    req = urllib.request.Request(
        f"{ODYSSEUS_URL}/api/auth/login",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read())
        token = body.get("session_token") or body.get("token")
        if token:
            with open(COOKIE_FILE, "w") as f:
                f.write(token)
            return token
    raise RuntimeError("login failed")


def get_or_create_session(name, model, endpoint_id, rag=True):
    """Find or create a chat session."""
    import urllib.request
    import urllib.parse

    cookie = get_ody_session()
    req = urllib.request.Request(
        f"{ODYSSEUS_URL}/api/sessions",
        headers={"Cookie": f"odysseus_session={cookie}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        sessions = json.loads(resp.read())

    for s in sessions:
        if s.get("name") == name:
            return s.get("id")

    body = urllib.parse.urlencode({
        "name": name, "model": model, "endpoint_id": endpoint_id,
        "rag": str(rag).lower(),
    }).encode()
    req = urllib.request.Request(
        f"{ODYSSEUS_URL}/api/session",
        data=body,
        headers={
            "Cookie": f"odysseus_session={cookie}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read()).get("id")


def ask_cloud_ai(model, prompt, system=None, timeout=180):
    """Ask a cloud AI a question. Returns (response, elapsed)."""
    import urllib.request

    sid = get_or_create_session(f"self-upgrade-{model}", model, CLOUD_ENDPOINT, rag=False)
    cookie = get_ody_session()

    # Build message
    if system:
        user_msg = f"[SYSTEM CONTEXT]\n{system}\n\n[REQUEST]\n{prompt}"
    else:
        user_msg = prompt

    body = json.dumps({"message": user_msg, "session": sid, "use_rag": False})
    req = urllib.request.Request(
        f"{ODYSSEUS_URL}/api/chat",
        data=body.encode(),
        headers={
            "Cookie": f"odysseus_session={cookie}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return data.get("response", ""), time.time() - t0
    except Exception as e:
        return f"(error: {e})", time.time() - t0


def ask_local_ai(prompt, model=LOCAL_AI, use_rag=True, timeout=120):
    """Ask the local AI with RAG enabled."""
    import urllib.request

    sid = get_or_create_session(f"self-upgrade-local", model, LOCAL_ENDPOINT, rag=use_rag)
    cookie = get_ody_session()

    body = json.dumps({"message": prompt, "session": sid, "use_rag": use_rag})
    req = urllib.request.Request(
        f"{ODYSSEUS_URL}/api/chat",
        data=body.encode(),
        headers={
            "Cookie": f"odysseus_session={cookie}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return data.get("response", ""), time.time() - t0
    except Exception as e:
        return f"(error: {e})", time.time() - t0


def save_memory(text, source="self_upgrade"):
    """Save a learning to Odysseus memory. Chunks if >4500 chars (limit ~5000)."""
    import urllib.request
    cookie = get_ody_session()
    
    # Chunk if too long
    chunks = [text]
    if len(text) > 4500:
        chunks = []
        # Split on double newlines (paragraph boundaries)
        parts = text.split("\n\n")
        current = ""
        for part in parts:
            if len(current) + len(part) + 2 > 4500 and current:
                chunks.append(current)
                current = part
            else:
                current = current + "\n\n" + part if current else part
        if current:
            chunks.append(current)
    
    results = []
    for i, chunk in enumerate(chunks):
        chunk_source = source if len(chunks) == 1 else f"{source}_part{i+1}of{len(chunks)}"
        body = json.dumps({"text": chunk, "source": chunk_source, "session_id": None}).encode()
        req = urllib.request.Request(
            f"{ODYSSEUS_URL}/api/memory/add",
            data=body,
            headers={
                "Cookie": f"odysseus_session={cookie}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                results.append(json.loads(resp.read()))
        except urllib.error.HTTPError as e:
            if e.code == 422:
                # Try smaller chunks
                smaller = [chunk[j:j+2000] for j in range(0, len(chunk), 2000)]
                for j, sub in enumerate(smaller):
                    sub_source = f"{chunk_source}_sub{j+1}"
                    body = json.dumps({"text": sub, "source": sub_source, "session_id": None}).encode()
                    req = urllib.request.Request(
                        f"{ODYSSEUS_URL}/api/memory/add",
                        data=body,
                        headers={
                            "Cookie": f"odysseus_session={cookie}",
                            "Content-Type": "application/json",
                        },
                        method="POST",
                    )
                    try:
                        with urllib.request.urlopen(req, timeout=10) as resp:
                            results.append(json.loads(resp.read()))
                    except Exception as ex:
                        results.append({"error": str(ex)})
            else:
                results.append({"error": str(e)})
    return {"ok": True, "count": len(results), "chunks": results}


def save_suggestion(category, content, source_ai, confidence=0.7):
    """Save an AI-suggested improvement to review queue (NEVER auto-applied)."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = SUGGESTIONS_DIR / f"{timestamp}_{category}_{source_ai}.json"
    payload = {
        "timestamp": timestamp,
        "category": category,
        "source_ai": source_ai,
        "confidence": confidence,
        "content": content,
        "status": "pending_review",  # ALWAYS pending until human approves
    }
    fname.write_text(json.dumps(payload, indent=2))
    return fname


def web_search(query):
    """Web search using searxng (running in docker) or fallback."""
    import urllib.request
    import urllib.parse

    # Try searxng first (on port 8080 in docker setup)
    try:
        params = urllib.parse.urlencode({"q": query, "format": "json", "language": "en"})
        req = urllib.request.Request(
            f"http://localhost:8080/search?{params}",
            headers={"User-Agent": "vexin-self-upgrade/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            results = data.get("results", [])
            return [{
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "")[:500],
            } for r in results[:5]]
    except Exception as e:
        return [{"error": f"web search failed: {e}"}]


def web_fetch(url, max_chars=2000):
    """Fetch a URL and extract text content."""
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "vexin-self-upgrade/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
            # Strip HTML tags roughly
            content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL)
            content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL)
            content = re.sub(r'<[^>]+>', ' ', content)
            content = re.sub(r'\s+', ' ', content)
            return content[:max_chars]
    except Exception as e:
        return f"(fetch failed: {e})"


def cmd_task(task):
    """Full self-improvement loop on a task."""
    print("=" * 70)
    print(f"SELF-IMPROVEMENT LOOP: {task}")
    print("=" * 70)

    # Step 1: Local AI tries the task
    print("\n[1/4] Local AI attempt...")
    local_result, local_time = ask_local_ai(task)
    print(f"  ⏱ {local_time:.2f}s")
    print(f"  Result: {local_result[:200]}...")

    # Step 2: Ask 3 cloud AIs to teach local AI
    print("\n[2/4] 3 cloud AIs analyzing the task and local AI's response...")
    cloud_teachings = []
    for ai in CLOUD_AIS:
        print(f"\n  --- {ai['name']} ({ai['personality']}) ---")
        teach_prompt = f"""A local AI was asked this task:
[TASK]
{task}

[LOCAL AI'S RESPONSE]
{local_result}

Your job: give CONCISE, ACTIONABLE feedback to help the local AI solve this better.
Focus on:
1. What the local AI got wrong or missed
2. Specific facts/knowledge it needs
3. Step-by-step approach it should take
4. Common pitfalls to avoid

Be specific and brief. Aim for 200-400 words."""
        teaching, teach_time = ask_cloud_ai(ai["model"], teach_prompt,
                                             system="You are a teacher helping a local AI improve.")
        cloud_teachings.append({
            "ai": ai["name"],
            "teaching": teaching,
            "time": teach_time,
        })
        print(f"    ⏱ {teach_time:.2f}s")
        print(f"    Teaching: {teaching[:200]}...")

    # Step 3: Local AI retries with all 3 cloud teachings
    print("\n[3/4] Local AI retry with cloud feedback...")
    teachings_text = "\n\n".join([
        f"[{t['ai']}]\n{t['teaching']}" for t in cloud_teachings
    ])
    retry_prompt = f"""[ORIGINAL TASK]
{task}

[YOUR FIRST ATTEMPT]
{local_result}

[FEEDBACK FROM 3 CLOUD AIs]
{teachings_text}

Now retry the task using the feedback above. Be concise and direct."""
    retry_result, retry_time = ask_local_ai(retry_prompt)
    print(f"  ⏱ {retry_time:.2f}s")
    print(f"  Result: {retry_result[:200]}...")

    # Step 4: Save learnings
    print("\n[4/4] Saving learnings to memory...")
    cloud_text = "\n\n".join([
        "--- " + t['ai'] + " ---\n" + t['teaching']
        for t in cloud_teachings
    ])
    learning = (
        "=== SELF-IMPROVEMENT LOOP RESULT (" + datetime.now().isoformat() + ") ===\n\n"
        "TASK: " + task + "\n\n"
        "LOCAL AI FIRST ATTEMPT:\n" + local_result + "\n\n"
        "CLOUD AI TEACHINGS:\n" + cloud_text + "\n\n"
        "LOCAL AI RETRY RESULT:\n" + retry_result + "\n\n"
        "IMPROVEMENT METRICS:\n"
        "  - First attempt: " + f"{local_time:.2f}" + "s\n"
        "  - Retry: " + f"{retry_time:.2f}" + "s\n"
        "  - Cloud feedback total: " + f"{sum(t['time'] for t in cloud_teachings):.2f}" + "s\n"
        "  - Total loop: " + f"{local_time + retry_time + sum(t['time'] for t in cloud_teachings):.2f}" + "s\n"
    )
    result = save_memory(learning, "self_upgrade_loop")
    print(f"  Saved memory: {result.get('count')} entries total")

    # Save each cloud teaching as a suggestion for review
    for t in cloud_teachings:
        save_suggestion("teaching", t["teaching"], t["ai"])

    print(f"\n{'='*70}")
    print(f"LOOP COMPLETE: {local_time + retry_time + sum(t['time'] for t in cloud_teachings):.2f}s total")
    print(f"Suggestions saved to: {SUGGESTIONS_DIR}")
    print(f"{'='*70}")


def cmd_teach(lesson):
    """Ask 3 cloud AIs to teach a lesson to the local AI."""
    print("=" * 70)
    print(f"TEACH: 3 cloud AIs explaining a concept to the local AI")
    print("=" * 70)
    print(f"Topic: {lesson}\n")

    teachings = []
    for ai in CLOUD_AIS:
        print(f"--- {ai['name']} ({ai['personality']}) ---")
        prompt = f"""Explain this concept clearly to a local AI:
{lesson}

Structure your answer as:
1. Core concept (1-2 sentences)
2. Key facts/definitions (bullet list)
3. Common mistakes
4. When/how to use this
5. Example

Keep it under 500 words. Be precise."""
        response, elapsed = ask_cloud_ai(ai["model"], prompt)
        teachings.append({"ai": ai["name"], "content": response, "time": elapsed})
        print(f"  ⏱ {elapsed:.2f}s")
        print(f"  {response[:300]}...\n")

    # Save to memory
    teach_text = "\n\n".join([
        "--- " + t['ai'] + " ---\n" + t['content']
        for t in teachings
    ])
    full = "=== LESSON: " + lesson + "\n\n" + teach_text + "\n"
    result = save_memory(full, f"cloud_teach_{int(time.time())}")
    print(f"\nSaved to memory: {result.get('count')} entries total")

    return teachings


def cmd_research(topic):
    """Web research on a topic, with cloud AIs summarizing."""
    print("=" * 70)
    print(f"RESEARCH: {topic}")
    print("=" * 70)

    # Step 1: Web search
    print("\n[1/3] Web search via searxng...")
    results = web_search(topic)
    for r in results[:3]:
        print(f"  - {r.get('title', '?')[:80]}")
        print(f"    {r.get('url', '?')[:80]}")

    # Step 2: Fetch top result
    if results and not results[0].get("error"):
        top = results[0]
        print(f"\n[2/3] Fetching top result: {top.get('title', '?')}")
        content = web_fetch(top.get("url", ""))
        print(f"  Content ({len(content)} chars): {content[:300]}...")

        # Step 3: Have 3 cloud AIs summarize and learn
        print("\n[3/3] 3 cloud AIs analyze and summarize the content...")
        for ai in CLOUD_AIS:
            print(f"\n  --- {ai['name']} ---")
            prompt = f"""Source article about '{topic}':
URL: {top.get('url', '?')}
Content:
{content}

Summarize the 5 most important takeaways for an AI agent that wants to learn from this.
Focus on actionable knowledge, not just facts. Be concise."""
            response, elapsed = ask_cloud_ai(ai["model"], prompt)
            print(f"    ⏱ {elapsed:.2f}s")
            print(f"    {response[:300]}...")

            # Save each as memory + suggestion
            save_memory(f"""=== RESEARCH LEARNING: {topic}

SOURCE: {top.get('url', '?')}

SUMMARY BY {ai['name']}:
{response}""", f"research_{ai['name'].lower()}")

            save_suggestion("research", response, ai["name"])
    else:
        print("\n[2/3] No web results found.")


def cmd_code_review(filepath):
    """3 cloud AIs review code and suggest improvements."""
    print("=" * 70)
    print(f"CODE REVIEW: {filepath}")
    print("=" * 70)

    file_path = Path(filepath)
    if not file_path.exists():
        # Try in projects dir
        file_path = PROJECTS_DIR / filepath
    if not file_path.exists():
        print(f"File not found: {filepath}")
        return

    code = file_path.read_text()
    if len(code) > 5000:
        print(f"Warning: file is {len(code)} chars, truncating to 5000")
        code = code[:5000]

    print(f"\nFile: {file_path}")
    print(f"Size: {file_path.stat().st_size} bytes\n")

    for ai in CLOUD_AIS:
        print(f"--- {ai['name']} review ---")
        prompt = f"""Review this code:

```python
{code}
```

Provide:
1. Bugs (be specific, line numbers if possible)
2. Security issues
3. Performance improvements
4. Style/best practices
5. Suggested refactor (show before/after)

Be concise. Max 400 words. If the code is good, say so."""
        response, elapsed = ask_cloud_ai(ai["model"], prompt)
        print(f"  ⏱ {elapsed:.2f}s")
        print(f"  {response}\n")

        # Save suggestions
        save_suggestion("code_review", f"FILE: {filepath}\n\n{response}",
                       f"{ai['name']}_{file_path.name}")


def cmd_upgrade_self():
    """Scan all local agents and get 3 cloud AIs to suggest improvements."""
    print("=" * 70)
    print("SELF-UPGRADE: 3 cloud AIs review all local agents")
    print("=" * 70)

    # Find all .py files in projects dir
    agent_files = [
        "vexin_agent.py",
        "multi_ai_orchestrator.py",
        "vexin_dual_brain.py",
        "vexin_jarvis.py",
        "vexin_image_to_3d.py",
        "vexin_3d_router.py",
        "vexin_printer.py",
        "vexin_web_agent.py",
        "vexin_triposr.py",
        "ai_school.py",
    ]

    for f in agent_files:
        path = PROJECTS_DIR / f
        if not path.exists():
            continue
        print(f"\n=== Reviewing {f} ({path.stat().st_size} bytes) ===")
        # Get one quick review from nemotron (best for code)
        cmd_code_review(str(path))


def cmd_discuss(topic):
    """Multi-AI discussion on a topic."""
    print("=" * 70)
    print(f"MULTI-AI DISCUSSION: {topic}")
    print("=" * 70)

    history = [f"[TOPIC]\n{topic}"]

    for round_num in range(2):  # 2 rounds
        print(f"\n--- Round {round_num + 1} ---")
        for ai in CLOUD_AIS:
            print(f"  {ai['name']} speaking...")
            context = "\n\n---\n\n".join(history)
            prompt = f"""This is a multi-AI discussion. Here's the history:

{context}

Your turn to contribute. Either:
- Build on what others said
- Disagree with specific points (cite them)
- Add a new angle
- Conclude if you think the topic is settled

Be brief (3-5 sentences). Be specific. No fluff."""
            response, elapsed = ask_cloud_ai(ai["model"], prompt)
            history.append(f"[{ai['name']}]:\n{response}")
            print(f"    ⏱ {elapsed:.2f}s")
            print(f"    {response[:200]}...")

    # Save the discussion
    full = f"""=== MULTI-AI DISCUSSION: {topic}

{chr(10).join(history)}
"""
    save_memory(full, f"multi_ai_discussion_{int(time.time())}")
    print(f"\n{'='*70}")
    print("Discussion saved to memory")


def cmd_status():
    """Show all pending suggestions."""
    print("=" * 70)
    print(f"SELF-UPGRADE STATUS")
    print("=" * 70)

    print(f"\nSuggestions directory: {SUGGESTIONS_DIR}")
    suggestions = sorted(SUGGESTIONS_DIR.glob("*.json"))
    if not suggestions:
        print("  (no suggestions yet)")
    else:
        print(f"  {len(suggestions)} pending review:")
        for s in suggestions[-10:]:
            try:
                d = json.loads(s.read_text())
                print(f"  {s.name}")
                print(f"    category: {d.get('category')}, source: {d.get('source_ai')}, status: {d.get('status')}")
                print(f"    content preview: {d.get('content', '')[:100]}...")
            except:
                pass

    # Memory stats
    import urllib.request
    cookie = get_ody_session()
    req = urllib.request.Request(
        f"{ODYSSEUS_URL}/api/memory/timeline?limit=1000",
        headers={"Cookie": f"odysseus_session={cookie}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    entries = data.get("timeline", [])
    self_upgrade = [e for e in entries if "self_upgrade" in (e.get("source", "") or "")]
    print(f"\nMemory: {len(entries)} total, {len(self_upgrade)} from self-upgrade")

    # Skills stats
    req = urllib.request.Request(
        f"{ODYSSEUS_URL}/api/skills",
        headers={"Cookie": f"odysseus_session={cookie}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    print(f"Skills: {data.get('count', '?')}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_task = sub.add_parser("task")
    p_task.add_argument("task_text")

    p_teach = sub.add_parser("teach")
    p_teach.add_argument("lesson")

    p_research = sub.add_parser("research")
    p_research.add_argument("topic")

    p_review = sub.add_parser("code-review")
    p_review.add_argument("file")

    sub.add_parser("upgrade-self")

    p_discuss = sub.add_parser("discuss")
    p_discuss.add_argument("topic")

    sub.add_parser("status")

    args = parser.parse_args()

    if args.cmd == "task":
        cmd_task(args.task_text)
    elif args.cmd == "teach":
        cmd_teach(args.lesson)
    elif args.cmd == "research":
        cmd_research(args.topic)
    elif args.cmd == "code-review":
        cmd_code_review(args.file)
    elif args.cmd == "upgrade-self":
        cmd_upgrade_self()
    elif args.cmd == "discuss":
        cmd_discuss(args.topic)
    elif args.cmd == "status":
        cmd_status()


if __name__ == "__main__":
    main()