from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from segmerge import checker

from .common import SAMPLES, make_tempdir


class CheckerTest(unittest.TestCase):
    def test_all_samples_pass(self):
        with make_tempdir() as tmp:
            outcomes = checker.check_all(SAMPLES, Path(tmp) / "var")
            self.assertEqual(len(outcomes), 15)
            for outcome in outcomes:
                self.assertTrue(outcome.ok, "%s: %s" % (outcome.name, outcome.problems))

    def test_mismatch_on_broken_expected(self):
        with make_tempdir() as tmp:
            fake_root = Path(tmp) / "samples"
            shutil.copytree(SAMPLES / "workloads", fake_root / "workloads")
            shutil.copytree(SAMPLES / "expected", fake_root / "expected")
            views = fake_root / "expected" / "07-edges.views.txt"
            views.write_bytes(views.read_bytes() + b"# step 3\nbogus\tvalue\n")
            outcome = checker.run_one(
                fake_root, "07-edges", Path(tmp) / "var" / "07-edges"
            )
            self.assertFalse(outcome.ok)
            self.assertTrue(any("视图" in problem for problem in outcome.problems))

    def test_mismatch_on_missing_expected(self):
        with make_tempdir() as tmp:
            fake_root = Path(tmp) / "samples"
            shutil.copytree(SAMPLES / "workloads", fake_root / "workloads")
            shutil.copytree(SAMPLES / "expected", fake_root / "expected")
            (fake_root / "expected" / "07-edges.marks.tsv").unlink()
            outcome = checker.run_one(
                fake_root, "07-edges", Path(tmp) / "var" / "07-edges"
            )
            self.assertFalse(outcome.ok)
            self.assertTrue(any("门槛" in problem for problem in outcome.problems))


if __name__ == "__main__":
    unittest.main()
