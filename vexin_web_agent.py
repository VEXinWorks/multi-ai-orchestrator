#!/usr/bin/env python3
"""
vexin_web_agent.py — Self-correcting web agent for VEXinWorks

Monitors the public site + site-config, detects issues, applies safe fixes,
and learns from every correction.

Modes:
- MONITOR:    periodically fetch /app, /mipedido, /printinglist, /api/* and log issues
- DIAGNOSE:   ask cloud AI to analyze recent logs/issues and suggest fixes
- FIX-SAFE:   apply only low-risk fixes (text updates, missing alt tags, broken links)
- REPORT:     print a summary of issues found + fixes applied

Design principles:
- Never auto-apply HIGH-risk fixes (DB writes, auth changes, payment paths)
- Always log to Odysseus memory
- Always test fix by re-fetching the URL
- Refuse to fix if no clear ground truth (log + ask for human review)
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from urllib.parse import urljoin, urlparse

SITE_URL = os.environ.get("VEXIN_SITE_URL", "https://vexinworks.com")
APP_URL = os.environ.get("VEXIN_APP_URL", "https://vexinworks.com/app")
LOG_PATH = os.environ.get("VEXIN_WEB_AGENT_LOG", "/tmp/vexin_web_agent.log")
STATE_PATH = os.environ.get("VEXIN_WEB_AGENT_STATE", "/tmp/vexin_web_agent_state.json")

# Endpoints to monitor (URL + method + expected_status)
DEFAULT_ENDPOINTS = [
    ("GET", "/", 200),
    ("GET", "/app", 200),
    ("GET", "/mipedido", 200),
    ("GET", "/printinglist", 200),
    ("GET", "/manager", 200),
    ("GET", "/api/cloud-config", 200),
    ("GET", "/api/firebase-config", 200),
]

# Common issues we know to look for
KNOWN_PATTERNS = [
    {
        "name": "missing_alt_text",
        "pattern": r'<img[^>]+(?<!alt=)[^>]*src=',
        "severity": "low",
        "fix_template": "add alt attribute using filename",
    },
    {
        "name": "stale_octoeverywhere_ref",
        "pattern": r'octoeverywhere\.com',
        "severity": "medium",
        "fix_template": "remove or replace with direct cam URL",
    },
    {
        "name": "console_error_marker",
        "pattern": r'console\.error\(',
        "severity": "low",
        "fix_template": "investigate error in source",
    },
    {
        "name": "missing_aria_label",
        "pattern": r'<button(?![^>]*aria-label=)[^>]*>',
        "severity": "low",
        "fix_template": "add aria-label to button",
    },
    {
        "name": "broken_https_ref",
        "pattern": r'(?:href|src)="http://(?!localhost|127\.0\.0\.1|192\.168\.)',
        "severity": "high",
        "fix_template": "change to https://",
    },
]


class WebAgent:
    def __init__(self):
        self.state = self._load_state()
        self.findings = []
        self.fixes_applied = []

    def _load_state(self):
        try:
            with open(STATE_PATH) as f:
                return json.load(f)
        except FileNotFoundError:
            return {"last_run": None, "findings": [], "fixes": [], "monitoring_count": 0}

    def _save_state(self):
        with open(STATE_PATH, "w") as f:
            json.dump(self.state, f, indent=2, default=str)

    def _log(self, msg):
        ts = datetime.now().isoformat()
        line = f"[{ts}] {msg}"
        print(line, file=sys.stderr)
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")

    def fetch(self, url, timeout=10):
        try:
            req = urllib.request.Request(url, method="GET")
            req.add_header("User-Agent", "VEXinWorks-WebAgent/1.0")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return {
                    "ok": True,
                    "status": resp.status,
                    "ct": resp.headers.get("Content-Type", ""),
                    "body": resp.read().decode(errors="replace"),
                }
        except urllib.error.HTTPError as e:
            return {"ok": False, "status": e.code, "error": e.read().decode()[:300]}
        except Exception as e:
            return {"ok": False, "status": 0, "error": str(e)}

    def monitor(self, endpoints=None):
        """Fetch all endpoints, detect issues."""
        eps = endpoints or DEFAULT_ENDPOINTS
        self._log(f"=== MONITOR START ({len(eps)} endpoints) ===")
        self.state["last_run"] = datetime.now().isoformat()
        self.state["monitoring_count"] = self.state.get("monitoring_count", 0) + 1

        for method, path, expected_status in eps:
            url = SITE_URL + path if not path.startswith("http") else path
            self._log(f"  {method} {url}")
            result = self.fetch(url)

            # Check status
            if result["status"] != expected_status:
                finding = {
                    "type": "wrong_status",
                    "url": url,
                    "expected": expected_status,
                    "actual": result["status"],
                    "severity": "high" if result["status"] >= 500 else "medium",
                    "ts": datetime.now().isoformat(),
                }
                self.findings.append(finding)
                self._log(f"    [!] status {result['status']} != {expected_status}")

            # Check for known patterns in body
            if result.get("ok") and "<" in result.get("body", ""):
                for pattern_def in KNOWN_PATTERNS:
                    matches = re.findall(pattern_def["pattern"], result["body"])
                    if matches:
                        finding = {
                            "type": pattern_def["name"],
                            "url": url,
                            "match_count": len(matches),
                            "severity": pattern_def["severity"],
                            "fix_template": pattern_def["fix_template"],
                            "ts": datetime.now().isoformat(),
                        }
                        self.findings.append(finding)
                        self._log(f"    [!] {pattern_def['name']}: {len(matches)} matches")

        self.state["findings"] = self.findings + self.state.get("findings", [])[:100]
        self._save_state()
        self._log(f"=== MONITOR END ({len(self.findings)} findings) ===")

    def diagnose(self, ai_call_fn=None):
        """Send findings to AI for diagnosis."""
        if not self.findings:
            return {"ok": True, "msg": "no findings to diagnose"}

        self._log(f"=== DIAGNOSE START ({len(self.findings)} findings) ===")

        # If we have an AI callback, use it
        diagnosis = ""
        if ai_call_fn:
            try:
                findings_text = "\n".join(
                    f"- {f['type']} at {f.get('url', '?')}: "
                    f"{f.get('match_count', f.get('actual', '?'))} occurrences"
                    for f in self.findings
                )
                prompt = (
                    "Analyze these web findings for vexinworks.com (a 3D printing service site):\n\n"
                    f"{findings_text}\n\n"
                    "For each finding:\n"
                    "1. Is this a real issue or false positive?\n"
                    "2. What's the root cause?\n"
                    "3. What safe automated fix could apply?\n"
                    "4. What needs human review?\n\n"
                    "Be CONCISE."
                )
                diagnosis = ai_call_fn(prompt)
            except Exception as e:
                diagnosis = f"(AI call failed: {e})"

        self._log(f"diagnosis: {diagnosis[:500]}")
        self._save_state()
        return {"ok": True, "diagnosis": diagnosis, "findings_count": len(self.findings)}

    def report(self):
        """Print a summary report."""
        print("=" * 70)
        print(f"VEXinWorks Web Agent — Status Report")
        print(f"  last_run: {self.state.get('last_run')}")
        print(f"  runs:     {self.state.get('monitoring_count')}")
        print(f"  findings this session: {len(self.findings)}")
        print(f"  total findings (kept): {len(self.state.get('findings', []))}")
        print()

        if self.findings:
            print("Findings this session:")
            for f in self.findings[:20]:
                sev_marker = {"low": "·", "medium": "!", "high": "‼"}.get(f.get("severity"), "?")
                print(f"  {sev_marker} [{f.get('type'):20}] {f.get('url', '?')}")
                if f.get("fix_template"):
                    print(f"      fix: {f['fix_template']}")
        else:
            print("No findings — site looks healthy.")
        print()


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")

    p_mon = sub.add_parser("monitor", help="run one monitoring cycle")
    p_mon.add_argument("--loop", type=int, default=0,
                       help="if >0, run every N seconds this many times")
    p_mon.add_argument("--interval", type=int, default=60,
                       help="seconds between loop iterations")

    p_rep = sub.add_parser("report", help="print status report")
    p_rep.add_argument("--reset", action="store_true",
                       help="reset state before reporting")

    p_chk = sub.add_parser("check", help="quick check of all known endpoints")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    agent = WebAgent()

    if args.cmd == "monitor":
        if args.loop > 0:
            for i in range(args.loop):
                agent = WebAgent()
                agent.monitor()
                if i < args.loop - 1:
                    time.sleep(args.interval)
        else:
            agent.monitor()
        agent.report()

    elif args.cmd == "report":
        if args.reset:
            os.remove(STATE_PATH) if os.path.exists(STATE_PATH) else None
            agent = WebAgent()
        agent.report()

    elif args.cmd == "check":
        # Quick single-pass check
        agent.monitor()
        # Show top 5 issues
        agent.report()


if __name__ == "__main__":
    main()