"""段文件：一层内按键升序的一批记录，文件格式与读写。"""
from __future__ import annotations

import bisect
import os

LEVELS = 5
SEG_LIMIT = 8
ROW_LIMITS = (1024, 8192, 65536, 524288, None)

MISSING = object()


class Segment:
    """内存中的存活段；records 是按键升序的 [(键, 值)]，值为 None 表示墓碑。"""

    __slots__ = ("level", "number", "records", "keys", "nbytes")

    def __init__(self, level, number, records, nbytes=0):
        self.level = level
        self.number = number
        self.records = records
        self.keys = [key for key, _ in records]
        self.nbytes = nbytes

    @property
    def rows(self):
        return len(self.records)

    @property
    def min_key(self):
        return self.keys[0]

    @property
    def max_key(self):
        return self.keys[-1]

    @property
    def tombstones(self):
        return sum(1 for _, value in self.records if value is None)

    def get(self, key):
        """返回值（可能是 None=墓碑），没有该键返回 MISSING。"""
        index = bisect.bisect_left(self.keys, key)
        if index < len(self.keys) and self.keys[index] == key:
            return self.records[index][1]
        return MISSING


def segment_filename(number):
    return "seg-%06d.seg" % number


def encode_segment(level, number, records):
    lines = ["seg\tL%d\t%06d\t%d" % (level, number, len(records))]
    for key, value in records:
        if value is None:
            lines.append("DEL\t" + key)
        else:
            lines.append("PUT\t" + key + "\t" + value)
    return ("\n".join(lines) + "\n").encode("utf-8")


def decode_segment(data):
    """从段文件字节还原 Segment；格式不合法抛 ValueError。"""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("段文件不是合法 UTF-8") from exc
    if not data.endswith(b"\n"):
        raise ValueError("段文件缺少结尾换行")
    lines = text[:-1].split("\n")
    if len(lines) < 1:
        raise ValueError("段文件为空")
    head = lines[0].split("\t")
    if len(head) != 4 or head[0] != "seg" or not head[1].startswith("L"):
        raise ValueError("段头不合法")
    level = int(head[1][1:])
    number = int(head[2])
    declared_rows = int(head[3])
    if not 0 <= level < LEVELS or number < 1:
        raise ValueError("层号或段号不合法")
    records = []
    for line in lines[1:]:
        parts = line.split("\t")
        if parts[0] == "PUT" and len(parts) == 3:
            records.append((parts[1], parts[2]))
        elif parts[0] == "DEL" and len(parts) == 2:
            records.append((parts[1], None))
        else:
            raise ValueError("段内存在不合法记录行")
    if records != sorted(records, key=lambda item: item[0]):
        raise ValueError("段内记录未按键升序排列")
    if len(records) != declared_rows:
        raise ValueError("段头行数与实际行数不符")
    return Segment(level, number, records, nbytes=len(data))


def load_dir_segments(dirpath):
    """读输出目录里的全部存活段，按新到旧（层小者新、同层号大者新）排序。"""
    segs = []
    for name in os.listdir(dirpath):
        if name.startswith("seg-") and name.endswith(".seg"):
            with open(os.path.join(dirpath, name), "rb") as handle:
                segs.append(decode_segment(handle.read()))
    segs.sort(key=lambda seg: (seg.level, -seg.number))
    return segs
