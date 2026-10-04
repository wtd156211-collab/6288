"""测试公共工具：定位 samples/（只读）与临时输出目录。"""

from __future__ import annotations

import pathlib
import shutil
import tempfile
import unittest

SAMPLES_ROOT = pathlib.Path(__file__).resolve().parent.parent / "samples"
WORKLOADS_DIR = SAMPLES_ROOT / "workloads"
EXPECTED_DIR = SAMPLES_ROOT / "expected"
REPO_ROOT = SAMPLES_ROOT.parent


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="segmerge-test-"))
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def outdir(self, name="out") -> pathlib.Path:
        path = self.tmp / name
        path.mkdir(parents=True, exist_ok=True)
        return path


def workload_path(name: str) -> str:
    return str(WORKLOADS_DIR / f"{name}.tsv")


def expected_views_bytes(name: str) -> bytes:
    return (EXPECTED_DIR / f"{name}.views.txt").read_bytes()
