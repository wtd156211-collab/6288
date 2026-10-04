"""引擎测试：视图逐字节一致、逐键点查一致、墓碑回收口径、容量不变量。"""

from __future__ import annotations

import pathlib
import unittest

from segmerge.engine import LEVELS, ROW_CAPS, SEG_CAP, Engine, run_workload
from segmerge.workload import load_workload
from .common import (
    WORKLOADS_DIR,
    TempDirTestCase,
    expected_views_bytes,
    workload_path,
)

ALL_NAMES = sorted(path.stem for path in WORKLOADS_DIR.glob("*.tsv"))


class SampleViewsTest(TempDirTestCase):
    def test_views_match_expected_byte_for_byte(self):
        for name in ALL_NAMES:
            with self.subTest(name=name):
                outdir = self.outdir(name)
                run_workload(load_workload(workload_path(name)), str(outdir))
                mine = (outdir / "views.txt").read_bytes()
                self.assertEqual(mine, expected_views_bytes(name))


class PointLookupTest(TempDirTestCase):
    """每步结束后，对至此出现过的每个键点查，结果必须与该步视图一致。"""

    def check_workload(self, name):
        steps = load_workload(workload_path(name))
        engine = Engine(str(self.outdir(name)))
        engine.prepare_outdir()
        seen = set()
        for _step_no, ops in steps:
            engine.apply_step(ops)
            seen.update(key for key, _ in ops)
            view = dict(engine.view())
            for key in seen:
                self.assertEqual(
                    engine.point_get(key),
                    view.get(key),
                    f"{name} 键 {key!r} 点查与视图不一致",
                )

    def test_point_lookups(self):
        for name in ("01-overwrite", "02-reclaim", "08-singlekey", "13-lifecycle"):
            with self.subTest(name=name):
                self.check_workload(name)

    def test_deleted_keys_never_come_back(self):
        steps = load_workload(workload_path("02-reclaim"))
        engine = Engine(str(self.outdir("02")))
        engine.prepare_outdir()
        deleted = set()
        for _step_no, ops in steps:
            engine.apply_step(ops)
            for key, value in ops:
                if value is None:
                    deleted.add(key)
                else:
                    deleted.discard(key)
            for key in deleted:
                self.assertIsNone(engine.point_get(key))


class CapacityInvariantTest(TempDirTestCase):
    def test_limits_hold_after_every_step(self):
        for name in ALL_NAMES:
            with self.subTest(name=name):
                steps = load_workload(workload_path(name))
                engine = Engine(str(self.outdir(name)))
                engine.prepare_outdir()
                for _step_no, ops in steps:
                    engine.apply_step(ops)
                    for level in range(LEVELS):
                        segs = engine.levels[level]
                        self.assertLessEqual(len(segs), SEG_CAP)
                        cap = ROW_CAPS[level]
                        if cap is not None:
                            rows = sum(seg.rows for seg in segs)
                            self.assertLessEqual(rows, cap)


class TombstoneGcTest(TempDirTestCase):
    def make_engine(self, name):
        engine = Engine(str(self.outdir(name)))
        engine.prepare_outdir()
        return engine

    def test_kept_when_older_segment_has_key(self):
        """更旧、未参与合并的段含该键时，墓碑必须保留。"""
        engine = self.make_engine("keep")
        engine._add_segment(2, {"k": "old"})
        engine._add_segment(0, {"k": None})
        engine._merge_once(0)
        self.assertEqual(len(engine.levels[1]), 1)
        self.assertEqual(engine.levels[1][0].records, {"k": None})
        self.assertIsNone(engine.point_get("k"))

    def test_dropped_when_no_older_segment(self):
        """没有更旧的段含该键时，墓碑丢弃；结果为空则不写段。"""
        engine = self.make_engine("drop")
        engine._add_segment(0, {"k": None})
        engine._merge_once(0)
        self.assertEqual(engine.live_segments(), [])
        self.assertEqual(engine.merges, 1)

    def test_kept_across_level_gap(self):
        """墓碑来自被相交拉入的下一层段，更老的 L2 段不参与时仍要保留。"""
        engine = self.make_engine("gap")
        engine._add_segment(2, {"k": "old"})
        engine._add_segment(1, {"k": None, "zz": "1"})
        engine._add_segment(0, {"zz": "2"})
        engine._merge_once(0)
        self.assertEqual(len(engine.levels[1]), 1)
        self.assertEqual(engine.levels[1][0].records, {"k": None, "zz": "2"})
        self.assertIsNone(engine.point_get("k"))

    def test_dropped_when_gap_closed(self):
        """同上但没有更老的段时，墓碑被回收。"""
        engine = self.make_engine("nogap")
        engine._add_segment(1, {"k": None, "zz": "1"})
        engine._add_segment(0, {"zz": "2"})
        engine._merge_once(0)
        self.assertEqual(engine.levels[1][0].records, {"zz": "2"})


class MergeSemanticsTest(TempDirTestCase):
    def test_newest_record_wins(self):
        engine = Engine(str(self.outdir("win")))
        engine.prepare_outdir()
        engine._add_segment(1, {"k": "old"})
        engine._add_segment(0, {"k": "new"})
        engine._merge_once(0)
        self.assertEqual(engine.levels[1][0].records, {"k": "new"})

    def test_row_overflow_takes_oldest_prefix(self):
        """行数越限时从最旧的段开始取，取到剩余回到上限内。"""
        engine = Engine(str(self.outdir("rows")))
        engine.prepare_outdir()
        for idx in range(3):
            engine._add_segment(0, {f"k{idx}{j:04d}": "v" for j in range(600)})
        self.assertTrue(engine._over_limit(0))
        taken = engine._pick_taken(0)
        self.assertEqual([seg.segno for seg in taken], [1, 2])

    def test_count_overflow_takes_whole_level(self):
        engine = Engine(str(self.outdir("count")))
        engine.prepare_outdir()
        for idx in range(9):
            engine._add_segment(0, {f"k{idx}": "v"})
        taken = engine._pick_taken(0)
        self.assertEqual(len(taken), 9)

    def test_empty_step_writes_no_segment(self):
        engine = Engine(str(self.outdir("empty")))
        engine.prepare_outdir()
        engine.apply_step([])
        self.assertEqual(engine.live_segments(), [])
        wa, ra, reclaim = engine.metrics()
        self.assertEqual((wa, ra, reclaim), (0.0, 0.0, 0.0))


class DeterminismTest(TempDirTestCase):
    def test_same_workload_same_bytes(self):
        snapshots = []
        for run_idx in range(2):
            outdir = self.outdir(f"det{run_idx}")
            run_workload(load_workload(workload_path("03-coldhot")), str(outdir))
            snapshots.append(
                {path.name: path.read_bytes() for path in sorted(outdir.iterdir())}
            )
        self.assertEqual(snapshots[0], snapshots[1])


if __name__ == "__main__":
    unittest.main()
