"""Adapter for the bundled RSI Harness in an already configured Python environment."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


class HarnessError(RuntimeError):
    """Harness failed to run, or did not produce an unambiguous final result."""

    def __init__(
        self, message: str, *, returncode: int | None = None, result: dict | None = None
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.result = result


def compile_task(task: Path) -> None:
    """Validate the Harbor source with the real compiler; do not build an image."""
    try:
        from rsi_harness.errors import HarnessError as CompilerError
        from rsi_harness.models import CompileOptions
        from rsi_harness.task.compiler import HarborTaskCompiler
    except ImportError as error:
        raise HarnessError(
            "RSI Harness is not importable. Use a Python environment with the "
            "bundled RSI-Harness and its dependencies installed."
        ) from error

    try:
        HarborTaskCompiler().compile(task.expanduser().resolve(), CompileOptions())
    except (CompilerError, ValueError, OSError) as error:
        raise HarnessError(f"Harbor task validation failed: {error}") from error


def _read_result(logs: Path) -> dict:
    root = logs / "runs"
    if not root.is_dir() or root.is_symlink():
        raise ValueError("no Harness runs directory was produced")
    # ArtifactWriter stores logs under runs/<run_id>/<task_id>/.
    candidates = []
    for run in root.iterdir():
        if run.is_symlink() or not run.is_dir():
            continue
        for task_dir in run.iterdir():
            if task_dir.is_symlink() or not task_dir.is_dir():
                continue
            artifact = task_dir / "final_result.json"
            if artifact.is_file() and not artifact.is_symlink():
                candidates.append(artifact)
    if len(candidates) != 1:
        raise ValueError(
            f"expected one fresh final_result.json, found {len(candidates)}"
        )

    def reject_nonfinite(value: str) -> None:
        raise ValueError(f"nonstandard JSON number {value}")

    result = json.loads(
        candidates[0].read_text(encoding="utf-8"), parse_constant=reject_nonfinite
    )
    if not isinstance(result, dict):
        raise ValueError("final_result.json does not contain an object")
    if result.get("status") not in (
        "completed",
        "no_valid_submission",
        "failed",
        "cancelled",
    ):
        raise ValueError("final_result.json does not contain a terminal Harness status")
    rounds = result.get("total_rounds")
    if type(rounds) is not int or rounds < 0:
        raise ValueError("final_result.json does not contain a valid total_rounds")
    return result


def run_harness(
    task: Path,
    logs: Path,
    data: Path,
    *,
    agent: str,
    primary_reward: str,
    score_direction: str,
    max_submissions: int,
    gpus: str | None = None,
    model: str | None = None,
    verbose: bool = False,
) -> dict:
    """Launch the local Harness CLI, stream its output, and return the fresh result.

    The caller must supply a distinct log root for every invocation. Nonzero
    exits raise HarnessError even when evidence exists; the error carries the
    original exit code and any uniquely identifiable, parseable final result.
    A zero exit does not imply the run scored (normal agents may have no valid
    submission), nor does any Harness exit code assert a task-specific threshold.
    """
    task, logs, data = (path.expanduser().resolve() for path in (task, logs, data))
    if not task.is_dir():
        raise HarnessError(f"Harbor task directory does not exist: {task}")
    if any(path == task or task in path.parents for path in (logs, data)):
        raise HarnessError("Harness logs and data must be outside the Harbor task")
    try:
        # Exclusively reserve the artifact subtree to reject prior/concurrent runs.
        # Harness creates descendants itself and accepts an empty runs directory.
        (logs / "runs").mkdir(parents=True, exist_ok=False)
    except OSError as error:
        raise HarnessError(
            f"Cannot reserve fresh Harness logs at {logs}: {error}"
        ) from error

    command = [
        sys.executable,
        "-m",
        "rsi_harness.cli",
        "run",
        str(task),
        f"--logs-root={logs}",
        f"--data-root={data}",
        f"--agent={agent}",
        f"--primary-reward={primary_reward}",
        f"--score-direction={score_direction}",
        f"--max-submissions={max_submissions}",
    ]
    if gpus:
        command.append(f"--gpus={gpus}")
    if model:
        command.append(f"--model={model}")
    if verbose:
        command.append("--verbose")
    try:
        completed = subprocess.run(command, check=False)
    except OSError as error:
        raise HarnessError(f"Could not start RSI Harness: {error}") from error
    try:
        result = _read_result(logs)
    except (OSError, ValueError) as error:
        raise HarnessError(
            f"Harness exited {completed.returncode} without a usable result in {logs}: {error}",
            returncode=completed.returncode,
        ) from error
    if completed.returncode != 0:
        raise HarnessError(
            f"Harness exited {completed.returncode} (status: {result['status']}); "
            f"see {logs} and the CLI output",
            returncode=completed.returncode,
            result=result,
        )
    if result["status"] in ("failed", "cancelled"):
        raise HarnessError(
            f"Harness reported {result['status']} despite exit 0; see {logs}",
            returncode=completed.returncode,
            result=result,
        )
    return result
