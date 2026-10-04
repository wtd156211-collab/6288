"""核对：重放 samples/workloads/**，比对视图、门槛与容量不变量。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .engine import LEVELS, ROW_CAPS, SEG_CAP, run_workload
from .segment import load_segments
from .workload import WorkloadError, load_workload

RA_STRUCTURAL_CAP = 40


@dataclass
class CheckResult:
    name: str
    steps: int = 0
    problems: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def list_workloads(samples_root: str) -> list:
    """返回 [(名, 负载路径)]，按名排序；名为相对 workloads/ 的去后缀路径。"""
    wdir = os.path.join(samples_root, "workloads")
    found = []
    for dirpath, _dirnames, filenames in os.walk(wdir):
        for filename in filenames:
            if not filename.endswith(".tsv"):
                continue
            path = os.path.join(dirpath, filename)
            rel = os.path.relpath(path, wdir)
            name = rel[: -len(".tsv")].replace(os.sep, "/")
            found.append((name, path))
    return sorted(found)


def parse_marks(path: str) -> list:
    """解析 marks.tsv -> [(step, wa_max, ra_max, reclaim_min), ...]。"""
    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        step, wa_max, ra_max, reclaim_min = line.split("\t")
        rows.append((int(step), float(wa_max), float(ra_max), float(reclaim_min)))
    return rows


def parse_report(path: str) -> list:
    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    return [line.split(" ") for line in lines[1:] if line.strip()]


def _check_marks(result: CheckResult, marks: list, report: list) -> None:
    if len(marks) != len(report):
        result.problems.append(
            f"门槛行数 {len(marks)} 与报告步数 {len(report)} 不一致"
        )
        return
    for (step, wa_max, ra_max, reclaim_min), row in zip(marks, report):
        wa, ra, reclaim = float(row[5]), float(row[6]), float(row[7])
        if int(row[0]) != step:
            result.problems.append(f"第 {step} 步：报告步号对不上")
        if wa > wa_max:
            result.problems.append(f"第 {step} 步：写放大 {wa:.3f} 超上限 {wa_max:.3f}")
        if ra > ra_max or ra > RA_STRUCTURAL_CAP:
            result.problems.append(f"第 {step} 步：读放大 {ra:.3f} 超上限 {ra_max:.3f}")
        if reclaim < reclaim_min:
            result.problems.append(
                f"第 {step} 步：回收率 {reclaim:.3f} 低于下限 {reclaim_min:.3f}"
            )


def _check_capacity(result: CheckResult, report: list) -> None:
    for row in report:
        step = row[0]
        for level in range(LEVELS):
            segs = int(row[9 + level * 2])
            rows = int(row[10 + level * 2])
            if segs > SEG_CAP:
                result.problems.append(f"第 {step} 步：L{level} 段数 {segs} 越限")
            cap = ROW_CAPS[level]
            if cap is not None and rows > cap:
                result.problems.append(f"第 {step} 步：L{level} 行数 {rows} 越限")


def _check_disk_state(result: CheckResult, outdir: str, report: list) -> None:
    """按存活段文件重算，与报告最后一行对照。"""
    if not report:
        return
    segs = load_segments(outdir)
    counts = [0] * LEVELS
    rows = [0] * LEVELS
    for seg in segs:
        counts[seg.level] += 1
        rows[seg.level] += seg.rows
    last = report[-1]
    for level in range(LEVELS):
        if int(last[9 + level * 2]) != counts[level] or int(last[10 + level * 2]) != rows[level]:
            result.problems.append(f"L{level} 段数/行数与磁盘存活段不一致")
    if int(last[4]) != sum(seg.nbytes for seg in segs):
        result.problems.append("存活字节与磁盘存活段不一致")


def check_one(samples_root: str, name: str, workload_path: str, workdir: str) -> CheckResult:
    result = CheckResult(name)
    outdir = os.path.join(workdir, name)
    try:
        steps = load_workload(workload_path)
    except WorkloadError as exc:
        result.problems.append(f"负载不合法：{exc}")
        return result
    run_workload(steps, outdir)
    result.steps = len(steps)

    views_path = os.path.join(outdir, "views.txt")
    expected_views = os.path.join(samples_root, "expected", f"{name}.views.txt")
    if not os.path.exists(expected_views):
        result.problems.append("缺少期望视图文件")
    else:
        with open(views_path, "rb") as handle:
            mine = handle.read()
        with open(expected_views, "rb") as handle:
            expected = handle.read()
        if mine != expected:
            result.problems.append("视图与期望不一致")

    report = parse_report(os.path.join(outdir, "report.tsv"))
    if len(report) != len(steps):
        result.problems.append(f"报告步数 {len(report)} 与负载步数 {len(steps)} 不一致")

    marks_path = os.path.join(samples_root, "expected", f"{name}.marks.tsv")
    if not os.path.exists(marks_path):
        result.problems.append("缺少门槛文件")
    else:
        _check_marks(result, parse_marks(marks_path), report)

    _check_capacity(result, report)
    _check_disk_state(result, outdir, report)
    return result


def check_all(samples_root: str, workdir: str = "var") -> list:
    results = []
    for name, path in list_workloads(samples_root):
        results.append(check_one(samples_root, name, path, workdir))
    return results
