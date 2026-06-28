#!/usr/bin/env python3
"""Generate VEXinWorks tools using DIRECT ollama calls (no Odysseus overhead)."""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PROJECTS = Path("/home/vexin/projects")

TOOLS = [
    {
        "name": "vexin_paraguay_tax_calc.py",
        "desc": "Python script that calculates IRPC, IVA, minimum tax (impuesto mínimo presuntivo) for a given annual revenue in Paraguay. Show formulas, deductions, monthly obligations, and a clear breakdown. Use Paraguayan guaraní (₲ / PYG). Include a CLI interface with --revenue argument.",
    },
    {
        "name": "vexin_print_quote.py",
        "desc": "STL file analyzer that estimates print time, material weight, and PLA cost in Paraguayan guaraní (₲ / PYG) for a 3D print job. Takes an STL file path, computes approximate volume (without numpy-stl dependency if possible), estimates weight assuming 1.24 g/cm³ PLA density, then calculates cost using current PLA price (₲30,000/kg default). Includes electricity cost. CLI interface.",
    },
    {
        "name": "vexin_invoice_gen.py",
        "desc": "SET e-Kuatia compatible invoice generator in JSON format. Produces a valid Paraguay electronic invoice (factura electrónica) with required fields: timbrado, RUC, IVA 10%, totals. Outputs both human-readable and machine-readable formats. CLI interface.",
    },
    {
        "name": "vexin_customer_crm.py",
        "desc": "Simple CRM for tracking customers, quotes, and follow-ups. Uses SQLite for storage in /home/vexin/projects/crm.db. Supports: add customer, list customers, add quote, list quotes, mark follow-up done. CLI interface with subcommands. No external dependencies beyond Python stdlib.",
    },
    {
        "name": "vexin_whatsapp_bot.py",
        "desc": "Simple WhatsApp Business webhook handler using Flask. Receives incoming messages, classifies intent (greeting, quote_request, complaint), sends templated responses. Includes sample Flask routes for /webhook and /healthz. No external API calls (mock responses). CLI interface to run server.",
    },
]


def call_ollama(prompt, model="llama3.1:8b", timeout=120):
    """Direct call to local ollama. Bypasses Odysseus."""
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": 3000,
            "temperature": 0.4,
            "num_ctx": 4096,
        },
    })

    try:
        result = subprocess.run(
            ["curl", "-sS", "-X", "POST", "http://localhost:11434/api/generate",
             "-H", "Content-Type: application/json",
             "-d", body, "--max-time", str(timeout)],
            capture_output=True, text=True, timeout=timeout + 10,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("response", "")
    except Exception as e:
        print(f"  ollama err: {e}")
    return None


def extract_code(text):
    """Extract Python code from markdown code blocks."""
    if not text:
        return None
    patterns = [
        r'```python\n(.*?)\n```',
        r'```\n(.*?)\n```',
        r'```py\n(.*?)\n```',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1)
    # No code block - if it looks like python code, return as-is
    if 'def ' in text and 'import' in text:
        return text
    return None


def generate_one(tool):
    """Generate a single tool using direct ollama."""
    name = tool["name"]
    desc = tool["desc"]
    out_path = PROJECTS / name

    # Skip if already exists and substantial
    if out_path.exists() and out_path.stat().st_size > 1000:
        print(f"  ⊙ Already exists ({out_path.stat().st_size} bytes)")
        return True

    print(f"  Generating via llama3.1:8b...")
    prompt = f"""You are an expert Python developer. Write a complete, production-ready Python script.

File to write: {out_path}

Description: {desc}

Requirements:
- Complete working code, no placeholders or TODOs
- Proper imports at top
- Module docstring at top with description and usage example
- if __name__ == '__main__': guard
- argparse for CLI (--help must work)
- Basic error handling with try/except
- Type hints for function signatures
- Shebang line #!/usr/bin/env python3
- Encoding declaration # -*- coding: utf-8 -*-
- No external pip dependencies unless absolutely needed
- Should be runnable as: python3 {name} --help

Output ONLY the Python code in a single ```python code block, no explanations or commentary."""

    start = time.time()
    response = call_ollama(prompt)
    elapsed = time.time() - start

    if not response:
        print(f"  ✗ No response ({elapsed:.1f}s)")
        return False

    code = extract_code(response)
    if not code:
        print(f"  ✗ No code in response ({len(response)} chars, {elapsed:.1f}s)")
        return False

    # Write
    out_path.write_text(code)
    size = len(code)

    # Verify compiles
    try:
        subprocess.run(
            ["python3", "-c", f"import py_compile; py_compile.compile(str({repr(str(out_path))}), doraise=True)"],
            check=True, capture_output=True, timeout=10,
        )
        print(f"  ✓ Written + compiles ({size} chars, {elapsed:.1f}s)")
        return True
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode()[:300] if e.stderr else 'unknown'
        print(f"  ⚠ Written but compile error ({size} chars, {elapsed:.1f}s): {err[:200]}")
        return False


def main():
    log_path = Path("/tmp/gen-tools-direct.log")
    with log_path.open("a") as log:
        log.write(f"\n=== {time.strftime('%H:%M:%S')} STARTING DIRECT OLLAMA TOOL GEN ===\n")

    for tool in TOOLS:
        print(f"\n=== {tool['name']} ===")
        with log_path.open("a") as log:
            log.write(f"\n--- {time.strftime('%H:%M:%S')} {tool['name']} ---\n")
        success = generate_one(tool)
        with log_path.open("a") as log:
            log.write(f"  {'OK' if success else 'FAILED'}\n")

        # Sleep between to let ollama unload if needed
        time.sleep(3)

    print(f"\n=== ALL DONE at {time.strftime('%H:%M:%S')} ===")
    print("\nFiles created:")
    for tool in TOOLS:
        path = PROJECTS / tool["name"]
        if path.exists():
            print(f"  ✓ {tool['name']} ({path.stat().st_size} bytes)")
        else:
            print(f"  ✗ {tool['name']} (not created)")


if __name__ == "__main__":
    main()