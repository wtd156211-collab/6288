"""CLI 测试：run/read/check/page 的行为与退出码。"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest

from .common import REPO_ROOT, SAMPLES_ROOT, TempDirTestCase, workload_path


def run_cli(*args, cwd=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-m", "segmerge", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
    )


class RunReadTest(TempDirTestCase):
    def test_run_then_read(self):
        outdir = self.tmp / "out"
        result = run_cli("run", workload_path("07-edges"), str(outdir))
        self.assertEqual(result.returncode, 0, result.stderr)
        hit = run_cli("read", str(outdir), "x|y")
        self.assertEqual(hit.returncode, 0)
        self.assertEqual(hit.stdout, "x|y\tagain-0\n")
        deleted = run_cli("read", str(outdir), "!")
        self.assertEqual(deleted.returncode, 0)
        self.assertEqual(deleted.stdout, "")
        absent = run_cli("read", str(outdir), "no-such-key")
        self.assertEqual(absent.returncode, 0)
        self.assertEqual(absent.stdout, "")

    def test_read_invalid_key(self):
        result = run_cli("read", str(self.tmp), "has space")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith("error: "))

    def test_read_missing_dir(self):
        result = run_cli("read", str(self.tmp / "nope"), "k")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith("error: "))


class CheckCommandTest(TempDirTestCase):
    def test_check_ok(self):
        result = run_cli("check", str(SAMPLES_ROOT), cwd=str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok=15")
        self.assertTrue((self.tmp / "var" / "01-overwrite" / "report.tsv").exists())

    def test_check_missing_root(self):
        result = run_cli("check", str(self.tmp / "nope"), cwd=str(self.tmp))
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith("error: "))


class UsageTest(unittest.TestCase):
    def test_no_args(self):
        result = run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith("error: "))

    def test_unknown_command(self):
        result = run_cli("frobnicate")
        self.assertEqual(result.returncode, 2)

    def test_run_missing_workload(self):
        result = run_cli("run", "/no/such/file.tsv", "/tmp/segmerge-nope")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith("error: "))

    def test_run_invalid_workload(self):
        import tempfile

        with tempfile.NamedTemporaryFile(
            "wb", suffix=".tsv", delete=False
        ) as handle:
            handle.write(b"STEP\t9\nPUT\tk\tv\n")
            path = handle.name
        result = run_cli("run", path, "/tmp/segmerge-invalid")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith("error: "))


class PageCommandTest(TempDirTestCase):
    def test_page_written(self):
        out_html = self.tmp / "page.html"
        result = run_cli(
            "page", str(SAMPLES_ROOT), str(out_html), cwd=str(self.tmp)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(out_html.exists())
        text = out_html.read_text(encoding="utf-8")
        self.assertIn("<svg", text)


if __name__ == "__main__":
    unittest.main()
