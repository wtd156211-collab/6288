from __future__ import annotations

import os
import unittest
from pathlib import Path

from segmerge.engine import Engine, replay
from segmerge.segment import ROW_LIMITS, SEG_LIMIT
from segmerge.workload import parse

from .common import WORKLOADS, make_tempdir


def load_steps(name):
    return parse((WORKLOADS / (name + ".tsv")).read_bytes())


class MergeSemanticsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tempdir()
        self.engine = Engine(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, level, records):
        return self.engine._write_segment(level, sorted(records))

    def test_tombstone_kept_when_older_outsider_has_key(self):
        # L1 旧段含 k 的 PUT 但不参与合并；L1 新段含 k 的墓碑且与 L0 相交。
        old = self.write(1, [("k", "v1")])
        self.write(1, [("k", None), ("m", "x")])
        for _ in range(9):
            self.write(0, [("m", "y")])
        self.engine._compact()
        live_l1 = [s for s in self.engine.live if s.level == 1]
        self.assertEqual(len(live_l1), 2)
        merged = max(live_l1, key=lambda s: s.number)
        self.assertIn(("k", None), merged.records)  # 墓碑必须保留
        self.assertIsNone(self.engine.get("k"))  # 读出来仍是「不存在」
        self.assertIn(old, self.engine.live)

    def test_tombstone_dropped_when_no_older_outsider(self):
        # 含旧值的 L1 段参与合并，之外没有更旧的段含 k，墓碑可回收。
        self.write(1, [("k", "v1")])
        for _ in range(9):
            self.write(0, [("k", None)])
        self.engine._compact()
        self.assertEqual(self.engine.live, [])  # 墓碑回收后输出为空不写段
        self.assertIsNone(self.engine.get("k"))
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_merge_preserves_reads(self):
        # 合并前后同一批键读结果一致（不变量）。
        self.write(1, [("a", "1"), ("c", "3")])
        for _ in range(9):
            self.write(0, [("a", "2"), ("b", "x")])
        before = {key: self.engine.get(key) for key in ("a", "b", "c", "d")}
        self.engine._compact()
        after = {key: self.engine.get(key) for key in ("a", "b", "c", "d")}
        self.assertEqual(before, after)
        self.assertEqual(after, {"a": "2", "b": "x", "c": "3", "d": None})

    def test_row_overflow_takes_oldest_until_within_caps(self):
        # L0 行数越限：从最旧取到剩余回到上限内，新段留在 L0。
        for part in range(3):
            self.write(0, [("p%d-k%d" % (part, i), "v") for i in range(600)])
        self.engine._compact()
        l0 = [s for s in self.engine.live if s.level == 0]
        self.assertEqual(len(l0), 1)
        self.assertEqual(l0[0].rows, 600)
        l1 = [s for s in self.engine.live if s.level == 1]
        self.assertEqual(sum(s.rows for s in l1), 1200)

    def test_count_overflow_merges_whole_level(self):
        for i in range(9):
            self.write(0, [("key%02d" % i, "v")])
        self.engine._compact()
        self.assertEqual([s.level for s in self.engine.live], [1])

    def test_bottom_level_self_merge(self):
        # L4 段数越限时在本层相交段之间合并，输出仍落 L4。
        for i in range(9):
            self.write(4, [("same", "v%d" % i)])
        self.engine._compact()
        live = self.engine.live
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0].level, 4)
        self.assertEqual(live[0].records, [("same", "v8")])


class ReplayTest(unittest.TestCase):
    def test_point_query_matches_view_every_step(self):
        # 验收口径 2：每步对至此出现过的每个键点查，结果与该步视图一致。
        for name in ("04-smallbatch", "08-singlekey", "13-lifecycle"):
            steps = load_steps(name)
            with self.subTest(name=name), make_tempdir() as tmp:
                engine = Engine(tmp)
                seen = set()
                for ops in steps:
                    engine.apply_step(ops)
                    for op in ops:
                        seen.add(op.key)
                    view = dict(engine.view())
                    for key in seen:
                        self.assertEqual(engine.get(key), view.get(key), "step 内点查不一致")

    def test_capacity_invariants_every_step(self):
        for name in ("01-overwrite", "06-tombstone-gap", "14-mixed"):
            steps = load_steps(name)
            with self.subTest(name=name), make_tempdir() as tmp:
                engine = Engine(tmp)
                for ops in steps:
                    engine.apply_step(ops)
                    for level in range(5):
                        segs = [s for s in engine.live if s.level == level]
                        self.assertLessEqual(len(segs), SEG_LIMIT)
                        cap = ROW_LIMITS[level]
                        if cap is not None:
                            self.assertLessEqual(sum(s.rows for s in segs), cap)

    def test_step_dedup_last_write_wins(self):
        with make_tempdir() as tmp:
            engine = Engine(tmp)
            (ops,) = parse(b"STEP\t1\nPUT\tk\tv1\nDEL\tk\nPUT\tk\tv2\n")
            engine.apply_step(ops)
            self.assertEqual(engine.live[0].records, [("k", "v2")])
            self.assertEqual(engine.user_bytes, len(b"PUT\tk\tv1\nDEL\tk\nPUT\tk\tv2\n"))

    def test_empty_step_writes_no_segment(self):
        with make_tempdir() as tmp:
            engine = Engine(tmp)
            engine.apply_step([])
            self.assertEqual(engine.live, [])
            self.assertEqual(engine.view(), [])

    def test_replay_is_deterministic(self):
        steps = load_steps("03-coldhot")
        with make_tempdir() as dir_a, make_tempdir() as dir_b:
            replay(steps, dir_a)
            replay(steps, dir_b)
            files_a = sorted(os.listdir(dir_a))
            self.assertEqual(files_a, sorted(os.listdir(dir_b)))
            for name in files_a:
                self.assertEqual(
                    Path(dir_a, name).read_bytes(), Path(dir_b, name).read_bytes()
                )


if __name__ == "__main__":
    unittest.main()
