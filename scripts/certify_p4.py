#!/usr/bin/env python3
"""P4 certification helper. Local evaluation is required; hosted adversarial tests are not forced."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    print("P4 certification classes:")
    print("LOCAL_DETERMINISTIC: scripts/evaluate_p4.py (26 authority properties)")
    print("HOSTED_SAFE: GET /demo and POST /demo/run against the public bounded target")
    print("HOSTED_NOT_FORCED_FOR_SAFETY: production Bedrock destruction; concurrent live refresh races")
    return subprocess.call([sys.executable, str(ROOT / "scripts" / "evaluate_p4.py")], cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
