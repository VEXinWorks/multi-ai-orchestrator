#!/usr/bin/env python3
"""Generate useful tools for VEXinWorks using local AI (no cloud overload)."""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/vexin/projects")

TOOLS = [
    {
        "name": "vexin_paraguay_tax_calc.py",
        "desc": "Python script that calculates IRPC, IVA, minimum tax for a given revenue in Paraguay. Show formulas, deductions, monthly obligations.",
    },
    {
        "name": "vexin_print_quote.py",
        "desc": "STL file analyzer that estimates print time, material weight, and PLA cost in PYG (Paraguayan guaraní) for a given 3D print job.",
    },
    {
        "name": "vexin_invoice_gen.py",
        "desc": "SET e-Kuatia compatible invoice generator in JSON format. Produces a valid invoice XML/JSON for Paraguay's electronic invoicing system.",
    },
    {
        "name": "vexin_customer_crm.py",
        "desc": "Simple CRM for tracking customers, quotes, and follow-ups. Uses SQLite for storage. Supports add/list/update customers and quote tracking.",
    },
    {
        "name": "vexin_whatsapp_bot.py",
        "desc": "Simple WhatsApp Business webhook handler for auto-replies. Receives messages, classifies intent, sends templated responses. Uses Flask.",
    },
]

# Use cloud AIs but one tool at a time (not parallel)
# Each tool takes ~60-120 seconds
def generate_tool(tool):
    """Generate one tool using cloud AI."""
    name = tool["name"]
    desc = tool["desc"]
    out_path = f"/home/vexin/projects/{name}"

    prompt = f"""Write a complete, production-ready Python script at {out_path}.

Description: {desc}

Context: João runs a small 3D printing + AI automation business in Paraguay.
- Use Paraguayan guaraní (₲ / PYG) for currency
- SET e-Kuatia for invoicing
- BCP/Itaú banks
- IVA 10%, IRPC 8-10% tax rates

Requirements:
- Complete working code (no placeholders or TODOs)
- Proper imports at top
- Docstring at top with description
- if __name__ == '__main__': guard
- Basic error handling
- Type hints where helpful
- After writing, the script should be runnable with python3 {name}

Output ONLY the Python code in a single markdown code block, no explanations."""

    # Use the dual brain to write the code
    from vexin_dual_brain import cpu_think, gpu_execute

    try:
        thinking, summary, _ = cpu_think(prompt)
        answer, elapsed, sid = gpu_execute(prompt, summary, model="minimax-m3", use_rag=False)
        print(f"  Generated ({elapsed:.1f}s)")
        return answer
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def extract_code(text):
    """Extract Python code from markdown code blocks."""
    if not text:
        return None
    # Look for ```python ... ``` or ``` ... ```
    patterns = [
        r'```python\n(.*?)\n```',
        r'```\n(.*?)\n```',
        r'```py\n(.*?)\n```',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1)
    # If no code block, maybe the whole thing is code
    if 'def ' in text and 'import' in text:
        return text
    return None


def main():
    log_path = "/tmp/tools-sequential.log"
    with open(log_path, "a") as log:
        log.write(f"\n=== {time.strftime('%H:%M:%S')} STARTING SEQUENTIAL TOOL GEN ===\n")

    for tool in TOOLS:
        name = tool["name"]
        desc = tool["desc"]
        out_path = f"/home/vexin/projects/{name}"

        print(f"\n=== Generating {name} ===")
        with open(log_path, "a") as log:
            log.write(f"\n--- {time.strftime('%H:%M:%S')} {name} ---\n")

        # Skip if already exists
        if os.path.exists(out_path) and os.path.getsize(out_path) > 500:
            print(f"  Already exists ({os.path.getsize(out_path)} bytes), skipping")
            continue

        # Generate
        start = time.time()
        result = generate_tool(tool)
        elapsed = time.time() - start

        if not result:
            print(f"  FAILED ({elapsed:.1f}s)")
            with open(log_path, "a") as log:
                log.write(f"  FAILED after {elapsed:.1f}s\n")
            time.sleep(10)
            continue

        # Extract code
        code = extract_code(result)
        if not code:
            print(f"  No code block found in response ({len(result)} chars)")
            with open(log_path, "a") as log:
                log.write(f"  No code block ({len(result)} chars)\n")
            time.sleep(5)
            continue

        # Write file
        with open(out_path, "w") as f:
            f.write(code)
        size = len(code)
        print(f"  Written: {out_path} ({size} chars)")

        # Verify it compiles
        try:
            subprocess.run(
                ["python3", "-c", f"import py_compile; py_compile.compile('{out_path}', doraise=True)"],
                check=True, capture_output=True, timeout=10,
            )
            print(f"  ✓ Compiles OK")
            with open(log_path, "a") as log:
                log.write(f"  ✓ Written + compiles ({size} chars, {elapsed:.1f}s)\n")
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode()[:500] if e.stderr else 'unknown'
            print(f"  ✗ Compile error: {err[:200]}")
            with open(log_path, "a") as log:
                log.write(f"  ✗ Compile error: {err[:200]}\n")

        # Sleep between to let server recover
        time.sleep(15)

    print(f"\n=== ALL DONE at {time.strftime('%H:%M:%S')} ===")


if __name__ == "__main__":
    main()