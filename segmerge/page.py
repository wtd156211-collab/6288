"""page：把 var/ 下的统计与期望门槛渲染成自包含 HTML（内联 SVG，无外链）。"""
from __future__ import annotations

import html
import math
from pathlib import Path

from .checker import expected_root
from .engine import LEVELS, RA_HARD_LIMIT

LEVEL_NAMES = ["L0", "L1", "L2", "L3", "L4"]
LEVEL_COLORS = ["#2563eb", "#0d9488", "#d97706", "#dc2626", "#7c3aed"]
VALUE_COLOR = "#1d4ed8"
THRESHOLD_COLOR = "#b91c1c"


def _esc(text):
    return html.escape(str(text), quote=True)


# -- 数据读取（只取自引擎输出的统计文件与期望文件） --


def _read_report(path):
    rows = []
    lines = path.read_text(encoding="utf-8").split("\n")
    header = lines[0].split("\t")
    for line in lines[1:]:
        if line:
            rows.append(dict(zip(header, line.split("\t"))))
    return rows


def _read_layout(path):
    rows = []
    lines = path.read_text(encoding="utf-8").split("\n")
    for line in lines[1:]:
        if line:
            step, level, seg, nrows, tomb, nbytes = line.split("\t")
            rows.append(
                {
                    "step": int(step),
                    "level": int(level),
                    "seg": seg,
                    "rows": int(nrows),
                    "tomb": int(tomb),
                    "bytes": int(nbytes),
                }
            )
    return rows


def _read_marks(path):
    marks = []
    if not path.exists():
        return marks
    lines = path.read_text(encoding="utf-8").split("\n")
    for line in lines[1:]:
        if line:
            _, wa_max, ra_max, reclaim_min = line.split("\t")
            marks.append((float(wa_max), float(ra_max), float(reclaim_min)))
    return marks


# -- SVG 小件 --


def _polyline(points, color, dash=False):
    pts = " ".join("%.1f,%.1f" % point for point in points)
    dash_attr = ' stroke-dasharray="5 4"' if dash else ""
    return (
        '<polyline fill="none" stroke="%s" stroke-width="1.6"%s points="%s"/>'
        % (color, dash_attr, pts)
    )


def _metric_chart(title, values, thresholds, threshold_label):
    """一条指标曲线 + 门槛虚线；values/thresholds 为逐步浮点序列。"""
    width, height = 660, 150
    left, right, top, bottom = 48, 10, 26, 20
    count = len(values)
    vmax = max(list(values) + list(thresholds) + [1e-9]) * 1.08

    def x_at(i):
        span = max(count - 1, 1)
        return left + (width - left - right) * i / span

    def y_at(v):
        return top + (height - top - bottom) * (1 - v / vmax)

    parts = [
        '<svg width="%d" height="%d" viewBox="0 0 %d %d" role="img">'
        % (width, height, width, height),
        '<rect x="0" y="0" width="%d" height="%d" fill="#ffffff" stroke="#e2e8f0"/>'
        % (width, height),
        '<text x="8" y="16" font-size="12" fill="#334155">%s</text>' % _esc(title),
    ]
    for frac, label in ((0.0, "0"), (0.5, "%.3f" % (vmax / 2)), (1.0, "%.3f" % vmax)):
        y = y_at(vmax * frac)
        parts.append(
            '<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#f1f5f9"/>'
            % (left, y, width - right, y)
        )
        parts.append(
            '<text x="4" y="%.1f" font-size="9" fill="#94a3b8">%s</text>' % (y + 3, _esc(label))
        )
    parts.append(
        _polyline([(x_at(i), y_at(v)) for i, v in enumerate(thresholds)], THRESHOLD_COLOR, dash=True)
    )
    parts.append(_polyline([(x_at(i), y_at(v)) for i, v in enumerate(values)], VALUE_COLOR))
    parts.append(
        '<text x="%d" y="%d" font-size="9" fill="#94a3b8">step 1</text>' % (left, height - 6)
    )
    parts.append(
        '<text x="%d" y="%d" font-size="9" fill="#94a3b8" text-anchor="end">step %d</text>'
        % (width - right, height - 6, count)
    )
    parts.append(
        '<text x="%d" y="16" font-size="10" fill="%s" text-anchor="end">— 值 ┅ %s</text>'
        % (width - right, THRESHOLD_COLOR, _esc(threshold_label))
    )
    parts.append("</svg>")
    return "".join(parts)


def _level_chart(title, report_rows, key_prefix, log_scale):
    """各层段数/行数走势：每层一条折线。"""
    width, height = 660, 150
    left, right, top, bottom = 48, 10, 26, 20
    count = len(report_rows)
    series = []
    for level in range(LEVELS):
        values = [float(row["%s%d_%s" % ("L", level, key_prefix)]) for row in report_rows]
        series.append(values)
    flat = [v for values in series for v in values]
    vmax = max(flat + [1.0])
    if log_scale:
        vmax = math.log10(vmax + 1)

        def scale(v):
            return math.log10(v + 1)

    else:

        def scale(v):
            return v

    def x_at(i):
        span = max(count - 1, 1)
        return left + (width - left - right) * i / span

    def y_at(v):
        return top + (height - top - bottom) * (1 - scale(v) / vmax)

    parts = [
        '<svg width="%d" height="%d" viewBox="0 0 %d %d">'
        % (width, height, width, height),
        '<rect x="0" y="0" width="%d" height="%d" fill="#ffffff" stroke="#e2e8f0"/>'
        % (width, height),
        '<text x="8" y="16" font-size="12" fill="#334155">%s%s</text>'
        % (_esc(title), "（对数轴）" if log_scale else ""),
    ]
    for level, values in enumerate(series):
        parts.append(
            _polyline([(x_at(i), y_at(v)) for i, v in enumerate(values)], LEVEL_COLORS[level])
        )
        parts.append(
            '<text x="%d" y="%d" font-size="10" fill="%s">%s</text>'
            % (left + level * 34, height - 6, LEVEL_COLORS[level], LEVEL_NAMES[level])
        )
    parts.append("</svg>")
    return "".join(parts)


def _tombstone_color(ratio):
    """墓碑占比 0→浅色，1→深色。"""
    lightness = 84 - 49 * ratio
    return "hsl(215, 72%%, %.0f%%)" % lightness


def _layout_board(layout_rows, step_count):
    """段布局：每列一步、每段一行、按层分带；宽度=字节，颜色深浅=墓碑占比。"""
    col_w = 96
    bar_max_w = 86
    slot = 10
    seg_h = 7
    left = 40
    top = 18
    by_step_level = {}
    max_bytes = 1
    band_slots = [0] * LEVELS
    for row in layout_rows:
        key = (row["step"], row["level"])
        by_step_level.setdefault(key, []).append(row)
        max_bytes = max(max_bytes, row["bytes"])
    for (step, level), rows in by_step_level.items():
        band_slots[level] = max(band_slots[level], len(rows))
    band_h = [max(slots, 1) * slot + 8 for slots in band_slots]
    band_y = [top]
    for level in range(1, LEVELS):
        band_y.append(band_y[-1] + band_h[level - 1])
    height = band_y[-1] + band_h[-1] + 16
    width = left + step_count * col_w + 8
    parts = [
        '<svg width="%d" height="%d" viewBox="0 0 %d %d">'
        % (width, height, width, height),
        '<rect x="0" y="0" width="%d" height="%d" fill="#ffffff"/>' % (width, height),
    ]
    tick = max(1, step_count // 30)
    for step in range(1, step_count + 1):
        if step == 1 or step % tick == 0 or step == step_count:
            x = left + (step - 1) * col_w
            parts.append(
                '<text x="%d" y="12" font-size="9" fill="#94a3b8">%d</text>' % (x, step)
            )
    for level in range(LEVELS):
        y = band_y[level]
        parts.append(
            '<text x="4" y="%d" font-size="11" fill="%s">%s</text>'
            % (y + 12, LEVEL_COLORS[level], LEVEL_NAMES[level])
        )
        parts.append(
            '<line x1="0" y1="%d" x2="%d" y2="%d" stroke="#e2e8f0"/>'
            % (y + band_h[level] - 2, width, y + band_h[level] - 2)
        )
    for (step, level), rows in sorted(by_step_level.items()):
        x = left + (step - 1) * col_w
        for index, row in enumerate(rows):
            w = max(2.0, bar_max_w * row["bytes"] / max_bytes)
            ratio = row["tomb"] / row["rows"] if row["rows"] else 0.0
            y = band_y[level] + index * slot
            parts.append(
                '<rect x="%d" y="%d" width="%.1f" height="%d" fill="%s">'
                % (x, y, w, seg_h, _tombstone_color(ratio))
            )
            parts.append(
                "<title>step %d · %s · seg-%s · %d 行 · %d B · 墓碑 %d/%d</title></rect>"
                % (
                    step,
                    LEVEL_NAMES[level],
                    row["seg"],
                    row["rows"],
                    row["bytes"],
                    row["tomb"],
                    row["rows"],
                )
            )
    parts.append("</svg>")
    return "".join(parts)


# -- 页面组装 --

_SECTION_CSS = """
body{margin:0;padding:24px;font:14px/1.5 -apple-system,"Segoe UI",Roboto,"Noto Sans SC",sans-serif;background:#f8fafc;color:#0f172a}
h1{font-size:20px;margin:0 0 4px}h2{font-size:16px;margin:0}h3{font-size:13px;color:#475569;margin:14px 0 6px}
.summary{color:#475569;margin-bottom:18px}
section{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:16px;margin:0 0 20px}
.meta{color:#64748b;font-size:12px;margin:4px 0 0}
.ok{color:#15803d}.bad{color:#b91c1c}
.scroll{overflow-x:auto;border:1px solid #e2e8f0;border-radius:6px}
.charts{display:flex;flex-wrap:wrap;gap:12px}
ul.problems{margin:6px 0 0;padding-left:18px;color:#b91c1c;font-size:12px}
.legend{font-size:11px;color:#64748b;margin-top:4px}
""".strip()


def _section(samples_root, outcome, workdir):
    name = outcome.name
    report_rows = _read_report(workdir / "report.tsv")
    layout_rows = _read_layout(workdir / "layout.tsv")
    marks = _read_marks(expected_root(samples_root) / (name + ".marks.tsv"))
    steps = len(report_rows)
    wa = [float(row["wa"]) for row in report_rows]
    ra = [float(row["ra"]) for row in report_rows]
    reclaim = [float(row["reclaim"]) for row in report_rows]
    wa_max = [mark[0] for mark in marks] or [0.0] * steps
    ra_max = [mark[1] for mark in marks] or [float(RA_HARD_LIMIT)] * steps
    reclaim_min = [mark[2] for mark in marks] or [0.0] * steps
    verdict = (
        '<span class="ok">通过</span>' if outcome.ok else '<span class="bad">未通过</span>'
    )
    parts = [
        "<section>",
        "<h2>%s %s</h2>" % (_esc(name), verdict),
        '<p class="meta">%d 步 · %d 条操作 · 末步写放大 %s · 读放大 %s · 回收率 %s · 累计合并 %s 次</p>'
        % (
            steps,
            outcome.ops,
            _esc(report_rows[-1]["wa"] if report_rows else "-"),
            _esc(report_rows[-1]["ra"] if report_rows else "-"),
            _esc(report_rows[-1]["reclaim"] if report_rows else "-"),
            _esc(report_rows[-1]["merges"] if report_rows else "-"),
        ),
    ]
    if outcome.problems:
        parts.append('<ul class="problems">')
        for problem in outcome.problems:
            parts.append("<li>%s</li>" % _esc(problem))
        parts.append("</ul>")
    parts.append("<h3>段布局（每列一步，每段一行，按层分带；宽度=落盘字节，颜色越深墓碑占比越高）</h3>")
    parts.append('<div class="scroll">%s</div>' % _layout_board(layout_rows, steps))
    parts.append(
        '<p class="legend">墓碑占比色阶：<svg width="150" height="10">'
        + "".join(
            '<rect x="%d" y="0" width="30" height="10" fill="%s"/>'
            % (i * 30, _tombstone_color(i / 4))
            for i in range(5)
        )
        + '</svg> 0% → 100%</p>'
    )
    parts.append("<h3>指标走势（虚线为门槛）</h3>")
    parts.append('<div class="charts">')
    parts.append(_metric_chart("写放大（累计落盘 ÷ 输入）", wa, wa_max, "wa_max"))
    parts.append(_metric_chart("读放大（存活段数）", ra, ra_max, "ra_max"))
    parts.append(_metric_chart("空间回收率", reclaim, reclaim_min, "reclaim_min"))
    parts.append("</div>")
    parts.append("<h3>各层段数与行数</h3>")
    parts.append('<div class="charts">')
    parts.append(_level_chart("各层段数", report_rows, "segs", log_scale=False))
    parts.append(_level_chart("各层行数", report_rows, "rows", log_scale=True))
    parts.append("</div>")
    parts.append("</section>")
    return "".join(parts)


def render(samples_root, outcomes, work_root):
    """渲染整页；outcomes 来自 checker（提供核对结论），数字取自 var/ 与期望文件。"""
    work_root = Path(work_root)
    sections = []
    for outcome in outcomes:
        sections.append(_section(samples_root, outcome, work_root / outcome.name))
    total_steps = sum(outcome.steps for outcome in outcomes)
    passed = sum(1 for outcome in outcomes if outcome.ok)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        "<title>段合并策略报告</title>\n"
        "<style>%s</style>\n</head>\n<body>\n" % _SECTION_CSS
        + "<h1>段合并策略报告</h1>\n"
        + '<p class="summary">负载 %d 份 · 步数 %d · 通过 %d</p>\n'
        % (len(outcomes), total_steps, passed)
        + "\n".join(sections)
        + "\n</body>\n</html>\n"
    )
