"""Run one enquiry through Eva's brain locally - no Supabase, no mailbox.

Usage:  python -m scripts.run_sample samples/sunny.txt
"""

import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src import decide, reply  # noqa: E402


def load_env():
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def main():
    load_env()
    sample = BASE_DIR / (sys.argv[1] if len(sys.argv) > 1 else "samples/sunny.txt")
    source = sample.read_text()

    decision = decide.assess(source)
    out = reply.build_reply(decision, source)

    print("=" * 70)
    print("DECISION RECORD")
    print("=" * 70)
    print(json.dumps({k: v for k, v in decision.items() if k != "extraction"}, indent=2))
    print()
    print("EXTRACTION LEDGER")
    print("-" * 70)
    for name, f in decision.get("extraction", {}).items():
        if f["value"]:
            print(f"  {name:24s} {f['confidence']:.2f}  {f['value']!r}")
            print(f"  {'':24s}       evidence: {f['evidence']!r}")
    print()
    print("=" * 70)
    print(f"REPLY (send={out['should_send']}, cc={out['cc']}, flags={out['guard_flags']})")
    print("=" * 70)
    print(out["body"])


if __name__ == "__main__":
    main()
