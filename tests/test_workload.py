from __future__ import annotations

import unittest

from segmerge.workload import MAX_STEP_OPS, WorkloadError, parse

from .common import WORKLOADS


def workload_bytes(name):
    return (WORKLOADS / (name + ".tsv")).read_bytes()


class WorkloadTest(unittest.TestCase):
    def test_parse_all_samples(self):
        counts = {
            "01-overwrite": (12, 240),
            "04-smallbatch": (40, 87),
            "05-scale": (5, 100000),
        }
        for name, (steps, ops) in counts.items():
            parsed = parse(workload_bytes(name))
            self.assertEqual(len(parsed), steps)
            self.assertEqual(sum(len(step) for step in parsed), ops)

    def test_comment_and_blank_lines_ignored(self):
        steps = parse(b"# comment\n\nSTEP\t1\nPUT\tk\tv\n# x\n")
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0][0].key, "k")
        self.assertEqual(steps[0][0].value, "v")

    def test_op_before_step(self):
        with self.assertRaises(WorkloadError):
            parse(b"PUT\tk\tv\nSTEP\t1\n")

    def test_step_number_must_be_consecutive(self):
        with self.assertRaises(WorkloadError):
            parse(b"STEP\t1\nSTEP\t3\n")

    def test_bad_key(self):
        with self.assertRaises(WorkloadError):
            parse(b"STEP\t1\nPUT\tbad key\tv\n")
        with self.assertRaises(WorkloadError):
            parse(b"STEP\t1\nPUT\t\tv\n")
        with self.assertRaises(WorkloadError):
            parse(b"STEP\t1\nDEL\t" + b"k" * 65 + b"\n")

    def test_bad_value(self):
        with self.assertRaises(WorkloadError):
            parse(b"STEP\t1\nPUT\tk\t\n")
        with self.assertRaises(WorkloadError):
            parse(b"STEP\t1\nPUT\tk\t" + b"v" * 256 + b"\n")

    def test_unknown_line(self):
        with self.assertRaises(WorkloadError):
            parse(b"STEP\t1\nPATCH\tk\tv\n")

    def test_step_too_large(self):
        lines = [b"STEP\t1"] + [b"PUT\tkey%d\tv" % i for i in range(MAX_STEP_OPS + 1)]
        with self.assertRaises(WorkloadError):
            parse(b"\n".join(lines) + b"\n")

    def test_file_too_large(self):
        with self.assertRaises(WorkloadError):
            parse(b"#" * (8 * 1024 * 1024 + 1))

    def test_input_bytes_count_every_op(self):
        steps = parse(b"STEP\t1\nPUT\tk\tv1\nPUT\tk\tv2\nDEL\tk\n")
        total = sum(op.nbytes for op in steps[0])
        self.assertEqual(total, len(b"PUT\tk\tv1\nPUT\tk\tv2\nDEL\tk\n"))


if __name__ == "__main__":
    unittest.main()
