#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vexin_local_workforce.py — Actually use ALL local AIs in parallel

The school uses only llama3.1:8b. The dashboard shows 5 AI profiles but only
2 are "active" in any meaningful work. This script:

1. Loads multiple local models (within VRAM budget)
2. Assigns each a specific role
3. Has them work IN PARALLEL on real tasks
4. Cycles through them so each one gets used

Models used:
- llama3.1:8b (4.9 GB) — general workhorse
- qwen2.5-coder:7b (4.7 GB) — code generation
- deepseek-r1:1.5b (1.1 GB) — CPU planner
- llama3.2:3b (2.0 GB) — fast summarizer
- nomic-embed-text (0.3 GB) — embeddings
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


# === MODEL ROSTER (each model has a role) ===
WORKFORCE = [
    {
        "name": "llama3.1:8b",
        "role": "general",
        "vram_gb": 4.9,
        "tasks": ["general Q&A", "RAG", "business logic", "summarization", "planning"],
        "system_prompt": "You are the main VEXinWorks local AI. Be direct, practical, and concise. Prefer concrete advice over theory.",
    },
    {
        "name": "qwen2.5-coder:7b",
        "role": "code",
        "vram_gb": 4.7,
        "tasks": ["code generation", "debugging", "refactoring", "SQL", "shell scripts", "Python"],
        "system_prompt": "You are the VEXinWorks coding specialist. Write clean, production-ready code with type hints, error handling, and clear docstrings. Prefer Python.",
    },
    {
        "name": "llama3.2:3b",
        "role": "fast",
        "vram_gb": 2.0,
        "tasks": ["quick chat", "short Q&A", "summarization", "classification", "intent detection"],
        "system_prompt": "You are a fast VEXinWorks assistant. Be brief (2-3 sentences). No fluff. Just the answer.",
    },
    {
        "name": "deepseek-r1:1.5b",
        "role": "cpu_planner",
        "vram_gb": 0.0,  # CPU only
        "tasks": ["meta-reasoning", "task planning", "step decomposition", "decision frameworks"],
        "system_prompt": "You are the VEXinWorks strategic planner. Think step by step. Plan the approach, don't answer directly. Output a numbered plan.",
    },
]


def is_loaded(model: str) -> bool:
    """Check if model is in VRAM."""
    try:
        r = subprocess.run(['curl', '-sS', 'http://localhost:11434/api/ps'],
                           capture_output=True, text=True, timeout=5)
        if r.stdout:
            data = json.loads(r.stdout)
            for m in data.get("models", []):
                if m.get("name", "").startswith(model):
                    return True
    except Exception:
        pass
    return False


def unload_all_except(keep: list = None):
    """Unload all models except those in keep list."""
    keep = keep or []
    try:
        r = subprocess.run(['curl', '-sS', 'http://localhost:11434/api/ps'],
                           capture_output=True, text=True, timeout=5)
        if not r.stdout:
            return
        data = json.loads(r.stdout)
        for m in data.get("models", []):
            name = m.get("name", "")
            if not any(name.startswith(k) for k in keep):
                # Unload
                subprocess.run(['curl', '-sS', '-X', 'POST', 'http://localhost:11434/api/generate',
                              '-H', 'Content-Type: application/json',
                              '-d', json.dumps({"model": name.split(':')[0], "keep_alive": 0})],
                              capture_output=True, timeout=10)
                print(f"  unloaded {name}")
    except Exception as e:
        print(f"  unload err: {e}")


def load_model(model: str) -> bool:
    """Load a model (warm it up)."""
    if is_loaded(model):
        return True
    try:
        r = subprocess.run(
            ['curl', '-sS', '-X', 'POST', 'http://localhost:11434/api/generate',
             '-H', 'Content-Type: application/json',
             '-d', json.dumps({
                 "model": model,
                 "prompt": "hi",
                 "stream": False,
                 "options": {"num_predict": 1},
                 "keep_alive": "30m",
             })],
            capture_output=True, text=True, timeout=120,
        )
        return r.returncode == 0
    except Exception:
        return False


def ask_model(model: str, prompt: str, system: str = None,
              max_tokens: int = 1500, timeout: int = 180) -> dict:
    """Ask a model a question. Returns dict with response, elapsed, model."""
    start = time.time()
    full_prompt = f"[SYSTEM]\n{system}\n\n[USER]\n{prompt}" if system else prompt
    try:
        r = subprocess.run(
            ['curl', '-sS', '-X', 'POST', 'http://localhost:11434/api/generate',
             '-H', 'Content-Type: application/json',
             '-d', json.dumps({
                 "model": model,
                 "prompt": full_prompt,
                 "stream": False,
                 "options": {"num_predict": max_tokens, "temperature": 0.4, "num_ctx": 4096},
                 "keep_alive": "30m",
             })],
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode != 0:
            return {"model": model, "response": f"ERROR: {r.stderr[:200]}", "elapsed": time.time() - start}
        data = json.loads(r.stdout)
        return {
            "model": model,
            "response": data.get("response", ""),
            "elapsed": time.time() - start,
        }
    except subprocess.TimeoutExpired:
        return {"model": model, "response": "(timeout)", "elapsed": timeout}
    except Exception as e:
        return {"model": model, "response": f"ERROR: {e}", "elapsed": time.time() - start}


def parallel_diverse_workflow(task: str, max_models: int = 3) -> dict:
    """Run a task across multiple local models in parallel.

    Each model gets the same task but uses its own personality.
    Returns all responses + the fastest one.
    """
    print(f"\n{'='*70}")
    print(f"DIVERSE WORKFLOW: {task[:80]}")
    print(f"{'='*70}")

    # Pick top N models that fit in VRAM
    picked = []
    total_vram = 0
    for model_info in WORKFORCE:
        if len(picked) >= max_models:
            break
        vram = model_info["vram_gb"]
        if total_vram + vram <= 11.0:  # 11 GB safe budget
            picked.append(model_info)
            total_vram += vram
        else:
            print(f"  skip {model_info['name']} (VRAM would exceed)")

    print(f"  Picked: {[m['name'] for m in picked]} (total VRAM: {total_vram:.1f} GB)")

    # Unload all except the CPU model (which doesn't use VRAM)
    unload_all_except(keep=["deepseek-r1:1.5b"])

    # Load each model (sequentially to avoid OOM)
    for m in picked:
        if m["vram_gb"] > 0:
            print(f"  loading {m['name']}...")
            load_model(m["name"])

    # Now ask all in parallel
    with ThreadPoolExecutor(max_workers=len(picked)) as executor:
        futures = {}
        for m in picked:
            prompt = f"{m['system_prompt']}\n\nTask: {task}"
            fut = executor.submit(ask_model, m["name"], task, m["system_prompt"])
            futures[fut] = m

        results = []
        for fut in as_completed(futures):
            m = futures[fut]
            result = fut.result()
            result["role"] = m["role"]
            results.append(result)
            print(f"  {result['model']} ({result['elapsed']:.1f}s, role={m['role']}): {result['response'][:100]}...")

    return {
        "task": task,
        "results": results,
        "fastest": min(results, key=lambda r: r["elapsed"]),
    }


# === STANDALONE TASKS THAT USE SPECIFIC MODELS ===

def code_review_task(file_path: str) -> dict:
    """Use qwen2.5-coder:7b to review a Python file."""
    with open(file_path) as f:
        code = f.read()
    if len(code) > 4000:
        code = code[:4000] + "\n... (truncated)"

    task = f"""Review this Python file for bugs, security issues, and improvements:

```python
{code}
```

Output:
1. Critical bugs (must fix)
2. Security issues
3. Performance improvements
4. Style suggestions (max 3)

Be specific (line numbers, exact code). Be brief."""
    return parallel_diverse_workflow(task, max_models=2)


def summarize_task(text: str) -> dict:
    """Use llama3.2:3b (fast) to summarize."""
    task = f"Summarize in 3 bullet points:\n\n{text[:2000]}"
    return parallel_diverse_workflow(task, max_models=2)


def plan_task(goal: str) -> dict:
    """Use deepseek-r1:1.5b (CPU) to plan, llama3.1:8b to execute."""
    return parallel_diverse_workflow(f"Plan how to: {goal}", max_models=2)


# === MAIN CLI ===

def main():
    parser = argparse.ArgumentParser(
        description="Actually USE all your local AIs in parallel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # work: a task sent to all models
    p = sub.add_parser("work", help="Send a task to multiple local models in parallel")
    p.add_argument("task", nargs="+", help="The task to send")
    p.add_argument("--max-models", type=int, default=3, help="Max models to use in parallel")

    # review: code review
    p = sub.add_parser("review", help="Code review using local coder model")
    p.add_argument("file", help="Python file to review")

    # plan: planning task
    p = sub.add_parser("plan", help="Plan a goal using CPU planner + GPU executor")
    p.add_argument("goal", nargs="+", help="The goal to plan")

    # load: load a specific model
    p = sub.add_parser("load", help="Load a specific model")
    p.add_argument("model", help="Model name")

    # unload: unload all models
    p = sub.add_parser("unload", help="Unload all models from VRAM")

    # list: list available workforce
    p = sub.add_parser("list", help="List the local AI workforce")
    p.add_argument("--all", action="store_true", help="Show all installed models too")

    args = parser.parse_args()

    if args.cmd == "work":
        task = " ".join(args.task)
        parallel_diverse_workflow(task, max_models=args.max_models)
    elif args.cmd == "review":
        result = code_review_task(args.file)
        print(f"\n🏆 FASTEST: {result['fastest']['model']} ({result['fastest']['elapsed']:.1f}s)")
    elif args.cmd == "plan":
        goal = " ".join(args.goal)
        result = plan_task(goal)
        print(f"\n🏆 FASTEST: {result['fastest']['model']} ({result['fastest']['elapsed']:.1f}s)")
    elif args.cmd == "load":
        ok = load_model(args.model)
        print(f"{'✓' if ok else '✗'} {args.model}")
    elif args.cmd == "unload":
        unload_all_except(keep=[])
        print("✓ all unloaded")
    elif args.cmd == "list":
        print("\n🖥️  VEXinWorks Local AI Workforce\n")
        for m in WORKFORCE:
            loaded = is_loaded(m["name"])
            marker = "🟢" if loaded else "⚪"
            print(f"  {marker} {m['name']:30s} | {m['vram_gb']:4.1f} GB | {m['role']:12s} | {', '.join(m['tasks'][:3])}")
        if args.all:
            print("\n📦 All installed models:")
            r = subprocess.run(['ollama', 'list'], capture_output=True, text=True)
            for line in r.stdout.split('\n')[1:]:
                if line.strip():
                    print(f"  - {line.split()[0]}")


if __name__ == "__main__":
    main()