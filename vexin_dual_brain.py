#!/usr/bin/env python3
"""
vexin_dual_brain.py — CPU thinking layer + GPU execution layer

Architecture:
  USER QUESTION
       ↓
  [CPU THINKER: deepseek-r1:1.5b] ← always warm, low latency (1-3s)
       ↓ (produces thought summary + plan)
  [GPU EXECUTOR: qwen2.5-coder / llama3.1 / minimax-m3] ← does the heavy work
       ↓ (gets context: question + CPU thought + retrieved memories)
  RESULT (with reasoning shown)

Benefits:
  - CPU thinker runs in parallel with GPU work (doesn't compete for VRAM)
  - CPU thought gives the GPU model a "first draft" to refine
  - Always-on: even when GPU is busy with Ollama inference, CPU is ready
  - Cheap: 1.5B model on CPU = ~3s per thought

Usage:
  ./vexin_dual_brain.py chat "What's the SAS tax threshold in Paraguay?"
  ./vexin_dual_brain.py think "complex question"     # CPU-only
  ./vexin_dual_brain.py execute "what to do"         # GPU only
  ./vexin_dual_brain.py dual "question"              # both
  ./vexin_dual_brain.py info                          # status

Models:
  - CPU thinker: deepseek-r1:1.5b (1.1 GB, fast on CPU, reasoning)
  - GPU executor: minimax-m3 (cloud, default) or llama3.1:8b (local)
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Endpoints
LOCAL_OLLAMA = "http://localhost:11434"
LOCAL_ENDPOINT_ID = "262a8872"  # local Ollama
CLOUD_ENDPOINT_ID = "d2947ec9"  # Ollama Cloud

# Models
CPU_THINKER = "deepseek-r1:1.5b"  # small, fast, reasoning
GPU_EXECUTOR_DEFAULT = "minimax-m3"  # cloud, fast chat

# Odysseus
ODYSSEUS_URL = "http://localhost:7000"
COOKIE_FILE = "/tmp/c.txt"


def get_ody_session():
    """Login to Odysseus and return cookie + base URL."""
    import urllib.request
    import urllib.error
    import re

    # Read cookie if cached (handle both plain token and curl format)
    try:
        with open(COOKIE_FILE) as f:
            content = f.read().strip()
        # Try to extract token from curl format
        m = re.search(r'odysseus_session\s+(\S+)', content)
        cookie = m.group(1) if m else content
    except FileNotFoundError:
        cookie = None

    if cookie:
        return cookie, ODYSSEUS_URL

    # Login
    pw_file = Path("/tmp/_pw.txt")
    if not pw_file.exists():
        raise RuntimeError("No Odysseus cookie and no password file")

    pw = pw_file.read_text().strip()

    data = json.dumps({"username": "admin", "password": pw}).encode()
    req = urllib.request.Request(
        f"{ODYSSEUS_URL}/api/auth/login",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            token = body.get("session_token") or body.get("token")
            if token:
                with open(COOKIE_FILE, "w") as f:
                    f.write(token)
                return token, ODYSSEUS_URL
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"login failed: {e.code} {body[:200]}")
    raise RuntimeError("login: no token returned")


def get_or_create_session(name, model, endpoint_id, rag=True):
    """Get or create an Odysseus chat session."""
    cookie, base = get_ody_session()
    import urllib.request
    import urllib.error

    # List existing
    req = urllib.request.Request(
        f"{base}/api/sessions",
        headers={"Cookie": f"odysseus_session={cookie}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        sessions = json.loads(resp.read())

    for s in sessions:
        if s.get("name") == name:
            return s.get("id")

    # Create
    body = urllib.parse.urlencode({
        "name": name, "model": model, "endpoint_id": endpoint_id,
        "rag": str(rag).lower(),
    }).encode()
    req = urllib.request.Request(
        f"{base}/api/session",
        data=body,
        headers={
            "Cookie": f"odysseus_session={cookie}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        s = json.loads(resp.read())
        return s.get("id")


def cpu_think(question, max_thinking_tokens=400, max_summary_tokens=200):
    """CPU thinker: deepseek-r1:1.5b. Returns (thinking, summary, elapsed).

    Pipeline:
      1. First call: thinking only (max_thinking_tokens)
      2. Second call: condense to a 2-3 sentence summary (max_summary_tokens)
    """
    t0 = time.time()
    import urllib.request

    # Step 1: Think
    thinking_prompt = f"""Think briefly about this question.

Question: {question}

Consider:
- What's being asked
- What context is needed
- What approach to take
- Pitfalls to avoid

Be concise but thorough. Don't use <think> tags."""

    body = json.dumps({
        "model": CPU_THINKER,
        "prompt": thinking_prompt,
        "stream": False,
        "options": {
            "num_predict": max_thinking_tokens,
            "temperature": 0.6,
            "num_ctx": 2048,
            "num_gpu": 0,  # FORCE CPU ONLY
        },
    }).encode()

    req = urllib.request.Request(
        f"{LOCAL_OLLAMA}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    thinking = ""
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            # DeepSeek-R1 returns BOTH 'thinking' (chain of thought) and 'response' (final answer)
            thinking = data.get("thinking", "").strip()
            response = data.get("response", "").strip()
            # Use thinking if present, else fall back to response
            if not thinking:
                thinking = response
            thinking = thinking.replace("<think>", "").replace("</think>", "").strip()
    except Exception as e:
        return f"(CPU thinker error: {e})", "", time.time() - t0

    # Step 2: Summarize
    summary_prompt = f"""Based on this thinking:
---
{thinking}
---

Write a CONCISE 2-3 sentence brief for another AI that will execute the answer.
Focus on: what to research, what approach to take, key constraints.
No preamble, just the brief:"""

    body = json.dumps({
        "model": CPU_THINKER,
        "prompt": summary_prompt,
        "stream": False,
        "options": {
            "num_predict": max_summary_tokens,
            "temperature": 0.5,
            "num_ctx": 1024,
            "num_gpu": 0,
        },
    }).encode()

    req = urllib.request.Request(
        f"{LOCAL_OLLAMA}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    summary = ""
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            # Prefer 'thinking' (richer for R1), fall back to 'response'
            summary = data.get("thinking", "").strip() or data.get("response", "").strip()
            summary = summary.replace("<think>", "").replace("</think>", "").strip()
    except Exception as e:
        summary = ""

    return thinking, summary, time.time() - t0


def gpu_execute(question, cpu_summary=None, model=None, endpoint_id=None,
                use_rag=True):
    """GPU executor: chat with question + CPU thought summary."""
    if model is None:
        model = GPU_EXECUTOR_DEFAULT
    if endpoint_id is None:
        # Cloud model
        endpoint_id = CLOUD_ENDPOINT_ID if model in ("minimax-m3", "nemotron-3-ultra", "glm-5.2") else LOCAL_ENDPOINT_ID

    sid = get_or_create_session(f"dual-brain-{model}", model, endpoint_id, rag=use_rag)
    cookie, base = get_ody_session()

    # Build prompt with CPU thought as context
    if cpu_summary:
        user_msg = f"""[CPU THINKER ANALYSIS]
{cpu_summary}

[USER QUESTION]
{question}

[YOUR TASK]
Use the CPU thinker's analysis above to answer the user's question directly.
The thinker already broke down the problem — your job is to give the
final, polished answer."""
    else:
        user_msg = question

    import urllib.request
    body = json.dumps({
        "message": user_msg,
        "session": sid,
        "use_rag": use_rag,
    }).encode()
    req = urllib.request.Request(
        f"{base}/api/chat",
        data=body,
        headers={
            "Cookie": f"odysseus_session={cookie}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
            elapsed = time.time() - t0
            return data.get("response", "(no response)"), elapsed, sid
    except Exception as e:
        return f"(GPU executor error: {e})", time.time() - t0, sid


def cmd_dual(question):
    """Full pipeline: CPU think + GPU execute."""
    print(f"\n{'='*70}")
    print(f"DUAL BRAIN: thinking + executing")
    print(f"{'='*70}\n")
    print(f"Question: {question}\n")

    # Step 1: CPU think
    print("─" * 70)
    print("[1/2] CPU THINKER (deepseek-r1:1.5b)")
    print("─" * 70)
    thinking, summary, cpu_time = cpu_think(question)
    print(f"⏱  {cpu_time:.2f}s")
    if thinking:
        print(f"\nThinking:\n{thinking[:600]}{'...' if len(thinking) > 600 else ''}")
    if summary:
        print(f"\n📋 Summary for GPU:\n{summary[:300]}")

    # Step 2: GPU execute
    print("\n" + "─" * 70)
    print("[2/2] GPU EXECUTOR (minimax-m3:cloud)")
    print("─" * 70)
    answer, gpu_time, sid = gpu_execute(question, summary)
    print(f"⏱  {gpu_time:.2f}s")
    print(f"\nAnswer:\n{answer}")

    print(f"\n{'='*70}")
    print(f"Total: {cpu_time + gpu_time:.2f}s (CPU: {cpu_time:.2f}s + GPU: {gpu_time:.2f}s)")
    print(f"{'='*70}")


def cmd_think(question):
    """CPU-only thinking."""
    print(f"\n[CPU THINKER]: {question}")
    thinking, summary, elapsed = cpu_think(question)
    print(f"\n⏱  {elapsed:.2f}s\n")
    print(f"Thinking:\n{thinking}\n")
    if summary:
        print(f"Summary:\n{summary}")


def cmd_execute(question):
    """GPU-only execution (no CPU thinking)."""
    print(f"\n[GPU EXECUTOR]: {question}")
    answer, elapsed, sid = gpu_execute(question, cpu_summary=None)
    print(f"\n⏱  {elapsed:.2f}s\n")
    print(f"Answer:\n{answer}")


def cmd_info():
    """System status."""
    print("=" * 70)
    print("VEXinWorks DUAL BRAIN")
    print("=" * 70)

    # Models
    r = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    print("\nInstalled models:")
    print(r.stdout)

    # VRAM
    try:
        with open("/sys/class/drm/card1/device/mem_info_vram_used") as f:
            vram_used = int(f.read()) / 1e9
        with open("/sys/class/drm/card1/device/mem_info_vram_total") as f:
            vram_total = int(f.read()) / 1e9
        print(f"VRAM: {vram_used:.2f}GB / {vram_total:.2f}GB ({vram_total - vram_used:.2f}GB free)")
    except Exception:
        pass

    # RAM
    r = subprocess.run(["free", "-h"], capture_output=True, text=True)
    print(f"\nRAM:")
    print(r.stdout.split("\n")[1])

    # CPU
    r = subprocess.run(["nproc"], capture_output=True, text=True)
    print(f"CPU cores: {r.stdout.strip()}")

    # CPU thinker status
    print(f"\nCPU thinker: {CPU_THINKER}")
    r = subprocess.run(["ollama", "show", CPU_THINKER], capture_output=True, text=True)
    for line in r.stdout.split("\n"):
        if any(k in line for k in ["parameters", "quantization", "architecture"]):
            print(f"  {line.strip()}")

    print(f"\nGPU executor default: {GPU_EXECUTOR_DEFAULT} (cloud)")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_dual = sub.add_parser("dual")
    p_dual.add_argument("question")
    p_dual.add_argument("--model", help="override GPU model")
    p_dual.add_argument("--no-rag", action="store_true")

    p_think = sub.add_parser("think")
    p_think.add_argument("question")

    p_exec = sub.add_parser("execute")
    p_exec.add_argument("question")
    p_exec.add_argument("--model")

    sub.add_parser("info")

    args = parser.parse_args()

    if args.cmd == "dual":
        cmd_dual(args.question)
    elif args.cmd == "think":
        cmd_think(args.question)
    elif args.cmd == "execute":
        cmd_execute(args.question)
    elif args.cmd == "info":
        cmd_info()


if __name__ == "__main__":
    main()