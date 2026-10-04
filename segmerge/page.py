"""自包含 HTML 报告：内联样式 + 内联 SVG，无外链，file:// 双击即开。

每份负载一节：每步段布局（每段一格，按层排列，宽度表示字节大小，颜色深浅
表示墓碑占比）、三个指标随步走势（门槛画虚线）、各层段数与行数走势、核对
结论。顶部汇总负载数、步数与通过数。数字取自 var/ 下的 report.tsv 与
layout.tsv，以及 samples/expected/ 下的门槛文件。
"""

from __future__ import annotations

import html
import os

from .checker import check_all, parse_marks, parse_report

LEVEL_COLORS = ["#2563eb", "#0d9488", "#65a30d", "#d97706", "#dc2626"]
LEVEL_NAMES = ["L0", "L1", "L2", "L3", "L4"]


def _esc(text) -> str:
    return html.escape(str(text), quote=True)


def _num(value: float) -> str:
    return format(value, ".2f")


def _tombstone_color(ratio: float) -> str:
    """墓碑占比 0..1 -> 浅灰到深红。"""
    ratio = max(0.0, min(1.0, ratio))
    base = (226, 230, 238)
    dark = (153, 27, 27)
    rgb = tuple(round(b + (d - b) * ratio) for b, d in zip(base, dark))
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _polyline(points, color, width=1.5, dash=None) -> str:
    pts = " ".join(f"{_num(x)},{_num(y)}" for x, y in points)
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<polyline points="{pts}" fill="none" stroke="{color}" '
        f'stroke-width="{width}"{dash_attr}/>'
    )


def _axes(width, height, pad, ymax, ylabel) -> str:
    left, top, bottom = pad
    parts = [
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" '
        f'stroke="#94a3b8" stroke-width="1"/>',
        f'<line x1="{left}" y1="{height - bottom}" x2="{width - 6}" '
        f'y2="{height - bottom}" stroke="#94a3b8" stroke-width="1"/>',
        f'<text x="4" y="{top + 8}" font-size="9" fill="#64748b">'
        f"{_esc(_num(ymax))}</text>",
        f'<text x="4" y="{height - bottom}" font-size="9" fill="#64748b">0</text>',
        f'<text x="{left + 4}" y="{top + 8}" font-size="9" fill="#64748b">'
        f"{_esc(ylabel)}</text>",
    ]
    return "".join(parts)


def _series_points(values, width, height, pad, ymax):
    left, top, bottom = pad
    count = len(values)
    span = max(1, count - 1)
    usable = height - top - bottom
    points = []
    for idx, value in enumerate(values):
        x = left + (width - left - 8) * idx / span if count > 1 else left
        y = top + usable * (1.0 - value / ymax) if ymax else height - bottom
        points.append((x, y))
    return points


def _metric_chart(title, values, thresholds, width=330, height=150):
    pad = (34, 14, 18)
    ymax = max(list(values) + list(thresholds) + [1e-9]) * 1.08
    parts = [f'<svg width="{width}" height="{height}" role="img">']
    parts.append(_axes(width, height, pad, ymax, title))
    parts.append(
        _polyline(_series_points(thresholds, width, height, pad, ymax), "#b45309", 1.2, "5 3")
    )
    parts.append(
        _polyline(_series_points(values, width, height, pad, ymax), "#1d4ed8", 1.8)
    )
    parts.append(
        f'<text x="{width - 8}" y="{height - 4}" font-size="9" fill="#64748b" '
        f'text-anchor="end">步</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def _levels_chart(title, per_level_values, width=330, height=150):
    pad = (34, 14, 18)
    ymax = max([v for values in per_level_values for v in values] + [1e-9]) * 1.08
    parts = [f'<svg width="{width}" height="{height}" role="img">']
    parts.append(_axes(width, height, pad, ymax, title))
    for level, values in enumerate(per_level_values):
        parts.append(
            _polyline(
                _series_points(values, width, height, pad, ymax),
                LEVEL_COLORS[level],
                1.6,
            )
        )
    parts.append("</svg>")
    return "".join(parts)


def _layout_svg(layout_rows, steps_count):
    """每步之后的段布局：每段一格，按层分行，宽度表示字节，颜色表示墓碑占比。"""
    by_step_level: dict = {}
    max_bytes = 1
    for row in layout_rows:
        _step, level, segno, rows, tombs, nbytes = row
        key = (int(_step), int(level))
        by_step_level.setdefault(key, []).append(
            (segno, int(rows), int(tombs), int(nbytes))
        )
        max_bytes = max(max_bytes, int(nbytes))
    col_w = max(8, min(48, 960 // max(1, steps_count)))
    lane_h = 40
    left = 30
    top = 16
    width = left + steps_count * col_w + 8
    height = top + 5 * lane_h + 16
    parts = [
        f'<svg width="{width}" height="{height}" role="img" '
        f'style="max-width:none">'
    ]
    for level in range(5):
        lane_y = top + level * lane_h
        parts.append(
            f'<text x="2" y="{lane_y + 10}" font-size="9" '
            f'fill="{LEVEL_COLORS[level]}">{LEVEL_NAMES[level]}</text>'
        )
        parts.append(
            f'<line x1="{left}" y1="{lane_y + lane_h - 4}" x2="{width - 4}" '
            f'y2="{lane_y + lane_h - 4}" stroke="#e2e8f0" stroke-width="1"/>'
        )
    for step in range(1, steps_count + 1):
        x = left + (step - 1) * col_w
        for level in range(5):
            segs = by_step_level.get((step, level))
            if not segs:
                continue
            lane_y = top + level * lane_h
            for idx, (segno, rows, tombs, nbytes) in enumerate(segs):
                bar_w = max(1.0, (col_w - 2) * nbytes / max_bytes)
                bar_y = lane_y + idx * 4
                ratio = tombs / rows if rows else 0.0
                parts.append(
                    f'<rect x="{_num(x + 1)}" y="{_num(bar_y)}" '
                    f'width="{_num(bar_w)}" height="3" '
                    f'fill="{_tombstone_color(ratio)}">'
                    f"<title>步{step} {LEVEL_NAMES[level]} 段{segno} "
                    f"行={rows} 字节={nbytes} 墓碑占比={ratio:.1%}</title></rect>"
                )
    parts.append("</svg>")
    return "".join(parts)


def _read_layout(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle.read().splitlines()[1:]:
            if line.strip():
                rows.append(line.split(" "))
    return rows


def _render_section(samples_root, workdir, result):
    name = result.name
    outdir = os.path.join(workdir, name)
    report = parse_report(os.path.join(outdir, "report.tsv"))
    layout = _read_layout(os.path.join(outdir, "layout.tsv"))
    marks_path = os.path.join(samples_root, "expected", f"{name}.marks.tsv")
    marks = parse_marks(marks_path) if os.path.exists(marks_path) else []

    steps = [int(row[0]) for row in report]
    wa = [float(row[5]) for row in report]
    ra = [float(row[6]) for row in report]
    reclaim = [float(row[7]) for row in report]
    wa_max = [row[1] for row in marks] or [0.0] * len(steps)
    ra_max = [row[2] for row in marks] or [0.0] * len(steps)
    reclaim_min = [row[3] for row in marks] or [0.0] * len(steps)
    seg_counts = [[int(row[9 + level * 2]) for row in report] for level in range(5)]
    row_counts = [[int(row[10 + level * 2]) for row in report] for level in range(5)]

    verdict = (
        '<span class="pass">通过</span>'
        if result.ok
        else f'<span class="fail">失败：{_esc("；".join(result.problems))}</span>'
    )
    total_ops = sum(int(row[1]) for row in report)
    last = report[-1] if report else None
    final = (
        f"最终 写放大 {last[5]} / 读放大 {last[6]} / 回收率 {last[7]}"
        if last
        else "无数据"
    )

    legend = "".join(
        f'<span class="chip" style="background:{LEVEL_COLORS[level]}"></span>'
        f"{LEVEL_NAMES[level]} "
        for level in range(5)
    )
    parts = [
        f"<section><h2>{_esc(name)} {verdict}</h2>",
        f"<p>步数 {len(steps)}，操作 {total_ops} 条；{final}。"
        f"布局图例：{legend}（格宽∝段字节，颜色越深墓碑占比越高）</p>",
        '<div class="scroll">',
        _layout_svg(layout, len(steps)),
        "</div>",
        '<div class="charts">',
        _metric_chart("写放大(上限虚线)", wa, wa_max),
        _metric_chart("读放大(上限虚线)", ra, ra_max),
        _metric_chart("回收率(下限虚线)", reclaim, reclaim_min),
        "</div>",
        '<div class="charts">',
        _levels_chart("各层段数", seg_counts),
        _levels_chart("各层行数", row_counts),
        "</div>",
        "</section>",
    ]
    return "".join(parts)


PAGE_CSS = """
body{font-family:system-ui,'Segoe UI',sans-serif;margin:24px;color:#0f172a}
h1{font-size:20px} h2{font-size:15px;margin:18px 0 6px}
section{border-top:1px solid #cbd5e1;padding-top:8px;margin-top:18px}
.pass{color:#15803d;font-weight:600}.fail{color:#b91c1c;font-weight:600}
.charts{display:flex;gap:12px;flex-wrap:wrap;margin:6px 0}
.scroll{overflow-x:auto;border:1px solid #e2e8f0;background:#f8fafc}
.chip{display:inline-block;width:10px;height:10px;border-radius:2px;margin-left:8px}
table{border-collapse:collapse;font-size:12px;margin:8px 0}
td,th{border:1px solid #cbd5e1;padding:2px 8px;text-align:right}
th{background:#f1f5f9}
svg text{font-family:inherit}
"""


def generate_page(samples_root: str, out_html: str, workdir: str = "var") -> list:
    """重放全部负载并渲染报告页，返回核对结果列表。"""
    results = check_all(samples_root, workdir)
    total_steps = sum(result.steps for result in results)
    passed = sum(1 for result in results if result.ok)

    summary_rows = []
    for result in results:
        report_path = os.path.join(workdir, result.name, "report.tsv")
        report = parse_report(report_path) if os.path.exists(report_path) else []
        last = report[-1] if report else ["-"] * 20
        verdict = "通过" if result.ok else "失败"
        summary_rows.append(
            f"<tr><td>{_esc(result.name)}</td><td>{result.steps}</td>"
            f"<td>{_esc(last[5])}</td><td>{_esc(last[6])}</td>"
            f"<td>{_esc(last[7])}</td><td>{verdict}</td></tr>"
        )

    sections = [
        _render_section(samples_root, workdir, result) for result in results
    ]
    parts = [
        "<!DOCTYPE html>\n",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        "<title>段合并报告</title>",
        f"<style>{PAGE_CSS}</style></head><body>",
        "<h1>段合并策略报告</h1>",
        f"<p>负载 {len(results)} 份，总步数 {total_steps}，通过 {passed} 份。"
        "数据来自 report.tsv / layout.tsv 与 samples/expected/ 门槛文件。</p>",
        "<table><tr><th>负载</th><th>步数</th><th>最终写放大</th>"
        "<th>最终读放大</th><th>最终回收率</th><th>结论</th></tr>",
        "".join(summary_rows),
        "</table>",
        "".join(sections),
        "</body></html>",
    ]
    with open(out_html, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("".join(parts))
    return results
