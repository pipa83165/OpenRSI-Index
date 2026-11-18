"""Fixed judge for a trusted local smoke test, not an adversarial sandbox."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

CANDIDATE = Path("/workspace/sequence.py")
REWARD = Path("/logs/verifier/reward.json")
CASES = (
    (1, b"1\n"),
    (2, b"1\n"),
    (6, b"8\n"),
    (12, b"144\n"),
    (29, b"514229\n"),
    (100, b"354224848179261915075\n"),
)


def evaluate(candidate: Path) -> int:
    if candidate.is_symlink() or not candidate.is_file():
        return 0
    # Harness needs root to write the controller-owned 0700 log bind. Never
    # grant that identity to candidate code. Non-root host-only tests retain
    # the caller identity.
    identity = (
        {"user": 1000, "group": 1000, "extra_groups": []} if os.geteuid() == 0 else {}
    )
    for given, expected in CASES:
        try:
            result = subprocess.run(
                [sys.executable, "-I", str(candidate), str(given)],
                cwd="/",
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
                **identity,
            )
        except subprocess.TimeoutExpired:
            return 0
        if result.returncode != 0 or result.stdout != expected:
            return 0
    return 1


def main() -> None:
    score = evaluate(CANDIDATE)
    # Publish only a finished score. File/mount failures are infrastructure
    # failures: do not catch them and never substitute a candidate score.
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=REWARD.parent, delete=False
    ) as stream:
        temp = Path(stream.name)
        json.dump({"reward": score}, stream)
        stream.write("\n")
    temp.replace(REWARD)
    print("All fixed cases passed." if score else "The candidate failed Judge.")


if __name__ == "__main__":
    main()
