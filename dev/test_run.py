#!/usr/bin/env python3
"""
Local test runner for the neuro_hound skill.

Runs the skill locally, directing output to dev/sample_output/
so we don't pollute the workspace archives.

Usage (from project root):
    python dev/test_run.py                    # Full Phase 2 pipeline
    python dev/test_run.py --phase1-only      # Regex only (no LLM cost)
    python dev/test_run.py --days 3
    python dev/test_run.py --model gpt-4o-mini
"""
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILL_RUN = PROJECT_ROOT / "workspace" / "skills" / "neuro_hound" / "run.py"
OUTPUT_DIR = PROJECT_ROOT / "dev" / "sample_output"
ENV_FILE = PROJECT_ROOT / ".env"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Pass through any CLI args plus our output dir
    cmd = [
        sys.executable,
        str(SKILL_RUN),
        "--output-dir", str(OUTPUT_DIR),
    ] + sys.argv[1:]

    # Load .env so API keys are available in subprocess
    env = os.environ.copy()
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                env[key.strip()] = val.strip()

    print(f"=== Local Test Run ===")
    print(f"  Skill:  {SKILL_RUN}")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"  Args:   {' '.join(sys.argv[1:]) or '(defaults)'}")
    print()

    result = subprocess.run(cmd, env=env)

    print()
    if result.returncode == 0:
        reports = sorted(OUTPUT_DIR.glob("*.md"))
        alerts = sorted(OUTPUT_DIR.glob("*.alerts.json"))
        full_json = sorted(OUTPUT_DIR.glob("*.full.json"))
        print(f"=== Test Complete ===")
        print(f"  Reports: {len(reports)}")
        for r in reports[-3:]:
            print(f"    {r.name}")
        print(f"  Alert files: {len(alerts)}")
        for a in alerts[-3:]:
            size = a.stat().st_size
            print(f"    {a.name} ({size} bytes)")
        print(f"  Full JSON: {len(full_json)}")
        for j in full_json[-3:]:
            size = j.stat().st_size
            print(f"    {j.name} ({size} bytes)")
    else:
        print(f"=== Test FAILED (exit code {result.returncode}) ===")

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
