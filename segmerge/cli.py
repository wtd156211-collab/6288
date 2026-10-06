"""命令行入口：run / read / check / page。"""
from __future__ import annotations

import sys
from pathlib import Path

from . import checker
from .engine import clean_output_dir, replay
from .segment import MISSING, load_dir_segments
from .workload import WorkloadError, parse, valid_key

USAGE = "用法：python -m segmerge <run|read|check|page> …"


def _error(message):
    print("error: %s" % message, file=sys.stderr)
    return 2


def _run(args):
    if len(args) != 2:
        return _error("run 需要 <负载.tsv> <输出目录>")
    src, outdir = args
    try:
        data = Path(src).read_bytes()
    except OSError as exc:
        return _error("读不了负载文件：%s" % exc)
    try:
        steps = parse(data)
    except WorkloadError as exc:
        return _error(str(exc))
    out = Path(outdir)
    clean_output_dir(out)
    try:
        replay(steps, out)
    except OSError as exc:
        return _error("写输出目录失败：%s" % exc)
    return 0


def _read(args):
    if len(args) != 2:
        return _error("read 需要 <输出目录> <键>")
    dirpath, key = args
    if not valid_key(key):
        return _error("键不合法")
    try:
        segs = load_dir_segments(dirpath)
    except (OSError, ValueError) as exc:
        return _error("读输出目录失败：%s" % exc)
    for seg in segs:
        value = seg.get(key)
        if value is not MISSING:
            if value is not None:
                sys.stdout.write("%s\t%s\n" % (key, value))
            return 0
    return 0


def _check(args):
    if len(args) != 1:
        return _error("check 需要 <样例根目录>")
    root = Path(args[0])
    if not checker.workloads_root(root).is_dir():
        return _error("样例根目录下没有 workloads/")
    outcomes = checker.check_all(root, Path("var"))
    failed = [outcome for outcome in outcomes if not outcome.ok]
    for outcome in failed:
        print("mismatch=%s" % outcome.name)
    if failed:
        return 1
    print("ok=%d" % len(outcomes))
    return 0


def _page(args):
    if len(args) != 2:
        return _error("page 需要 <样例根目录> <页面.html>")
    root, target = args
    root = Path(root)
    if not checker.workloads_root(root).is_dir():
        return _error("样例根目录下没有 workloads/")
    from . import page as page_mod

    outcomes = checker.check_all(root, Path("var"))
    html_text = page_mod.render(root, outcomes, Path("var"))
    try:
        Path(target).write_bytes(html_text.encode("utf-8"))
    except OSError as exc:
        return _error("写页面失败：%s" % exc)
    return 0


_COMMANDS = {"run": _run, "read": _read, "check": _check, "page": _page}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in _COMMANDS:
        return _error(USAGE)
    return _COMMANDS[args[0]](args[1:])
