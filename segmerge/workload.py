"""负载文件解析与校验。"""
from __future__ import annotations

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_STEP_OPS = 20000


class WorkloadError(ValueError):
    """负载内容不合法。"""


class Op:
    """一条输入操作：value 为 None 表示 DEL；nbytes 是行编码的 UTF-8 字节数。"""

    __slots__ = ("key", "value", "nbytes")

    def __init__(self, key, value, nbytes):
        self.key = key
        self.value = value
        self.nbytes = nbytes


def valid_key(key):
    return 1 <= len(key) <= 64 and all("!" <= ch <= "~" for ch in key)


def valid_value_bytes(raw):
    return 1 <= len(raw) <= 255


def parse(data):
    """解析负载字节，返回每步一个 Op 列表；不合法抛 WorkloadError。"""
    if not isinstance(data, bytes):
        data = data.encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        raise WorkloadError("负载超过 8 MiB 上限")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkloadError("负载不是合法 UTF-8") from exc
    steps = []
    current = None
    expected_step = 1
    for lineno, line in enumerate(text.split("\n"), 1):
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        kind = parts[0]
        if kind == "STEP":
            if len(parts) != 2 or not parts[1].isdigit() or int(parts[1]) != expected_step:
                raise WorkloadError("第 %d 行：步号应为 %d" % (lineno, expected_step))
            current = []
            steps.append(current)
            expected_step += 1
        elif kind == "PUT":
            if current is None:
                raise WorkloadError("第 %d 行：操作出现在第一个 STEP 之前" % lineno)
            if len(parts) != 3:
                raise WorkloadError("第 %d 行：PUT 行字段数不对" % lineno)
            key, value = parts[1], parts[2]
            if not valid_key(key):
                raise WorkloadError("第 %d 行：键不合法" % lineno)
            if not valid_value_bytes(value.encode("utf-8")):
                raise WorkloadError("第 %d 行：值长度不在 1–255 字节内" % lineno)
            current.append(Op(key, value, len(("PUT\t%s\t%s\n" % (key, value)).encode("utf-8"))))
        elif kind == "DEL":
            if current is None:
                raise WorkloadError("第 %d 行：操作出现在第一个 STEP 之前" % lineno)
            if len(parts) != 2:
                raise WorkloadError("第 %d 行：DEL 行字段数不对" % lineno)
            key = parts[1]
            if not valid_key(key):
                raise WorkloadError("第 %d 行：键不合法" % lineno)
            current.append(Op(key, None, len(("DEL\t%s\n" % key).encode("utf-8"))))
        else:
            raise WorkloadError("第 %d 行：无法识别的行类型 %r" % (lineno, kind))
        if current is not None and len(current) > MAX_STEP_OPS:
            raise WorkloadError("单步操作数超过 %d 条上限" % MAX_STEP_OPS)
    return steps
