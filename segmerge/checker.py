"""check：逐份重放 samples/workloads 下的负载，核对视图、门槛与容量不变量。"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .engine import RA_HARD_LIMIT, ROW_LIMITS, SEG_LIMIT, LEVELS, fmt3, replay
from .segment import decode_segment
from .workload import WorkloadError, parse


@dataclass
class Outcome:
    name: str
    steps: int = 0
    ops: int = 0
    ok: bool = False
    problems: list = field(default_factory=list)
    marks: list = field(default_factory=list)
    stats: list = field(default_factory=list)


def workloads_root(samples_root):
    return Path(samples_root) / "workloads"


def expected_root(samples_root):
    return Path(samples_root) / "expected"


def _parse_marks(path):
    marks = []
    lines = path.read_text(encoding="utf-8").split("\n")
    for line in lines[1:]:
        if line:
            _, wa_max, ra_max, reclaim_min = line.split("\t")
            marks.append((float(wa_max), float(ra_max), float(reclaim_min)))
    return marks


def _check_disk_matches(stats, workdir):
    """末步 report 的层统计按存活段文件重算后必须一致。"""
    segs = []
    for name in os.listdir(workdir):
        if name.startswith("seg-") and name.endswith(".seg"):
            segs.append(decode_segment((workdir / name).read_bytes()))
    disk_segs = [0] * LEVELS
    disk_rows = [0] * LEVELS
    disk_bytes = 0
    for seg in segs:
        disk_segs[seg.level] += 1
        disk_rows[seg.level] += seg.rows
        disk_bytes += seg.nbytes
    last = stats[-1]
    if disk_segs != last.level_segs or disk_rows != last.level_rows:
        return "存活段文件的层统计与 report.tsv 末步不一致"
    if disk_bytes != last.live_bytes:
        return "存活段字节之和与 report.tsv 末步 live_bytes 不一致"
    return None



def run_one(samples_root, name, workdir):
    samples_root = Path(samples_root)
    workdir = Path(workdir)
    outcome = Outcome(name)
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    try:
        data = (workloads_root(samples_root) / (name + ".tsv")).read_bytes()
        steps = parse(data)
        _, stats = replay(steps, workdir)
    except (OSError, WorkloadError, ValueError) as exc:
        outcome.problems.append("重放失败：%s" % exc)
        return outcome
    outcome.stats = stats
    outcome.steps = len(stats)
    outcome.ops = sum(stat.ops for stat in stats)
    expect_dir = expected_root(samples_root)
    views_expect = expect_dir / (name + ".views.txt")
    if not views_expect.exists():
        outcome.problems.append("缺少期望视图")
    elif (workdir / "views.txt").read_bytes() != views_expect.read_bytes():
        outcome.problems.append("视图与期望逐字节不一致")
    marks_expect = expect_dir / (name + ".marks.tsv")
    if not marks_expect.exists():
        outcome.problems.append("缺少门槛文件")
    else:
        try:
            outcome.marks = _parse_marks(marks_expect)
        except ValueError:
            outcome.problems.append("门槛文件无法解析")
    if len(outcome.marks) != len(stats):
        outcome.problems.append("门槛行数与步数不符")
    for stat, mark in zip(stats, outcome.marks):
        wa_max, ra_max, reclaim_min = mark
        if float(fmt3(stat.wa)) > wa_max:
            outcome.problems.append("第 %d 步写放大 %.3f 超过门槛 %.3f" % (stat.step, stat.wa, wa_max))
        if stat.ra > RA_HARD_LIMIT:
            outcome.problems.append("第 %d 步读放大超过结构上限 %d" % (stat.step, RA_HARD_LIMIT))
        if float(stat.ra) > ra_max:
            outcome.problems.append("第 %d 步读放大 %d 超过门槛 %.3f" % (stat.step, stat.ra, ra_max))
        if float(fmt3(stat.reclaim)) < reclaim_min:
            outcome.problems.append(
                "第 %d 步回收率 %.3f 低于门槛 %.3f" % (stat.step, stat.reclaim, reclaim_min)
            )
        for level in range(LEVELS):
            if stat.level_segs[level] > SEG_LIMIT:
                outcome.problems.append("第 %d 步 L%d 段数 %d 越限" % (stat.step, level, SEG_LIMIT))
            cap = ROW_LIMITS[level]
            if cap is not None and stat.level_rows[level] > cap:
                outcome.problems.append("第 %d 步 L%d 行数 %d 越限" % (stat.step, level, cap))
    if stats:
        disk_problem = _check_disk_matches(stats, workdir)
        if disk_problem:
            outcome.problems.append(disk_problem)
    outcome.ok = not outcome.problems
    return outcome


def check_all(samples_root, work_root):
    root = workloads_root(samples_root)
    names = sorted(path.stem for path in root.glob("*.tsv"))
    work_root = Path(work_root)
    return [run_one(samples_root, name, work_root / name) for name in names]
