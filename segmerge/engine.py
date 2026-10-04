"""重放与合并引擎。

一次 run 逐步重放：读入该步操作（同键多条只有最后一条生效，但每条都计入
输入字节）；该步非空就落盘成 L0 段；反复找层号最小的越限层做一次合并，
直到没有越限层；最后写该步视图与指标。

合并口径（写死，不许换）：行数越限就从最旧的段开始取，取到剩下的段数与
行数都回到上限内（至少 1 段）；只是段数越限就取该层全部段。输入 = 取出
的段 + 下一层里键区间与之有交的段（最底层改成本层相交的其它段）。同键
只留最新的一条，输出按键升序写成一个新段，落到 min(层号+1, 4) 层。

墓碑回收：输出里的墓碑，只有当「比它所在的输入段更旧、又没参与本次合并
的段」都不含该键时才丢掉，否则原样保留。拿不准就保留。
"""

from __future__ import annotations

import os

from .segment import (
    Segment,
    is_older,
    is_seg_filename,
    newer_first,
    remove_segment,
    write_segment,
)
from .workload import op_encoded_bytes

LEVELS = 5
ROW_CAPS = (1024, 8192, 65536, 524288, None)  # L4 行数不限
SEG_CAP = 8

REPORT_HEADER = (
    "step ops user_bytes disk_bytes live_bytes wa ra reclaim view_lines "
    "L0_segs L0_rows L1_segs L1_rows L2_segs L2_rows L3_segs L3_rows "
    "L4_segs L4_rows merges"
)
LAYOUT_HEADER = "step level segno rows tombstones bytes"


def fmt3(value: float) -> str:
    return format(value, ".3f")


class Engine:
    """单个输出目录上的一次重放。"""

    def __init__(self, outdir: str):
        self.outdir = outdir
        self.levels: list = [[] for _ in range(LEVELS)]
        self.next_segno = 1
        self.user_bytes = 0
        self.disk_bytes = 0
        self.merges = 0

    def prepare_outdir(self) -> None:
        os.makedirs(self.outdir, exist_ok=True)
        for name in os.listdir(self.outdir):
            if is_seg_filename(name) or name in (
                "report.tsv",
                "views.txt",
                "layout.tsv",
            ):
                os.remove(os.path.join(self.outdir, name))

    def _add_segment(self, level: int, records: dict) -> Segment:
        seg = write_segment(self.outdir, level, self.next_segno, records)
        self.next_segno += 1
        self.disk_bytes += seg.nbytes
        level_segs = self.levels[level]
        level_segs.append(seg)
        level_segs.sort(key=lambda item: item.segno)
        return seg

    def _drop_segment(self, seg: Segment) -> None:
        self.levels[seg.level].remove(seg)
        remove_segment(self.outdir, seg.segno)

    def live_segments(self) -> list:
        return [seg for level_segs in self.levels for seg in level_segs]

    def live_bytes(self) -> int:
        return sum(seg.nbytes for seg in self.live_segments())

    def apply_step(self, ops: list) -> None:
        """落盘该步（如非空）并合并到收敛。ops 为 [(键, 值|None), ...]。"""
        self.user_bytes += sum(op_encoded_bytes(key, value) for key, value in ops)
        if ops:
            records: dict = {}
            for key, value in ops:
                records[key] = value  # 同键多条只有最后一条生效
            self._add_segment(0, records)
        self.compact()

    def _level_rows(self, level: int) -> int:
        return sum(seg.rows for seg in self.levels[level])

    def _over_limit(self, level: int) -> bool:
        if len(self.levels[level]) > SEG_CAP:
            return True
        cap = ROW_CAPS[level]
        return cap is not None and self._level_rows(level) > cap

    def compact(self) -> None:
        while True:
            for level in range(LEVELS):
                if self._over_limit(level):
                    self._merge_once(level)
                    break
            else:
                return

    def _pick_taken(self, level: int) -> list:
        segs = self.levels[level]  # 段号升序，最旧在前
        cap = ROW_CAPS[level]
        rows = sum(seg.rows for seg in segs)
        if cap is not None and rows > cap:
            taken: list = []
            rest_rows, rest_count = rows, len(segs)
            idx = 0
            while rest_count > SEG_CAP or rest_rows > cap:
                seg = segs[idx]
                taken.append(seg)
                rest_rows -= seg.rows
                rest_count -= 1
                idx += 1
            return taken
        return list(segs)

    def _merge_once(self, level: int) -> None:
        taken = self._pick_taken(level)
        taken_ids = {id(seg) for seg in taken}
        if level < LEVELS - 1:
            pool = self.levels[level + 1]
        else:
            pool = [seg for seg in self.levels[level] if id(seg) not in taken_ids]
        extra = [
            seg
            for seg in pool
            if any(seg.intersects(picked) for picked in taken)
        ]
        inputs = taken + extra
        input_ids = {id(seg) for seg in inputs}

        winners: dict = {}
        for seg in newer_first(inputs):
            for key, value in seg.records.items():
                if key not in winners:
                    winners[key] = (value, seg)

        output: dict = {}
        for key, (value, src) in winners.items():
            if value is None and self._tombstone_collectable(key, src, input_ids):
                continue
            output[key] = value

        for seg in inputs:
            self._drop_segment(seg)
        if output:
            self._add_segment(min(level + 1, LEVELS - 1), output)
        self.merges += 1

    def _tombstone_collectable(self, key: str, src: Segment, input_ids: set) -> bool:
        """比 src 更旧、又没参与本次合并的段都不含该键时，墓碑才可丢。"""
        for level_segs in self.levels:
            for seg in level_segs:
                if id(seg) in input_ids:
                    continue
                if is_older(seg, src) and seg.contains(key):
                    return False
        return True

    def view(self) -> list:
        """存活段按新覆盖旧归并出的键值列表，墓碑不出现，按键升序。"""
        merged: dict = {}
        for seg in newer_first(self.live_segments()):
            for key, value in seg.records.items():
                if key not in merged:
                    merged[key] = value
        return sorted((key, value) for key, value in merged.items() if value is not None)

    def point_get(self, key: str):
        """点查：命中 PUT 返回值，命中 DEL 或没有就是不存在（None）。"""
        for seg in newer_first(self.live_segments()):
            if key in seg.records:
                return seg.records[key]
        return None

    def metrics(self) -> tuple:
        wa = self.disk_bytes / self.user_bytes if self.user_bytes else 0.0
        ra = float(len(self.live_segments()))
        live = self.live_bytes()
        reclaim = (self.disk_bytes - live) / self.disk_bytes if self.disk_bytes else 0.0
        return wa, ra, reclaim

    def report_row(self, step: int, ops_count: int, view_lines: int) -> str:
        wa, ra, reclaim = self.metrics()
        cols = [
            str(step),
            str(ops_count),
            str(self.user_bytes),
            str(self.disk_bytes),
            str(self.live_bytes()),
            fmt3(wa),
            fmt3(ra),
            fmt3(reclaim),
            str(view_lines),
        ]
        for level in range(LEVELS):
            cols.append(str(len(self.levels[level])))
            cols.append(str(self._level_rows(level)))
        cols.append(str(self.merges))
        return " ".join(cols)

    def layout_rows(self, step: int) -> list:
        rows = []
        for level in range(LEVELS):
            for seg in self.levels[level]:
                rows.append(
                    f"{step} {level} {seg.segno:06d} {seg.rows} "
                    f"{seg.tombstone_rows} {seg.nbytes}"
                )
        return rows

    def run(self, steps: list) -> None:
        self.prepare_outdir()
        report_lines = [REPORT_HEADER]
        layout_lines = [LAYOUT_HEADER]
        views_parts: list = []
        for step_no, ops in steps:
            self.apply_step(ops)
            view = self.view()
            views_parts.append(f"# step {step_no}\n")
            views_parts.extend(f"{key}\t{value}\n" for key, value in view)
            report_lines.append(self.report_row(step_no, len(ops), len(view)))
            layout_lines.extend(self.layout_rows(step_no))
        self._write_text("report.tsv", "\n".join(report_lines) + "\n")
        self._write_text("views.txt", "".join(views_parts))
        self._write_text("layout.tsv", "\n".join(layout_lines) + "\n")

    def _write_text(self, name: str, text: str) -> None:
        with open(os.path.join(self.outdir, name), "wb") as handle:
            handle.write(text.encode("utf-8"))


def run_workload(steps: list, outdir: str) -> Engine:
    engine = Engine(outdir)
    engine.run(steps)
    return engine
