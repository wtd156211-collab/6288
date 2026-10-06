from __future__ import annotations

import os
import unittest

from segmerge.segment import MISSING, decode_segment, encode_segment, load_dir_segments, segment_filename

from .common import make_tempdir


class SegmentTest(unittest.TestCase):
    def test_header_and_record_encoding(self):
        data = encode_segment(2, 7, [("a", "v1"), ("b", None), ("中", "值 x")])
        self.assertEqual(
            data,
            "seg\tL2\t000007\t3\nPUT\ta\tv1\nDEL\tb\nPUT\t中\t值 x\n".encode("utf-8"),
        )

    def test_roundtrip(self):
        records = [("a", "v"), ("b", None)]
        seg = decode_segment(encode_segment(1, 42, records))
        self.assertEqual((seg.level, seg.number, seg.rows), (1, 42, 2))
        self.assertEqual(seg.records, records)
        self.assertEqual((seg.min_key, seg.max_key), ("a", "b"))
        self.assertEqual(seg.tombstones, 1)

    def test_get(self):
        seg = decode_segment(encode_segment(0, 1, [("a", "v"), ("b", None)]))
        self.assertEqual(seg.get("a"), "v")
        self.assertIsNone(seg.get("b"))
        self.assertIs(seg.get("c"), MISSING)

    def test_decode_rejects_bad_files(self):
        with self.assertRaises(ValueError):
            decode_segment(b"seg\tL9\t000001\t0\n")
        with self.assertRaises(ValueError):
            decode_segment(b"seg\tL0\t000001\t1\nPUT\tb\tx\nPUT\ta\ty\n")
        with self.assertRaises(ValueError):
            decode_segment(b"seg\tL0\t000001\t1\nPUT\tk\tv")

    def test_load_dir_segments_order_newest_first(self):
        with make_tempdir() as tmp:
            outdir = tmp
            for number, level in ((2, 0), (1, 0), (3, 1)):
                name = segment_filename(number)
                with open(os.path.join(outdir, name), "wb") as handle:
                    handle.write(encode_segment(level, number, [("k", str(number))]))
            segs = load_dir_segments(outdir)
            order = [(s.level, s.number) for s in segs]
            self.assertEqual(order, [(0, 2), (0, 1), (1, 3)])


if __name__ == "__main__":
    unittest.main()
