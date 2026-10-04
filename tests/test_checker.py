"""核对器测试：samples 全量通过；篡改期望后必须报 mismatch。"""

from __future__ import annotations

import pathlib
import shutil
import unittest

from segmerge.checker import check_all, list_workloads
from .common import SAMPLES_ROOT, TempDirTestCase


class CheckSamplesTest(TempDirTestCase):
    def test_all_samples_pass(self):
        results = check_all(str(SAMPLES_ROOT), str(self.tmp / "var"))
        self.assertEqual(len(results), 15)
        for result in results:
            self.assertTrue(result.ok, f"{result.name}: {result.problems}")
        self.assertEqual(sum(r.steps for r in results), 277)


class CheckFailureTest(TempDirTestCase):
    def make_tampered_root(self) -> pathlib.Path:
        root = self.tmp / "samples"
        shutil.copytree(SAMPLES_ROOT, root)
        return root

    def test_tampered_views_detected(self):
        root = self.make_tampered_root()
        views = root / "expected" / "01-overwrite.views.txt"
        views.write_bytes(views.read_bytes() + b"bogus\tline\n")
        results = check_all(str(root), str(self.tmp / "var"))
        by_name = {r.name: r for r in results}
        self.assertFalse(by_name["01-overwrite"].ok)
        self.assertTrue(by_name["02-reclaim"].ok)

    def test_tampered_marks_detected(self):
        root = self.make_tampered_root()
        marks = root / "expected" / "01-overwrite.marks.tsv"
        lines = marks.read_text(encoding="utf-8").splitlines()
        lines[1] = "1\t0.001\t3.000\t0.000"
        marks.write_text("\n".join(lines) + "\n", encoding="utf-8")
        results = check_all(str(root), str(self.tmp / "var"))
        by_name = {r.name: r for r in results}
        self.assertFalse(by_name["01-overwrite"].ok)
        self.assertTrue(
            any("写放大" in p for p in by_name["01-overwrite"].problems)
        )

    def test_list_workloads_sorted(self):
        names = [name for name, _ in list_workloads(str(SAMPLES_ROOT))]
        self.assertEqual(names, sorted(names))
        self.assertEqual(len(names), 15)


if __name__ == "__main__":
    unittest.main()
