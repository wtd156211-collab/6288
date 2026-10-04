"""负载文件解析与校验。

格式（UTF-8、LF、末行有换行）：`STEP<TAB>步号` 开一步（步号从 1 连续递增），
其后是 `PUT<TAB>键<TAB>值` 或 `DEL<TAB>键`；`#` 行与空行忽略；
单步 <= 20000 条操作，单份 <= 8 MiB。
"""

from __future__ import annotations

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_STEP_OPS = 20000
MAX_KEY_BYTES = 64
MAX_VALUE_BYTES = 255


class WorkloadError(Exception):
    """负载不合法。"""


def _check_key(key: str, lineno: int) -> None:
    if not key:
        raise WorkloadError(f"第 {lineno} 行：键为空")
    if len(key.encode("utf-8")) > MAX_KEY_BYTES:
        raise WorkloadError(f"第 {lineno} 行：键超过 64 字节")
    for ch in key:
        if not ("!" <= ch <= "~"):
            raise WorkloadError(f"第 {lineno} 行：键含非法字符")


def _check_value(value: str, lineno: int) -> None:
    if not value:
        raise WorkloadError(f"第 {lineno} 行：值为空")
    if len(value.encode("utf-8")) > MAX_VALUE_BYTES:
        raise WorkloadError(f"第 {lineno} 行：值超过 255 字节")


def parse_workload_bytes(data: bytes) -> list:
    """把负载字节解析成 [(步号, [(键, 值|None), ...]), ...]，保持文件内顺序。"""
    if len(data) > MAX_FILE_BYTES:
        raise WorkloadError("负载超过 8 MiB")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkloadError("负载不是合法 UTF-8") from exc
    if "\r" in text:
        raise WorkloadError("负载含 CR，应为 LF 换行")
    steps: list = []
    current_ops: list | None = None
    expected_step = 1
    for lineno, line in enumerate(text.split("\n"), start=1):
        if line == "" or line.startswith("#"):
            continue
        fields = line.split("\t")
        head = fields[0]
        if head == "STEP":
            if len(fields) != 2 or not fields[1].isdigit():
                raise WorkloadError(f"第 {lineno} 行：STEP 行不合法")
            step_no = int(fields[1])
            if step_no != expected_step:
                raise WorkloadError(
                    f"第 {lineno} 行：步号应为 {expected_step}，实为 {step_no}"
                )
            expected_step += 1
            current_ops = []
            steps.append((step_no, current_ops))
        elif head == "PUT":
            if current_ops is None:
                raise WorkloadError(f"第 {lineno} 行：操作出现在 STEP 之前")
            if len(fields) != 3:
                raise WorkloadError(f"第 {lineno} 行：PUT 行字段数不对")
            _check_key(fields[1], lineno)
            _check_value(fields[2], lineno)
            current_ops.append((fields[1], fields[2]))
        elif head == "DEL":
            if current_ops is None:
                raise WorkloadError(f"第 {lineno} 行：操作出现在 STEP 之前")
            if len(fields) != 2:
                raise WorkloadError(f"第 {lineno} 行：DEL 行字段数不对")
            _check_key(fields[1], lineno)
            current_ops.append((fields[1], None))
        else:
            raise WorkloadError(f"第 {lineno} 行：无法识别的指令 {head!r}")
        if current_ops is not None and len(current_ops) > MAX_STEP_OPS:
            raise WorkloadError(f"第 {lineno} 行：单步操作数超过 {MAX_STEP_OPS}")
    return steps


def load_workload(path: str) -> list:
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        raise WorkloadError(f"读不了负载文件：{exc}") from exc
    return parse_workload_bytes(data)


def op_encoded_bytes(key: str, value) -> int:
    """一条操作按行编码的字节数（计入输入字节）。"""
    if value is None:
        return len(f"DEL\t{key}\n".encode("utf-8"))
    return len(f"PUT\t{key}\t{value}\n".encode("utf-8"))
