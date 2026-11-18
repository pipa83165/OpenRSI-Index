#!/bin/bash
set -eu
cat > /workspace/sequence.py <<'PY'
# Intentionally wrong: emits the next Fibonacci number.
import sys

n = int(sys.argv[1])
a, b = 0, 1
for _ in range(n + 1):
    a, b = b, a + b
print(a)
PY
