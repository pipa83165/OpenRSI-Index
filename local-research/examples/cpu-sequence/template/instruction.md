# Fibonacci CLI smoke task

Change only `/workspace/sequence.py`. Given one command-line integer
`n` with `0 <= n <= 100`, print the exact integer `F(n)` followed
by one newline and nothing else. The recurrence is `F(0) = 0`,
`F(1) = 1`, and `F(n) = F(n-1) + F(n-2)` for `n >= 2`.
Use only the Python standard library.

Public examples: `python sequence.py 0` prints `0`,
`python sequence.py 5` prints `5`, and `python sequence.py 8`
prints `21`. The starter is deliberately wrong on some inputs.

Test locally, finish writing your candidate, then use `rsi-submit`.
Judge checks other inputs and returns reward 1 if every invocation exits
successfully with the exact expected stdout, or 0 for an invalid candidate.
A Judge infrastructure error does not produce a reward.
