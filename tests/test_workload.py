"""负载解析与校验测试（samples/ 只读，非法样例在内存中构造）。"""

from __future__ import annotations

import unittest

from segmerge.workload import WorkloadError, parse_workload_bytes

from .common import workload_path


class ParseWorkloadTest(unittest.TestCase):
    def test_overwrite_step_count(self):
        with open(workload_path("01-overwrite"), "rb") as handle:
            steps = parse_workload_bytes(handle.read())
        self.assertEqual([n for n, _ in steps], list(range(1, 13)))
        self.assertTrue(all(len(ops) == 20 for _, ops in steps))

    def test_comments_and_blank_lines_ignored(self):
        data = "# 注释\n\nSTEP\t1\n# 行内注释位置\nPUT\tk\tv\n"
        steps = parse_workload_bytes(data.encode("utf-8"))
        self.assertEqual(steps, [(1, [("k", "v")])])

    def test_duplicate_keys_kept_in_order(self):
        data = "STEP\t1\nPUT\tk\tv1\nPUT\tk\tv2\nDEL\tk\n"
        steps = parse_workload_bytes(data.encode("utf-8"))
        self.assertEqual(steps, [(1, [("k", "v1"), ("k", "v2"), ("k", None)])])

    def test_empty_step_allowed(self):
        steps = parse_workload_bytes(b"STEP\t1\nSTEP\t2\nPUT\tk\tv\n")
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0][1], [])


class InvalidWorkloadTest(unittest.TestCase):
    def assert_invalid(self, data: bytes):
        with self.assertRaises(WorkloadError):
            parse_workload_bytes(data)

    def test_bad_utf8(self):
        self.assert_invalid(b"STEP\t1\nPUT\tk\t\xff\n")

    def test_cr_line_endings(self):
        self.assert_invalid(b"STEP\t1\r\nPUT\tk\tv\r\n")

    def test_key_with_space(self):
        self.assert_invalid(b"STEP\t1\nPUT\ta b\tv\n")

    def test_key_too_long(self):
        self.assert_invalid(f"STEP\t1\nPUT\t{'k' * 65}\tv\n".encode("utf-8"))

    def test_empty_key(self):
        self.assert_invalid(b"STEP\t1\nPUT\t\tv\n")

    def test_value_too_long(self):
        self.assert_invalid(f"STEP\t1\nPUT\tk\t{'v' * 256}\n".encode("utf-8"))

    def test_empty_value(self):
        self.assert_invalid(b"STEP\t1\nPUT\tk\t\n")

    def test_put_wrong_field_count(self):
        self.assert_invalid(b"STEP\t1\nPUT\tk\n")

    def test_del_wrong_field_count(self):
        self.assert_invalid(b"STEP\t1\nDEL\tk\tv\n")

    def test_step_not_starting_at_one(self):
        self.assert_invalid(b"STEP\t2\nPUT\tk\tv\n")

    def test_step_not_consecutive(self):
        self.assert_invalid(b"STEP\t1\nPUT\tk\tv\nSTEP\t3\nPUT\tx\ty\n")

    def test_op_before_step(self):
        self.assert_invalid(b"PUT\tk\tv\nSTEP\t1\n")

    def test_unknown_directive(self):
        self.assert_invalid(b"STEP\t1\nPATCH\tk\tv\n")

    def test_too_many_ops(self):
        lines = ["STEP\t1"] + ["PUT\tk\tv"] * 20001
        self.assert_invalid(("\n".join(lines) + "\n").encode("utf-8"))

    def test_file_too_big(self):
        self.assert_invalid(b"#" * (8 * 1024 * 1024 + 1))


if __name__ == "__main__":
    unittest.main()
