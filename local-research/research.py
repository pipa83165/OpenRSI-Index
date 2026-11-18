#!/usr/bin/env python3
"""Local proposal, review, task packaging, and RSI-Harness gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import stat
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

import harness
import tomllib


class WorkflowError(ValueError):
    pass


PROPOSAL = """\
schema_version = 1
slug = "my-research-task"
title = ""
question = ""
baseline = ""  # Include the source revision, environment and reproduction steps.
candidate_paths = ["/workspace/candidate.py"]
evaluation = ""  # Include the inputs, controls, and timing/scoring protocol.
success_criteria = ""  # Include correctness gates as well as the target metric.
primary_reward = "reward"
score_direction = "maximize"
agent_timeout_sec = 600
verifier_timeout_sec = 120
max_submissions = 2
expected_oracle = 1.0  # Expected control scores, not a universal scoring convention.
expected_negative = 0.0
control_abs_tolerance = 0.0
"""
REQUIRED = {
    "task.toml",
    "instruction.md",
    "tests/test.sh",
    "solution/solve.sh",
}
# Metadata that should not be silently packaged into a candidate environment.
EXCLUDED_NAMES = {".git", ".env", ".venv", "__pycache__"}
VERSION = 1


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def as_json(data: dict) -> str:
    return (
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    )


def write_json(path: Path, data: dict) -> None:
    payload = as_json(data)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        temp = Path(stream.name)
        stream.write(payload)
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def read_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise WorkflowError(f"expected a regular file: {path}")
    return path.read_bytes()


def read_json(path: Path, data: bytes | None = None) -> dict:
    value = json.loads(read_file(path) if data is None else data)
    if not isinstance(value, dict) or value.get("schema_version") != VERSION:
        raise WorkflowError(f"unrecognized record: {path}")
    return value


def load_proposal(root: Path) -> tuple[dict, str]:
    data = read_file(root / "proposal.toml")
    p = tomllib.loads(data.decode("utf-8"))
    if type(p.get("schema_version")) is not int or p["schema_version"] != VERSION:
        raise WorkflowError("proposal schema_version must be 1")
    for key in (
        "slug",
        "title",
        "question",
        "baseline",
        "evaluation",
        "success_criteria",
    ):
        if not isinstance(p.get(key), str) or not p[key].strip():
            raise WorkflowError(f"fill in proposal field: {key}")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", p["slug"]):
        raise WorkflowError(
            "slug must use lowercase letters, digits and single hyphens"
        )
    key = p.get("primary_reward")
    if not isinstance(key, str) or not re.fullmatch(
        r"[A-Za-z0-9_][A-Za-z0-9_.-]*", key
    ):
        raise WorkflowError("primary_reward must be a nonempty metric name")
    if p.get("score_direction") not in ("maximize", "minimize"):
        raise WorkflowError("score_direction must be maximize or minimize")
    paths = p.get("candidate_paths")
    if not isinstance(paths, list) or not paths:
        raise WorkflowError("candidate_paths must be a nonempty list")
    for name in paths:
        if not isinstance(name, str):
            raise WorkflowError("candidate paths must be strings")
        path = PurePosixPath(name)
        if (
            not path.is_absolute()
            or path.anchor != "/"
            or str(path) != name
            or (name == "/" or ".." in path.parts or any(ch.isspace() for ch in name))
        ):
            raise WorkflowError(
                f"candidate path must be a normalized absolute path: {name}"
            )
    if len(set(paths)) != len(paths):
        raise WorkflowError("candidate_paths must be unique")
    for key in ("agent_timeout_sec", "verifier_timeout_sec", "max_submissions"):
        if type(p.get(key)) is not int or p[key] <= 0:
            raise WorkflowError(f"{key} must be a positive integer")
    p.setdefault("control_abs_tolerance", 0.0)
    for key in ("expected_oracle", "expected_negative", "control_abs_tolerance"):
        x = p.get(key)
        if type(x) not in (int, float) or not math.isfinite(x):
            raise WorkflowError(f"{key} must be a finite number")
    tolerance = p["control_abs_tolerance"]
    signed_gap = (p["expected_oracle"] - p["expected_negative"]) * (
        1 if p["score_direction"] == "maximize" else -1
    )
    if tolerance < 0 or signed_gap <= 2 * tolerance:
        raise WorkflowError(
            "control targets must be ordered by score direction and non-overlapping"
        )
    return p, sha(data)


def get_approval(root: Path) -> tuple[dict, str, str]:
    p, proposal_hash = load_proposal(root)
    path = root / "review.json"
    raw = read_file(path)
    review = read_json(path, raw)
    if (
        review.get("decision") != "approve"
        or review.get("proposal_sha256") != proposal_hash
    ):
        raise WorkflowError(
            "current proposal has no matching approval; review it again"
        )
    return p, proposal_hash, sha(raw)


def tree_digest(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise WorkflowError(f"expected a task directory: {root}")
    records: list[list] = []
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.name in EXCLUDED_NAMES or path.name.startswith(".env."):
            raise WorkflowError(
                f"do not package local metadata, caches or credentials: {name}"
            )
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            records.append([name, "directory", stat.S_IMODE(mode)])
        elif stat.S_ISREG(mode):
            with path.open("rb") as f:
                digest = hashlib.file_digest(f, "sha256").hexdigest()
            records.append([name, "file", stat.S_IMODE(mode), digest])
        else:
            raise WorkflowError(f"symlinks and special files are not supported: {name}")
    return sha(as_json({"entries": records}).encode("utf-8"))


def require_task_contract(task: Path, p: dict) -> None:
    for key in sorted(REQUIRED):
        if not read_file(task / key).strip():
            raise WorkflowError(f"empty template file: {key}")
    if not any(
        (task / "environment" / name).is_file()
        for name in (
            "Dockerfile",
            "docker-compose.yaml",
            "docker-compose.yml",
        )
    ):
        raise WorkflowError(
            "template requires an environment Dockerfile or Docker Compose file"
        )
    config = tomllib.loads(read_file(task / "task.toml").decode("utf-8"))
    if config.get("schema_version") != "1.4":
        raise WorkflowError(
            'task.toml must explicitly use Harbor schema_version = "1.4"'
        )
    env = config.get("environment", {})
    workdir = env.get("workdir")
    if not isinstance(workdir, str) or not workdir.startswith("/") or workdir == "/":
        raise WorkflowError(
            "task.toml must specify a non-root absolute environment.workdir"
        )
    root = PurePosixPath(workdir)
    if str(root) != workdir or root.anchor != "/" or ".." in root.parts:
        raise WorkflowError("environment.workdir must be normalized")
    if not all(
        PurePosixPath(name).is_relative_to(root) for name in p["candidate_paths"]
    ):
        raise WorkflowError("proposal candidate paths must be under the task workdir")
    for table, key in (
        ("agent", "agent_timeout_sec"),
        ("verifier", "verifier_timeout_sec"),
    ):
        if config.get(table, {}).get("timeout_sec") != p[key]:
            raise WorkflowError(
                f"task.toml [{table}].timeout_sec must match proposal.{key}"
            )
    verifier = config.get("metadata", {}).get("rsi_harness", {}).get("verifier", {})
    if verifier.get("max_submissions", p["max_submissions"]) != p["max_submissions"]:
        raise WorkflowError("task.toml max_submissions conflicts with proposal")
    if config.get("verifier", {}).get("environment_mode", "shared") != "shared" or (
        verifier.get("clean_image", True) is not True
    ):
        raise WorkflowError(
            "local workflow requires shared Harbor mode and a clean RSI Judge image"
        )
    if verifier.get("visibility", "hidden") != "hidden":
        raise WorkflowError(
            "local workflow expects a hidden verifier; do not bake it into Work"
        )
    metadata = config.get("metadata", {}).get("rsi_harness", {})
    if (
        "sandbox" in metadata
        or verifier.get("model_access")
        or verifier.get("judge_model")
    ):
        raise WorkflowError(
            "managed child sandboxes and model-backed Judges are outside v1"
        )


def identity(record: dict) -> dict:
    return {
        k: record[k]
        for k in ("proposal_sha256", "review_sha256", "task_sha256", "negative_sha256")
    }


def checked_bundle(root: Path) -> tuple[dict, Path, Path, dict]:
    p, proposal_hash, review_hash = get_approval(root)
    build = root / "build"
    record = read_json(build / "manifest.json")
    task, negative = build / "task", build / "negative-solve.sh"
    if identity(record) != {
        "proposal_sha256": proposal_hash,
        "review_sha256": review_hash,
        "task_sha256": tree_digest(task),
        "negative_sha256": sha(read_file(negative)),
    }:
        raise WorkflowError(
            "build no longer matches reviewed proposal or packaged files; rebuild"
        )
    require_task_contract(task, p)
    return p, task, negative, record


def do_propose(args: argparse.Namespace, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with (root / "proposal.toml").open("x", encoding="utf-8") as f:
        f.write(PROPOSAL)
    print(root / "proposal.toml")


def do_review(args: argparse.Namespace, root: Path) -> None:
    _, digest = load_proposal(root)
    notes = read_file(args.notes).decode("utf-8").strip()
    if not notes:
        raise WorkflowError("review notes must not be empty")
    write_json(
        root / "review.json",
        {
            "schema_version": VERSION,
            "recorded_at": now(),
            "proposal_sha256": digest,
            "decision": args.decision,
            "notes": notes,
        },
    )
    print(f"Recorded {args.decision} for proposal {digest[:12]}")


def do_author(args: argparse.Namespace, root: Path) -> None:
    """Render the approved handoff for a separate task-authoring session."""
    p, digest, _ = get_approval(root)
    raw = read_file(root / "proposal.toml")
    if sha(raw) != digest:
        raise WorkflowError("proposal changed while preparing the authoring handoff")
    print(f"""# Local Harbor task authoring brief: {p["slug"]}

Approved proposal SHA-256: {digest}

Use Harbor's official harbor-task-creator skill to prepare a task template
compatible with this checkout's RSI-Harness. You are the task author, not the
optimizer. Do not alter the approved experiment, publish files, or start a
research run. Ask for a new review if the approved design needs to change.

Create a template with task.toml (schema 1.4), instruction.md, environment/,
tests/test.sh, and solution/solve.sh. Use a non-root absolute Work directory
with a hidden verifier and clean Judge image. Verify the proposal's allowed
changes in the evaluator when appropriate. Prepare a separate negative
solution that terminates normally but makes a deliberately incorrect
candidate. Do not package that script into Work or the task template.

Treat the following proposal as the experiment specification:

{raw.decode("utf-8").rstrip()}
""")


def do_build(args: argparse.Namespace, root: Path) -> None:
    p, proposal_hash, review_hash = get_approval(root)
    dst = root / "build"
    if dst.exists() or dst.is_symlink():
        raise WorkflowError(
            "build already exists; archive it under a different name before rebuilding"
        )
    source = args.template.absolute()
    if source.resolve().is_relative_to(dst) or dst.is_relative_to(source.resolve()):
        raise WorkflowError(
            "template must not contain or be contained by the build destination"
        )
    if args.negative_solution.resolve().is_relative_to(source.resolve()):
        raise WorkflowError("negative control script must be outside the task template")
    original_digest = tree_digest(source)
    negative = read_file(args.negative_solution)
    if not negative.strip():
        raise WorkflowError("negative control script must not be empty")
    if negative == read_file(source / "solution" / "solve.sh"):
        raise WorkflowError("negative control must differ from the oracle solution")
    with tempfile.TemporaryDirectory(prefix=".build-", dir=root) as tmp:
        stage = Path(tmp) / "build"
        stage.mkdir()
        task = shutil.copytree(source, stage / "task", symlinks=True)
        task_hash = tree_digest(task)
        if task_hash != original_digest:
            raise WorkflowError("template changed during packaging")
        require_task_contract(task, p)
        if get_approval(root)[1:] != (proposal_hash, review_hash):
            raise WorkflowError("approval changed during packaging")
        (stage / "negative-solve.sh").write_bytes(negative)
        write_json(
            stage / "manifest.json",
            {
                "schema_version": VERSION,
                "created_at": now(),
                "slug": p["slug"],
                "proposal_sha256": proposal_hash,
                "review_sha256": review_hash,
                "task_sha256": task_hash,
                "negative_sha256": sha(negative),
            },
        )
        stage.rename(dst)
    print(f"Packaged {dst / 'task'} (not yet validated)")


def new_attempt(root: Path, label: str) -> Path:
    key = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
    dest = root / label / key
    dest.mkdir(parents=True, exist_ok=False)
    return dest


def run_options(p: dict, args: argparse.Namespace) -> dict:
    return {
        "primary_reward": p["primary_reward"],
        "score_direction": p["score_direction"],
        "max_submissions": p["max_submissions"],
        "gpus": args.gpus,
        "verbose": args.verbose,
    }


def control_has_score(result: dict, key: str, target: float, tolerance: float) -> float:
    score = result.get("best_score")
    # A genuinely completed negative control may be zero. Missing/failed is not zero.
    if (
        result.get("status") != "completed"
        or result.get("total_rounds") != 1
        or result.get("timed_out") is not False
        or type(result.get("agent_exit_code")) is not int
        or result["agent_exit_code"] != 0
        or not result.get("best_round")
    ) or (type(score) not in (int, float) or not math.isfinite(score)):
        raise WorkflowError(f"control did not complete with a valid {key} score")
    if not math.isclose(score, target, rel_tol=0.0, abs_tol=tolerance):
        raise WorkflowError(
            f"control {key}: got {score:g}, expected {target:g} ± {tolerance:g}"
        )
    return float(score)


def do_validate(args: argparse.Namespace, root: Path) -> None:
    p, task, negative, record = checked_bundle(root)
    attempt = new_attempt(root, "validation-runs")
    validation = {
        "schema_version": VERSION,
        "attempt": attempt.name,
        **identity(record),
        "status": "running",
        "gpus": args.gpus,
    }
    state = root / "validation.json"
    write_json(state, validation)
    try:
        harness.compile_task(task)
        opts = run_options(p, args)
        # Control runs use one final judging round for their known submissions.
        opts["max_submissions"] = 1
        for name, target in (
            ("oracle", p["expected_oracle"]),
            ("negative", p["expected_negative"]),
        ):
            with tempfile.TemporaryDirectory(
                prefix=f"control-{name}-", dir=attempt
            ) as tmp:
                control = shutil.copytree(task, Path(tmp) / p["slug"], symlinks=True)
                if tree_digest(control) != record["task_sha256"]:
                    raise WorkflowError(
                        "task package changed while making validation copy"
                    )
                if name == "negative":
                    read = read_file(negative)
                    if sha(read) != record["negative_sha256"]:
                        raise WorkflowError("negative control changed after packaging")
                    (control / "solution" / "solve.sh").write_bytes(read)
                result = harness.run_harness(
                    control,
                    attempt / name,
                    root / ".harness-data",
                    agent="oracle",
                    **opts,
                )
                validation[f"{name}_score"] = control_has_score(
                    result,
                    p["primary_reward"],
                    target,
                    p["control_abs_tolerance"],
                )
        if identity(checked_bundle(root)[3]) != identity(record):
            raise WorkflowError("task or approval changed during validation")
    except (Exception, KeyboardInterrupt) as exc:
        validation.update(status="failed", error=str(exc), finished_at=now())
        write_json(state, validation)
        raise
    validation.update(status="passed", finished_at=now())
    write_json(state, validation)
    print(f"Validated {task}; evidence: {attempt}")


def do_run(args: argparse.Namespace, root: Path) -> None:
    p, task, _, record = checked_bundle(root)
    validation = read_json(root / "validation.json")
    if validation.get("status") != "passed" or identity(validation) != identity(record):
        raise WorkflowError("this exact task build has not passed validation")
    if validation.get("gpus") != args.gpus:
        raise WorkflowError(
            "GPU selection changed; revalidate with the intended --gpus value"
        )
    if args.agent == "oracle":
        raise WorkflowError("use validate for oracle controls, not run")
    attempt = new_attempt(root, "research-runs")
    run_record = {
        "schema_version": VERSION,
        "started_at": now(),
        "status": "running",
        **identity(record),
        "validation_attempt": validation["attempt"],
        "agent": args.agent,
        "model": args.model,
        "gpus": args.gpus,
    }
    state = attempt / "research-run.json"
    write_json(state, run_record)
    try:
        snapshot = shutil.copytree(task, attempt / "task", symlinks=True)
        if tree_digest(snapshot) != record["task_sha256"]:
            raise WorkflowError("task package changed before launching the run")
        result = harness.run_harness(
            snapshot,
            attempt / "logs",
            root / ".harness-data",
            agent=args.agent,
            model=args.model,
            **run_options(p, args),
        )
    except (Exception, KeyboardInterrupt) as exc:
        write_json(
            state,
            {**run_record, "status": "failed", "finished_at": now(), "error": str(exc)},
        )
        raise
    write_json(
        state,
        {
            **run_record,
            "status": result.get("status", "unknown"),
            "finished_at": now(),
            "best_score": result.get("best_score"),
            "best_round": result.get("best_round"),
        },
    )
    print(f"Run status: {result.get('status')}; best score: {result.get('best_score')}")
    print(f"Evidence: {attempt}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    for name, fn in (
        ("propose", do_propose),
        ("review", do_review),
        ("author", do_author),
        ("build", do_build),
        ("validate", do_validate),
        ("run", do_run),
    ):
        command = subs.add_parser(name)
        command.add_argument("directory", type=Path)
        command.set_defaults(action=fn)
        if name == "review":
            command.add_argument(
                "--decision", choices=("approve", "revise"), required=True
            )
            command.add_argument("--notes", type=Path, required=True)
        if name == "build":
            command.add_argument("--template", type=Path, required=True)
            command.add_argument("--negative-solution", type=Path, required=True)
        if name in {"validate", "run"}:
            command.add_argument("--gpus", help="local GPU indexes/UUIDs; omit for CPU")
            command.add_argument(
                "--verbose", action="store_true", help="show native Harness errors"
            )
        if name == "run":
            command.add_argument("--agent", required=True)
            command.add_argument("--model")
    args = parser.parse_args(argv)
    try:
        args.action(args, args.directory.resolve())
    except KeyboardInterrupt:
        print("Interrupted; existing local evidence was kept.", file=sys.stderr)
        return 130
    except (
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        RuntimeError,
    ) as exc:
        print(f"research {args.command}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
