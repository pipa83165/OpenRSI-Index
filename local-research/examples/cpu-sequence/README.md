# CPU sequence smoke task

This example needs no GPU, model weights, or candidate dependencies. The
official `python:3.12-slim-bookworm` image is a maintained **tag**, not an
immutable digest. The first image build may need a registry pull. Task runtime
networking is disabled.

The image contains the broken starter, not the hidden Judge directory, the
oracle, or the negative control. The positive oracle replaces the starter with
an iterative implementation. The separate `negative-solve.sh` is a deliberately
wrong oracle for checking that Judge can reject a logical failure. It is not
part of the Work template.

Work runs as UID/GID 1000. Judge starts from the clean base image and
reads the submitted workspace. Its controller-owned log bind requires a root
Judge process; candidate Python runs as UID/GID 1000.

This is a local trusted-candidate smoke test. Python isolated mode removes
some ambient Python settings; it is not a security sandbox. Because the
candidate is executable code run by Judge, do not use this fixture as a security
boundary for an untrusted candidate or as a leaderboard benchmark.
