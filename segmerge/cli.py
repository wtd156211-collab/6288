"""命令行入口：run / read / check / page。"""

from __future__ import annotations

import os
import sys

from .checker import check_all
from .engine import run_workload
from .segment import load_segments
from .workload import WorkloadError, load_workload

USAGE = (
    "用法：python -m segmerge run <负载.tsv> <输出目录>\n"
    "      python -m segmerge read <输出目录> <键>\n"
    "      python -m segmerge check <样例根目录>\n"
    "      python -m segmerge page <样例根目录> <页面.html>"
)


def _error(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def _cmd_run(args: list) -> int:
    if len(args) != 2:
        return _error(USAGE)
    workload_path, outdir = args
    steps = load_workload(workload_path)
    run_workload(steps, outdir)
    return 0


def _cmd_read(args: list) -> int:
    if len(args) != 2:
        return _error(USAGE)
    outdir, key = args
    if not key or len(key.encode("utf-8")) > 64 or any(not "!" <= ch <= "~" for ch in key):
        return _error("键不合法")
    if not os.path.isdir(outdir):
        return _error(f"输出目录不存在：{outdir}")
    for seg in load_segments(outdir):
        if key in seg.records:
            value = seg.records[key]
            if value is not None:
                print(f"{key}\t{value}")
            return 0
    return 0


def _cmd_check(args: list) -> int:
    if len(args) != 1:
        return _error(USAGE)
    results = check_all(args[0])
    if not results:
        return _error("样例根目录下没有找到负载")
    failed = [result for result in results if not result.ok]
    if failed:
        for result in failed:
            print(f"mismatch={result.name}")
        return 1
    print(f"ok={len(results)}")
    return 0


def _cmd_page(args: list) -> int:
    if len(args) != 2:
        return _error(USAGE)
    from .page import generate_page

    generate_page(args[0], args[1])
    return 0


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return _error(USAGE)
    command, rest = args[0], args[1:]
    handlers = {
        "run": _cmd_run,
        "read": _cmd_read,
        "check": _cmd_check,
        "page": _cmd_page,
    }
    handler = handlers.get(command)
    if handler is None:
        return _error(USAGE)
    try:
        return handler(rest)
    except WorkloadError as exc:
        return _error(str(exc))
    except OSError as exc:
        return _error(str(exc))
