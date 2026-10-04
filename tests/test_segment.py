"""段文件编码/解析与新旧次序测试。"""

from __future__ import annotations

import unittest

from segmerge.segment import (
    Segment,
    encode_segment,
    is_older,
    newer_first,
    parse_segment,
)


class EncodeParseTest(unittest.TestCase):
    def test_header_and_lines(self):
        data = encode_segment(2, 7, {"b": "y", "a": None, "c": "z"})
        lines = data.decode("utf-8").splitlines()
        self.assertEqual(lines[0], "seg\tL2\t000007\t3")
        self.assertEqual(lines[1], "DEL\ta")
        self.assertEqual(lines[2], "PUT\tb\ty")
        self.assertEqual(lines[3], "PUT\tc\tz")

    def test_roundtrip(self):
        records = {"a": "x", "k": None, "z": "值测试"}
        seg = parse_segment(encode_segment(0, 1, records))
        self.assertEqual(seg.level, 0)
        self.assertEqual(seg.segno, 1)
        self.assertEqual(seg.records, records)

    def test_unsorted_rejected(self):
        data = b"seg\tL0\t000001\t2\nPUT\tb\tx\nPUT\ta\ty\n"
        with self.assertRaises(ValueError):
            parse_segment(data)

    def test_row_count_mismatch_rejected(self):
        data = b"seg\tL0\t000001\t5\nPUT\ta\tx\n"
        with self.assertRaises(ValueError):
            parse_segment(data)

    def test_bad_header_rejected(self):
        with self.assertRaises(ValueError):
            parse_segment(b"seg\tX0\t000001\t0\n")

    def test_intersection(self):
        low = Segment(1, 0, {"a": "", "m": ""})
        high = Segment(2, 0, {"m": "", "z": ""})
        disjoint = Segment(3, 0, {"n": "", "z": ""})
        self.assertTrue(low.intersects(high))
        self.assertFalse(low.intersects(Segment(4, 1, {"x": "", "y": ""})))
        self.assertTrue(high.intersects(disjoint))


class OrderingTest(unittest.TestCase):
    def test_newer_first(self):
        l0_old = Segment(1, 0, {})
        l0_new = Segment(3, 0, {})
        l1 = Segment(2, 1, {})
        self.assertEqual(newer_first([l0_old, l1, l0_new]), [l0_new, l0_old, l1])

    def test_is_older(self):
        l0 = Segment(1, 0, {})
        l1 = Segment(1, 1, {})
        self.assertTrue(is_older(l1, l0))
        self.assertFalse(is_older(l0, l1))
        self.assertTrue(is_older(Segment(2, 1, {}), Segment(3, 1, {})))

    def test_tombstone_rows(self):
        seg = Segment(1, 0, {"a": "x", "b": None, "c": None})
        self.assertEqual(seg.tombstone_rows, 2)


if __name__ == "__main__":
    unittest.main()
