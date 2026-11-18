"""Unit tests for the local Harness process and artifact boundary."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import HarnessError, run_harness


class HarnessBackendTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.task = self.root / "task with spaces"
        self.task.mkdir()
        self.logs = self.root / "logs"
        self.data = self.root / "data"

    def _run(self, **options):
        return run_harness(
            self.task,
            self.logs,
            self.data,
            agent="oracle",
            primary_reward="score",
            score_direction="minimize",
            max_submissions=1,
            **options,
        )

    def _artifact(self, run_id, text):
        path = self.logs / "runs" / run_id / self.task.name / "final_result.json"
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8")

    def _process(self, files, returncode=0):
        def process(command, *, check):
            self.assertFalse(check)
            for run_id, text in files.items():
                self._artifact(run_id, text)
            return subprocess.CompletedProcess(command, returncode=returncode)

        return patch("harness.subprocess.run", side_effect=process)

    def test_passes_argv_and_reads_nested_result(self):
        result = {"status": "completed", "total_rounds": 1, "best_score": 2.5}
        with self._process({"run-a": json.dumps(result)}) as process:
            self.assertEqual(self._run(gpus="0,2", model="model-name"), result)
        argv = process.call_args.args[0]
        self.assertEqual(
            argv,
            [
                sys.executable,
                "-m",
                "rsi_harness.cli",
                "run",
                str(self.task),
                f"--logs-root={self.logs}",
                f"--data-root={self.data}",
                "--agent=oracle",
                "--primary-reward=score",
                "--score-direction=minimize",
                "--max-submissions=1",
                "--gpus=0,2",
                "--model=model-name",
            ],
        )

    def test_refuses_preexisting_run_artifact(self):
        self._artifact("old-run", '{"status": "completed", "total_rounds": 1}')
        with patch("harness.subprocess.run") as process:
            with self.assertRaisesRegex(HarnessError, "reserve fresh Harness logs"):
                self._run()
        process.assert_not_called()

    def test_rejects_multiple_run_artifacts(self):
        raw = '{"status": "completed", "total_rounds": 1}'
        with self._process({"run-a": raw, "run-b": raw}):
            with self.assertRaisesRegex(HarnessError, "found 2"):
                self._run()

    def test_rejects_invalid_result(self):
        with self._process({"run-a": '{"status":"completed","total_rounds":true}'}):
            with self.assertRaisesRegex(HarnessError, "valid total_rounds"):
                self._run()

    def test_preserves_nonzero_exit_even_when_result_is_parseable(self):
        result = {"status": "completed", "total_rounds": 1, "best_score": 99}
        with self._process({"run-a": json.dumps(result)}, returncode=1):
            with self.assertRaises(HarnessError) as caught:
                self._run()
        self.assertEqual(caught.exception.returncode, 1)
        self.assertEqual(caught.exception.result, result)


if __name__ == "__main__":
    unittest.main()
