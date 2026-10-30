#!/usr/bin/env python3
"""
add_platforms.py — Declarative Platform Registration & CLI Helper
Provides programmatic and command-line examples for declaring new platforms,
RSS feeds, portal dorks, and filter keywords for SCOUT v4.0.0.
"""

import sys
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SCOUT_AGENT = BASE_DIR / "scout_agent.py"

EXAMPLES = [
    (
        "Declare a new RSS feed or Job Board API",
        [
            sys.executable,
            str(SCOUT_AGENT),
            "add-platform",
            "--name", "MSPJobs Board",
            "--type", "rss_feed",
            "--url", "https://example-msp-board.com/jobs.rss",
            "--track", "Track F: Curated Remote-First & WFA Job Boards",
        ],
    ),
    (
        "Declare a career portal dork",
        [
            sys.executable,
            str(SCOUT_AGENT),
            "add-platform",
            "--name", "Example AI Portal",
            "--type", "portal_dork",
            "--url", "https://example-ai.com/careers",
            "--query", 'site:example-ai.com ("Cloud" OR "DevOps" OR "Python" OR "AI")',
            "--track", "Track B: Async AI Evaluation & RLHF",
        ],
    ),
    (
        "Add a high-signal keyword",
        [sys.executable, str(SCOUT_AGENT), "add-keyword", "terraform"],
    ),
    (
        "Add a hard-exclude filter keyword",
        [sys.executable, str(SCOUT_AGENT), "add-keyword", "on-site only", "--exclude"],
    ),
]


def print_examples() -> None:
    print("=" * 70)
    print("  SCOUT v4.0.0 — Platform & Keyword Declarative Management")
    print("=" * 70)
    print("\nRun these CLI commands directly or execute this script with --demo:\n")
    for title, cmd in EXAMPLES:
        print(f"# {title}:")
        cmd_str = " ".join(f'"{c}"' if " " in c else c for c in cmd[2:])
        print(f"python scout_agent.py {cmd_str}\n")


def run_demo() -> None:
    print("[INFO] Running declarative platform registration examples...")
    for title, cmd in EXAMPLES:
        print(f"\n--> {title}")
        res = subprocess.run(cmd, capture_output=True, text=True)
        print(res.stdout.strip())
        if res.stderr:
            print("[STDERR]", res.stderr.strip())


if __name__ == "__main__":
    if "--demo" in sys.argv:
        run_demo()
    else:
        print_examples()
