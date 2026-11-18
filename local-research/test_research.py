"""Workflow tests: filesystem gates plus deterministic Harness doubles."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import research

EXAMPLE = Path(__file__).parent / "examples" / "cpu-sequence"
COMPLETED = {
    "status": "completed",
    "best_round": "agent-1",
    "total_rounds": 1,
    "timed_out": False,
    "agent_exit_code": 0,
}


class LocalResearchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.project = self.tmp / "project"
        self.notes = self.tmp / "notes.md"
        self.notes.write_text(
            "Independent review: use the fixed set and exact oracle.", encoding="utf-8"
        )
        self.template = self.tmp / "template"
        shutil.copytree(EXAMPLE / "template", self.template)

    def call(self, command, *args, expected=0):
        capture = io.StringIO()
        with contextlib.redirect_stderr(capture), contextlib.redirect_stdout(capture):
            code = research.main([command, str(self.project), *map(str, args)])
        self.assertEqual(code, expected, capture.getvalue())
        return capture.getvalue()

    def proposal(self):
        self.call("propose")
        shutil.copyfile(EXAMPLE / "proposal.toml", self.project / "proposal.toml")

    def review(self, decision="approve"):
        return self.call("review", "--decision", decision, "--notes", self.notes)

    def build(self, expected=0):
        return self.call(
            "build",
            "--template",
            self.template,
            "--negative-solution",
            EXAMPLE / "negative-solve.sh",
            expected=expected,
        )

    def approved(self):
        self.proposal()
        self.review()
        self.build()

    def read_record(self, name):
        return json.loads((self.project / name).read_text(encoding="utf-8"))

    def test_exact_review_and_no_overwrite(self):
        self.proposal()
        self.call("propose", expected=1)
        self.review("revise")
        self.assertIn("no matching approval", self.build(expected=1))
        self.assertIn("no matching approval", self.call("author", expected=1))
        self.review()
        brief = self.call("author")
        self.assertIn("Approved proposal SHA-256", brief)
        self.assertIn("Fibonacci CLI", brief)
        p = self.project / "proposal.toml"
        p.write_bytes(p.read_bytes() + b"\n# amended\n")
        self.assertIn("no matching approval", self.build(expected=1))
        self.review()
        self.build()
        self.assertIn("already exists", self.build(expected=1))

    def test_rejects_symlinks_and_budget_mismatch(self):
        self.proposal()
        self.review()
        link = self.template / "leak"
        link.symlink_to(self.notes)
        self.assertIn("symlinks", self.build(expected=1))
        link.unlink()
        task = self.template / "task.toml"
        source = task.read_text(encoding="utf-8").replace(
            "timeout_sec = 30\n", "timeout_sec = 31\n"
        )
        task.write_text(source, encoding="utf-8")
        self.assertIn("verifier_timeout_sec", self.build(expected=1))

    def test_recomputed_digests_gate_launch(self):
        self.approved()
        self.call("run", "--agent", "codex", expected=1)
        sample = self.project / "build" / "task" / "instruction.md"
        sample.write_bytes(sample.read_bytes() + b"changed")
        self.assertIn("no longer matches", self.call("validate", expected=1))

    def test_validate_and_run_select_exact_task(self):
        self.approved()
        observed = []

        def runner(task, logs, data, **opts):
            script = (task / "solution" / "solve.sh").read_bytes()
            observed.append((logs, opts, script))
            return {
                **COMPLETED,
                "best_score": (0 if logs.name == "negative" else 1),
            }

        with (
            patch.object(research.harness, "compile_task") as compile_mock,
            patch.object(research.harness, "run_harness", side_effect=runner),
        ):
            self.call("validate")
            compile_mock.assert_called_once()
            self.assertEqual(self.read_record("validation.json")["status"], "passed")
            self.call("run", "--agent", "codex", "--gpus", "0", expected=1)
            self.call("run", "--agent", "codex", "--model", "test")
            self.assertEqual(
                [opts["agent"] for _, opts, _ in observed],
                ["oracle", "oracle", "codex"],
            )
            self.assertEqual(
                [opts["max_submissions"] for _, opts, _ in observed], [1, 1, 2]
            )
            self.assertNotEqual(observed[0][2], observed[1][2])
            self.assertEqual(observed[0][2], observed[2][2])
            # Positive and negative runs never share a logs root.
            self.assertEqual(len(set(log for log, _, _ in observed)), 3)
            self.review()
            self.assertIn(
                "no longer matches", self.call("run", "--agent", "codex", expected=1)
            )

    def test_failed_negative_is_not_zero(self):
        self.approved()
        with (
            patch.object(research.harness, "compile_task"),
            patch.object(
                research.harness,
                "run_harness",
                side_effect=[
                    {**COMPLETED, "best_score": 1},
                    {
                        "status": "no_valid_submission",
                        "best_round": None,
                        "best_score": None,
                    },
                ],
            ),
        ):
            self.assertIn("valid reward score", self.call("validate", expected=1))
        self.assertEqual(self.read_record("validation.json")["status"], "failed")
        self.assertIn(
            "not passed validation", self.call("run", "--agent", "codex", expected=1)
        )

    def test_negative_must_not_pass_the_same_gate(self):
        self.approved()
        with (
            patch.object(research.harness, "compile_task"),
            patch.object(
                research.harness,
                "run_harness",
                return_value={**COMPLETED, "best_score": 1},
            ),
        ):
            self.assertIn("got 1, expected 0", self.call("validate", expected=1))
        self.assertEqual(self.read_record("validation.json")["status"], "failed")

    def test_timed_out_negative_with_zero_cannot_certify_task(self):
        self.approved()
        with (
            patch.object(research.harness, "compile_task"),
            patch.object(
                research.harness,
                "run_harness",
                side_effect=[
                    {**COMPLETED, "best_score": 1},
                    {**COMPLETED, "best_score": 0, "timed_out": True},
                ],
            ),
        ):
            self.assertIn("valid reward score", self.call("validate", expected=1))
        self.assertEqual(self.read_record("validation.json")["status"], "failed")


@unittest.skipUnless(
    os.getenv("RSI_LOCAL_DOCKER") == "1", "set RSI_LOCAL_DOCKER=1 for Docker"
)
class DockerSmokeTest(unittest.TestCase):
    def test_positive_and_negative_use_real_harness(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            notes = Path(temp) / "review.md"
            notes.write_text(
                "Fixed inputs, exact outputs, independent oracle controls.\n",
                encoding="utf-8",
            )
            self.assertEqual(research.main(["propose", str(root)]), 0)
            shutil.copyfile(EXAMPLE / "proposal.toml", root / "proposal.toml")
            self.assertEqual(
                research.main(
                    [
                        "review",
                        str(root),
                        "--decision",
                        "approve",
                        "--notes",
                        str(notes),
                    ]
                ),
                0,
            )
            self.assertEqual(
                research.main(
                    [
                        "build",
                        str(root),
                        "--template",
                        str(EXAMPLE / "template"),
                        "--negative-solution",
                        str(EXAMPLE / "negative-solve.sh"),
                    ]
                ),
                0,
            )
            self.assertEqual(research.main(["validate", str(root), "--verbose"]), 0)
            result = json.loads((root / "validation.json").read_text(encoding="utf-8"))
            self.assertEqual(
                (result["status"], result["oracle_score"], result["negative_score"]),
                ("passed", 1.0, 0.0),
            )


if __name__ == "__main__":
    unittest.main()
