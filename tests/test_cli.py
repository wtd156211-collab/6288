from __future__ import annotations

import contextlib
import io
import os
import shutil
import unittest
from pathlib import Path

from segmerge.cli import main

from .common import ROOT, SAMPLES, WORKLOADS, make_tempdir


class CliTest(unittest.TestCase):
    def run_cli(self, *args, cwd=None):
        old_cwd = os.getcwd()
        if cwd is not None:
            os.chdir(cwd)
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(list(args))
        finally:
            os.chdir(old_cwd)
        return code, out.getvalue(), err.getvalue()

    def test_run_and_read(self):
        with make_tempdir() as tmp:
            code, _, err = self.run_cli(
                "run", str(WORKLOADS / "01-overwrite.tsv"), str(Path(tmp) / "out")
            )
            self.assertEqual(code, 0, err)
            code, out, err = self.run_cli(
                "read", str(Path(tmp) / "out"), "hot:00", cwd=tmp
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(out, "hot:00\tv00000-012\n")
            code, out, _ = self.run_cli(
                "read", str(Path(tmp) / "out"), "missing-key", cwd=tmp
            )
            self.assertEqual(code, 0)
            self.assertEqual(out, "")

    def test_run_invalid_workload_exit_2(self):
        with make_tempdir() as tmp:
            bad = Path(tmp) / "bad.tsv"
            bad.write_text("PUT\tk\tv\n", encoding="utf-8")
            code, _, err = self.run_cli("run", str(bad), str(Path(tmp) / "out"), cwd=tmp)
            self.assertEqual(code, 2)
            self.assertTrue(err.startswith("error:"))

    def test_usage_error(self):
        code, _, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("error:"))
        code, _, err = self.run_cli("nope")
        self.assertEqual(code, 2)

    def test_check_prints_ok(self):
        with make_tempdir() as tmp:
            code, out, _ = self.run_cli("check", str(SAMPLES), cwd=tmp)
            self.assertEqual(code, 0)
            self.assertEqual(out.strip(), "ok=15")

    def test_check_exit_1_on_broken_samples(self):
        with make_tempdir() as tmp:
            fake = Path(tmp) / "samples"
            shutil.copytree(SAMPLES / "workloads", fake / "workloads")
            shutil.copytree(SAMPLES / "expected", fake / "expected")
            marks = fake / "expected" / "01-overwrite.marks.tsv"
            lines = marks.read_text(encoding="utf-8").split("\n")
            lines[1] = "1\t0.500\t3.000\t0.000"
            marks.write_text("\n".join(lines), encoding="utf-8")
            code, out, _ = self.run_cli("check", str(fake), cwd=tmp)
            self.assertEqual(code, 1)
            self.assertIn("mismatch=01-overwrite", out)

    def test_page_writes_self_contained_file(self):
        with make_tempdir() as tmp:
            page = Path(tmp) / "report.html"
            code, _, err = self.run_cli(
                "page", str(SAMPLES), str(page), cwd=tmp
            )
            self.assertEqual(code, 0, err)
            data = page.read_text(encoding="utf-8")
            self.assertIn("<svg", data)
            self.assertNotIn("http://", data)
            self.assertNotIn("https://", data)
            self.assertIn("通过 15", data)

    def test_module_invocation(self):
        import subprocess
        import sys

        with make_tempdir() as tmp:
            env = dict(os.environ)
            env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
            proc = subprocess.run(
                [sys.executable, "-m", "segmerge", "check", str(SAMPLES)],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), "ok=15")


if __name__ == "__main__":
    unittest.main()
