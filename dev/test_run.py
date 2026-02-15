#!/usr/bin/env python3
"""
Local test runner for the neuro_hound skill.

Runs the skill locally, directing output to dev/sample_output/
so we don't pollute the workspace archives.

Usage (from project root):
    python dev/test_run.py
    python dev/test_run.py --days 3
    python dev/test_run.py --days 14 --max 60
"""
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILL_RUN = PROJECT_ROOT / "workspace" / "skills" / "neuro_hound" / "run.py"
OUTPUT_DIR = PROJECT_ROOT / "dev" / "sample_output"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Pass through any CLI args (--days, --max) plus our output dir
    cmd = [
        sys.executable,
        str(SKILL_RUN),
        "--output-dir", str(OUTPUT_DIR),
    ] + sys.argv[1:]

    print(f"=== Local Test Run ===")
    print(f"  Skill:  {SKILL_RUN}")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"  Args:   {' '.join(sys.argv[1:]) or '(defaults)'}")
    print()

    result = subprocess.run(cmd)

    print()
    if result.returncode == 0:
        # Show what was generated
        reports = sorted(OUTPUT_DIR.glob("*.md"))
        alerts = sorted(OUTPUT_DIR.glob("*.alerts.json"))
        print(f"=== Test Complete ===")
        print(f"  Reports: {len(reports)}")
        for r in reports[-3:]:
            print(f"    {r.name}")
        print(f"  Alert files: {len(alerts)}")
        for a in alerts[-3:]:
            size = a.stat().st_size
            print(f"    {a.name} ({size} bytes)")
    else:
        print(f"=== Test FAILED (exit code {result.returncode}) ===")

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
