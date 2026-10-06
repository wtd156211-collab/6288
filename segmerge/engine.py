"""段合并引擎：逐步落盘，按容量口径找层、挑段、合并到收敛。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .segment import (
    LEVELS,
    MISSING,
    ROW_LIMITS,
    SEG_LIMIT,
    Segment,
    encode_segment,
    segment_filename,
)

REPORT_COLUMNS = (
    "step", "ops", "user_bytes", "disk_bytes", "live_bytes", "wa", "ra", "reclaim",
    "view_lines",
) + tuple(
    "%s_%s" % ("L%d" % level, kind)
    for level in range(LEVELS)
    for kind in ("segs", "rows")
) + ("merges",)
LAYOUT_COLUMNS = ("step", "level", "seg", "rows", "tomb_rows", "bytes")
OUTPUT_FILES = ("report.tsv", "views.txt", "layout.tsv")
RA_HARD_LIMIT = 40


def fmt3(value):
    return format(value, ".3f")


@dataclass
class StepStat:
    """一步收敛后的统计；wa/ra/reclaim 为原始值，写文件时按三位小数格式化。"""

    step: int
    ops: int
    user_bytes: int
    disk_bytes: int
    live_bytes: int
    wa: float
    ra: int
    reclaim: float
    view_lines: int
    level_segs: list
    level_rows: list
    merges: int

    def report_line(self):
        fields = [
            str(self.step),
            str(self.ops),
            str(self.user_bytes),
            str(self.disk_bytes),
            str(self.live_bytes),
            fmt3(self.wa),
            fmt3(float(self.ra)),
            fmt3(self.reclaim),
            str(self.view_lines),
        ]
        for level in range(LEVELS):
            fields.append(str(self.level_segs[level]))
            fields.append(str(self.level_rows[level]))
        fields.append(str(self.merges))
        return "\t".join(fields)


class Engine:
    """重放负载的合并引擎；段即时落盘，合并后输入段随即删除。"""

    def __init__(self, outdir):
        self.outdir = str(outdir)
        self.live = []
        self.user_bytes = 0
        self.disk_bytes = 0
        self.merges = 0
        self.seq = 0

    # -- 段文件 --

    def _write_segment(self, level, records):
        self.seq += 1
        seg = Segment(level, self.seq, records)
        data = encode_segment(level, self.seq, records)
        seg.nbytes = len(data)
        path = os.path.join(self.outdir, segment_filename(self.seq))
        with open(path, "wb") as handle:
            handle.write(data)
        self.live.append(seg)
        self.disk_bytes += len(data)
        return seg

    def _drop_segment(self, seg):
        os.remove(os.path.join(self.outdir, segment_filename(seg.number)))
        self.live.remove(seg)

    # -- 一步 --

    def apply_step(self, ops):
        """落盘该步操作（同键只留最后一条）并合并到收敛。"""
        for op in ops:
            self.user_bytes += op.nbytes
        if ops:
            latest = {}
            for op in ops:
                latest[op.key] = op.value
            self._write_segment(0, sorted(latest.items()))
        self._compact()

    # -- 合并 --

    def _level_segs(self, level):
        return sorted((s for s in self.live if s.level == level), key=lambda s: s.number)

    def _over_limit_level(self):
        """层号最小的越限层；没有则 None。"""
        for level in range(LEVELS):
            segs = self._level_segs(level)
            if len(segs) > SEG_LIMIT:
                return level
            cap = ROW_LIMITS[level]
            if cap is not None and sum(s.rows for s in segs) > cap:
                return level
        return None

    def _compact(self):
        while True:
            level = self._over_limit_level()
            if level is None:
                return
            self._merge(level)

    def _pick_segments(self, level, segs):
        """只是段数越限取全部；行数越限从最旧取到剩余段数与行数都回到上限内。"""
        cap = ROW_LIMITS[level]
        total_rows = sum(s.rows for s in segs)
        if cap is None or total_rows <= cap:
            return list(segs)
        selected = []
        rest_rows, rest_count = total_rows, len(segs)
        for seg in segs:
            if rest_rows <= cap and rest_count <= SEG_LIMIT:
                break
            selected.append(seg)
            rest_rows -= seg.rows
            rest_count -= 1
        return selected

    def _merge(self, level):
        segs = self._level_segs(level)
        selected = self._pick_segments(level, segs)
        ranges = [(s.min_key, s.max_key) for s in selected]
        chosen = {id(s) for s in selected}
        if level + 1 < LEVELS:
            pool = [s for s in self.live if s.level == level + 1]
        else:
            pool = [s for s in self.live if s.level == level and id(s) not in chosen]
        inputs = selected + [
            seg
            for seg in pool
            if any(lo <= seg.max_key and seg.min_key <= hi for lo, hi in ranges)
        ]
        # 归并：最旧在前，同键新的覆盖旧的，并记下每条最新记录来自哪段。
        latest = {}
        for seg in sorted(inputs, key=lambda s: (-s.level, s.number)):
            for key, value in seg.records:
                latest[key] = (value, seg)
        input_ids = {id(s) for s in inputs}
        outsiders = [s for s in self.live if id(s) not in input_ids]
        older_cache = {}
        records = []
        for key in sorted(latest):
            value, src = latest[key]
            if value is not None:
                records.append((key, value))
                continue
            src_id = id(src)
            if src_id not in older_cache:
                older_cache[src_id] = [
                    s
                    for s in outsiders
                    if s.level > src.level
                    or (s.level == src.level and s.number < src.number)
                ]
            # 只有更旧且未参与合并的段都不含该键，墓碑才能丢掉。
            if any(s.get(key) is not MISSING for s in older_cache[src_id]):
                records.append((key, None))
        for seg in inputs:
            self._drop_segment(seg)
        if records:
            self._write_segment(min(level + 1, LEVELS - 1), records)
        self.merges += 1

    # -- 读 --

    def view(self):
        """存活段按新覆盖旧归并出的键值列表，墓碑不出现，按键升序。"""
        latest = {}
        for seg in sorted(self.live, key=lambda s: (-s.level, s.number)):
            for key, value in seg.records:
                latest[key] = value
        return [(key, latest[key]) for key in sorted(latest) if latest[key] is not None]

    def get(self, key):
        """点查：从新到旧，第一条含该键的记录说了算；不存在返回 None。"""
        for seg in sorted(self.live, key=lambda s: (s.level, -s.number)):
            value = seg.get(key)
            if value is not MISSING:
                return value
        return None

    # -- 统计 --

    def snapshot(self, step, ops_count, view_lines):
        level_segs = [0] * LEVELS
        level_rows = [0] * LEVELS
        live_bytes = 0
        for seg in self.live:
            level_segs[seg.level] += 1
            level_rows[seg.level] += seg.rows
            live_bytes += seg.nbytes
        wa = self.disk_bytes / self.user_bytes if self.user_bytes else 0.0
        reclaim = (self.disk_bytes - live_bytes) / self.disk_bytes if self.disk_bytes else 0.0
        return StepStat(
            step=step,
            ops=ops_count,
            user_bytes=self.user_bytes,
            disk_bytes=self.disk_bytes,
            live_bytes=live_bytes,
            wa=wa,
            ra=len(self.live),
            reclaim=reclaim,
            view_lines=view_lines,
            level_segs=level_segs,
            level_rows=level_rows,
            merges=self.merges,
        )


def clean_output_dir(outdir):
    """清空输出目录里本工具会写的文件（段文件与三个统计文件）。"""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    for name in os.listdir(outdir):
        if (name.startswith("seg-") and name.endswith(".seg")) or name in OUTPUT_FILES:
            os.remove(outdir / name)


def replay(steps, outdir):
    """逐步重放负载，写段文件、report.tsv、views.txt、layout.tsv，返回每步统计。"""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    engine = Engine(outdir)
    stats = []
    with open(outdir / "report.tsv", "wb") as report, open(
        outdir / "views.txt", "wb"
    ) as views, open(outdir / "layout.tsv", "wb") as layout:
        report.write(("\t".join(REPORT_COLUMNS) + "\n").encode("ascii"))
        layout.write(("\t".join(LAYOUT_COLUMNS) + "\n").encode("ascii"))
        for index, ops in enumerate(steps, 1):
            engine.apply_step(ops)
            view = engine.view()
            views.write(("# step %d\n" % index).encode("ascii"))
            for key, value in view:
                views.write(("%s\t%s\n" % (key, value)).encode("utf-8"))
            stat = engine.snapshot(index, len(ops), len(view))
            stats.append(stat)
            report.write((stat.report_line() + "\n").encode("ascii"))
            for seg in sorted(engine.live, key=lambda s: (s.level, s.number)):
                layout.write(
                    (
                        "%d\t%d\t%06d\t%d\t%d\t%d\n"
                        % (index, seg.level, seg.number, seg.rows, seg.tombstones, seg.nbytes)
                    ).encode("ascii")
                )
    return engine, stats
