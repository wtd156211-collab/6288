"""测试公共件：定位 samples，准备临时输出目录。"""
from __future__ import annotations

import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
WORKLOADS = SAMPLES / "workloads"
EXPECTED = SAMPLES / "expected"


def make_tempdir():
    return tempfile.TemporaryDirectory()
