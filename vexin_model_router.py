#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vexin_model_router.py — Task-aware model router

Picks the BEST local model for each task type:
- Code questions → qwen2.5-coder:7b
- Simple chat    → llama3.2:3b (fast, small)
- Deep thinking  → deepseek-r1:8b
- Vision/image   → llava:7b or moondream
- Default exec   → llama3.1:8b

Auto-detects task type from prompt keywords.
Falls back to llama3.1:8b if unsure.
Manages VRAM by unloading models when not in use.

Usage:
    from vexin_model_router import ask
    result = ask("Write a Python function")  # → qwen2.5-coder
    result = ask("Hi!")  # → llama3.2:3b (fast)
    result = ask("Explain quantum entanglement deeply")  # → deepseek-r1:8b
    result = ask("What's in this image?", image_path="...")  # → llava
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional


# Model registry with capabilities
MODELS = {
    "llama3.1:8b": {
        "size_gb": 4.9,
        "vram_gb": 4.5,
        "speed": "medium",
        "type": "general",
        "specialty": "general execution, RAG, business logic, conversation",
        "category": "default",
    },
    "llama3.2:3b": {
        "size_gb": 2.0,
        "vram_gb": 1.8,
        "speed": "fast",
        "type": "general",
        "specialty": "quick chat, simple Q&A, summaries",
        "category": "fast",
    },
    "qwen2.5-coder:7b": {
        "size_gb": 4.7,
        "vram_gb": 4.3,
        "speed": "medium",
        "type": "code",
        "specialty": "code generation, debugging, refactoring, SQL, shell",
        "category": "code",
    },
    "deepseek-r1:8b": {
        "size_gb": 5.2,
        "vram_gb": 4.8,
        "speed": "slow",
        "type": "reasoning",
        "specialty": "deep reasoning, math, complex multi-step problems",
        "category": "reasoning",
    },
    "llava:7b": {
        "size_gb": 4.7,
        "vram_gb": 4.3,
        "speed": "medium",
        "type": "vision",
        "specialty": "image understanding, photo analysis, screenshots",
        "category": "vision",
    },
    "moondream:latest": {
        "size_gb": 1.7,
        "vram_gb": 1.5,
        "speed": "fast",
        "type": "vision",
        "specialty": "fast vision, small images, captions",
        "category": "vision",
    },
    "nomic-embed-text:latest": {
        "size_gb": 0.3,
        "vram_gb": 0.3,
        "speed": "fast",
        "type": "embeddings",
        "specialty": "text embeddings, semantic search, RAG",
        "category": "embed",
    },
    "deepseek-r1:1.5b": {
        "size_gb": 1.1,
        "vram_gb": 0.0,  # CPU only
        "speed": "very_fast",
        "type": "reasoning",
        "specialty": "lightning-fast local planning, meta-reasoning",
        "category": "cpu",
    },
}


# Task detection keywords (case-insensitive)
TASK_KEYWORDS = {
    "code": [
        r"\b(write|create|implement|code|program|function|class|method|api|sql|query|html|css|js|python|java|rust|go|bash|shell|script)\b",
        r"\b(refactor|debug|fix|patch|bug|error|exception|traceback|compile|syntax)\b",
        r"\b(git commit|pull request|merge|branch|commit|diff)\b",
        r"```",  # code blocks in prompt
        r"^\s*(def|class|import|from|const|let|var|function)\b",  # starts with code
    ],
    "vision": [
        r"\b(image|picture|photo|screenshot|image_path|image_url|see|look at|describe.*image|what.*in.*image|attach|attachment)\b",
        r"\b(llava|moondream|vision)\b",
    ],
    "reasoning": [
        r"\b(why|how does|explain.*deeply|analyze|reason|prove|derive|think.*about|step by step|chain of thought)\b",
        r"\b(math|equation|formula|integral|derivative|matrix|theorem|proof)\b",
        r"\b(strategy|plan|evaluate|compare|tradeoff|pros and cons)\b",
    ],
    "fast": [
        r"^(hi|hello|hey|ok|yes|no|thanks|thank you|hola|gracias)\b",
        r"\b(quick|fast|brief|short|tl;dr|summary|summarize)\b",
        r"^.{1,50}$",  # very short prompts
    ],
    "embed": [
        r"\b(embed|embedding|similarity|semantic|search|index|vector)\b",
    ],
}


def detect_task(prompt: str, has_image: bool = False) -> str:
    """Detect the task type from the prompt."""
    if has_image:
        return "vision"

    p = prompt.lower()
    scores = {}
    for task, patterns in TASK_KEYWORDS.items():
        score = 0
        for pattern in patterns:
            matches = len(re.findall(pattern, p, re.IGNORECASE | re.MULTILINE))
            score += matches
        scores[task] = score

    # Default to "general" (llama3.1:8b) if nothing else matches strongly
    if not scores or max(scores.values()) == 0:
        return "default"

    # Pick the highest scoring task
    best = max(scores, key=scores.get)
    return best


def pick_model(prompt: str, has_image: bool = False,
               prefer: Optional[str] = None,
               fast: bool = False) -> str:
    """Pick the best model for a task."""
    if prefer:
        return prefer

    if fast:
        return "llama3.2:3b"

    task = detect_task(prompt, has_image)
    routing = {
        "code": "qwen2.5-coder:7b",
        "vision": "moondream:latest" if len(prompt) < 100 else "llava:7b",
        "reasoning": "deepseek-r1:8b",
        "fast": "llama3.2:3b",
        "embed": "nomic-embed-text:latest",
        "default": "llama3.1:8b",
    }
    return routing.get(task, "llama3.1:8b")


def is_model_loaded(model: str) -> bool:
    """Check if a model is currently loaded in ollama."""
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


def get_loaded_models():
    """Get list of currently loaded models and their VRAM."""
    try:
        r = subprocess.run(['curl', '-sS', 'http://localhost:11434/api/ps'],
                           capture_output=True, text=True, timeout=5)
        if r.stdout:
            data = json.loads(r.stdout)
            return [{
                "name": m.get("name", "?"),
                "size_gb": m.get("size", 0) / 1e9,
                "vram_gb": m.get("size_vram", 0) / 1e9,
            } for m in data.get("models", [])]
    except Exception:
        pass
    return []


def unload_model(model: str) -> bool:
    """Unload a model from ollama (frees VRAM)."""
    try:
        # Set keep_alive to 0 to unload
        r = subprocess.run(
            ['curl', '-sS', '-X', 'POST', 'http://localhost:11434/api/generate',
             '-H', 'Content-Type: application/json',
             '-d', json.dumps({"model": model, "keep_alive": 0})],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def ensure_loaded(model: str) -> bool:
    """Make sure a model is loaded, unloading others if needed."""
    # First check VRAM
    loaded = get_loaded_models()
    current_vram = sum(m["vram_gb"] for m in loaded)
    target_vram = MODELS.get(model, {}).get("vram_gb", 4.0)
    available = 12.0 - current_vram  # 12GB safe limit

    # Unload other models if no room (LRU: keep small models)
    if target_vram > available and loaded:
        # Sort by size, unload largest first
        for other in sorted(loaded, key=lambda m: -m["vram_gb"]):
            if other["name"] == model:
                continue
            if target_vram <= (12.0 - current_vram + other["vram_gb"]):
                unload_model(other["name"])
                current_vram -= other["vram_gb"]
                print(f"  unloaded {other['name']} ({other['vram_gb']:.1f} GB freed)")
                break

    if not is_model_loaded(model):
        # Load by sending empty request
        try:
            r = subprocess.run(
                ['curl', '-sS', '-X', 'POST', 'http://localhost:11434/api/generate',
                 '-H', 'Content-Type: application/json',
                 '-d', json.dumps({"model": model, "prompt": "hi", "stream": False,
                                   "keep_alive": "30m"})],
                capture_output=True, text=True, timeout=120,
            )
            return r.returncode == 0
        except Exception:
            return False
    return True


@dataclass
class RouterResult:
    model: str
    task: str
    response: str
    elapsed: float
    loaded: list


def ask(prompt: str, image_path: Optional[str] = None,
        prefer: Optional[str] = None, fast: bool = False,
        max_tokens: int = 2000) -> RouterResult:
    """Ask a question, with automatic model routing."""
    start = time.time()

    # Pick model
    model = pick_model(prompt, has_image=bool(image_path),
                       prefer=prefer, fast=fast)
    task = detect_task(prompt, has_image=bool(image_path))

    print(f"  🎯 task: {task} → model: {model}")

    # Ensure loaded
    if not ensure_loaded(model):
        print(f"  ⚠ could not load {model}, falling back to llama3.1:8b")
        model = "llama3.1:8b"
        ensure_loaded(model)

    # Build request
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": 0.4,
        },
        "keep_alive": "30m",
    }

    if image_path and os.path.exists(image_path):
        import base64
        with open(image_path, "rb") as f:
            body["images"] = [base64.b64encode(f.read()).decode()]

    # Make request
    r = subprocess.run(
        ['curl', '-sS', '-X', 'POST', 'http://localhost:11434/api/generate',
         '-H', 'Content-Type: application/json',
         '-d', json.dumps(body), '--max-time', '300'],
        capture_output=True, text=True, timeout=310,
    )

    elapsed = time.time() - start

    if r.returncode != 0:
        response = f"ERROR: {r.stderr[:200]}"
    else:
        try:
            data = json.loads(r.stdout)
            response = data.get("response", "no response field")
        except Exception as e:
            response = f"PARSE ERROR: {e} | raw: {r.stdout[:200]}"

    return RouterResult(
        model=model,
        task=task,
        response=response,
        elapsed=elapsed,
        loaded=get_loaded_models(),
    )


def list_models():
    """List all available models with stats."""
    print("\n📦 All installed models:\n")
    for name, info in sorted(MODELS.items(), key=lambda x: -x[1]["size_gb"]):
        loaded = is_model_loaded(name)
        marker = "🟢" if loaded else "⚪"
        print(f"  {marker} {name:30s} | {info['size_gb']:4.1f} GB | {info['speed']:10s} | {info['specialty']}")
    print()


def explain_routing():
    """Show the routing rules."""
    print("""
🎯 Task → Model routing:

  CODE     → qwen2.5-coder:7b   (4.7 GB, best for code)
  VISION   → llava:7b or moondream
  REASONING → deepseek-r1:8b    (slow, deep thoughts)
  FAST     → llama3.2:3b        (2.0 GB, super quick)
  EMBED    → nomic-embed-text
  DEFAULT  → llama3.1:8b        (your main workhorse)

  Override with: --prefer deepseek-r1:8b
  Force fast:   --fast
""")


def main():
    parser = argparse.ArgumentParser(
        description="Task-aware local AI router",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("prompt", nargs="*", help="The question/prompt (or omit for interactive)")
    parser.add_argument("--image", help="Image path for vision tasks")
    parser.add_argument("--prefer", help="Force a specific model")
    parser.add_argument("--fast", action="store_true", help="Use fastest model (llama3.2:3b)")
    parser.add_argument("--list", action="store_true", help="List all models")
    parser.add_argument("--routing", action="store_true", help="Show routing rules")
    parser.add_argument("--interactive", action="store_true", help="Interactive mode")

    args = parser.parse_args()

    if args.list:
        list_models()
        return
    if args.routing:
        explain_routing()
        return

    if args.interactive:
        print("🎯 VEXinWorks Model Router — interactive mode")
        print("Type 'exit' to quit, 'list' to show models, 'routing' for rules\n")
        while True:
            try:
                prompt = input("\n💬 > ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not prompt:
                continue
            if prompt == "exit":
                break
            if prompt == "list":
                list_models()
                continue
            if prompt == "routing":
                explain_routing()
                continue
            result = ask(prompt)
            print(f"\n[{result.model} | {result.elapsed:.1f}s]\n")
            print(result.response)
            print(f"\n[loaded: {', '.join(m['name'] for m in result.loaded)}]")
        return

    if args.prompt:
        prompt = " ".join(args.prompt)
        result = ask(prompt, image_path=args.image, prefer=args.prefer, fast=args.fast)
        print(f"\n[{result.model} | {result.task} | {result.elapsed:.1f}s]\n")
        print(result.response)
        print(f"\n[loaded: {', '.join(m['name'] for m in result.loaded)}]")
    else:
        list_models()
        explain_routing()
        print("Use: vexin_model_router.py 'your question here'")
        print("Or:  vexin_model_router.py --interactive")


if __name__ == "__main__":
    main()