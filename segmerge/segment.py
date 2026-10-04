"""段文件的内存表示、行编码与读写。

段文件格式（UTF-8、LF、末行有换行）：

    seg<TAB>L<层号><TAB><六位段号><TAB>记录行数\\n
    PUT<TAB>键<TAB>值\\n   或   DEL<TAB>键\\n   （按键升序、每键至多一条）
"""

from __future__ import annotations

import os

PUT = "PUT"
DEL = "DEL"

SEG_PREFIX = "seg-"
SEG_SUFFIX = ".seg"


def seg_filename(segno: int) -> str:
    return f"{SEG_PREFIX}{segno:06d}{SEG_SUFFIX}"


def is_seg_filename(name: str) -> bool:
    return name.startswith(SEG_PREFIX) and name.endswith(SEG_SUFFIX)


class Segment:
    """内存中的段：records 是 键->值 的字典，值为 None 表示墓碑。"""

    __slots__ = ("segno", "level", "records", "min_key", "max_key", "nbytes")

    def __init__(self, segno: int, level: int, records: dict, nbytes: int = 0):
        self.segno = segno
        self.level = level
        self.records = records
        if records:
            self.min_key = min(records)
            self.max_key = max(records)
        else:
            self.min_key = ""
            self.max_key = ""
        self.nbytes = nbytes

    @property
    def rows(self) -> int:
        return len(self.records)

    @property
    def tombstone_rows(self) -> int:
        return sum(1 for value in self.records.values() if value is None)

    def contains(self, key: str) -> bool:
        return key in self.records

    def intersects(self, other: "Segment") -> bool:
        if not self.records or not other.records:
            return False
        return self.min_key <= other.max_key and other.min_key <= self.max_key


def encode_segment(level: int, segno: int, records: dict) -> bytes:
    """把记录字典编码成段文件字节（按键升序，同键至多一条）。"""
    lines = [f"seg\tL{level}\t{segno:06d}\t{len(records)}\n"]
    for key in sorted(records):
        value = records[key]
        if value is None:
            lines.append(f"DEL\t{key}\n")
        else:
            lines.append(f"PUT\t{key}\t{value}\n")
    return "".join(lines).encode("utf-8")


def parse_segment(data: bytes) -> Segment:
    """解析段文件字节，返回 Segment（含层号、段号、记录与字节数）。"""
    text = data.decode("utf-8")
    lines = text.split("\n")
    if not lines or lines[-1] != "":
        raise ValueError("段文件末行缺少换行")
    if len(lines) < 2:
        raise ValueError("段文件只有头行")
    header = lines[0].split("\t")
    if len(header) != 4 or header[0] != "seg" or not header[1].startswith("L"):
        raise ValueError("段文件头行不合法")
    level = int(header[1][1:])
    segno = int(header[2])
    row_count = int(header[3])
    if not (0 <= level <= 4):
        raise ValueError("层号越界")
    records: dict = {}
    for line in lines[1:-1]:
        fields = line.split("\t")
        if fields[0] == PUT:
            if len(fields) != 3:
                raise ValueError("PUT 行字段数不对")
            records[fields[1]] = fields[2]
        elif fields[0] == DEL:
            if len(fields) != 2:
                raise ValueError("DEL 行字段数不对")
            records[fields[1]] = None
        else:
            raise ValueError("段内出现非法记录类型")
    if len(records) != row_count:
        raise ValueError("头行行数与记录数不一致")
    if list(records) != sorted(records):
        raise ValueError("段内记录未按键升序")
    return Segment(segno, level, records, len(data))


def write_segment(outdir: str, level: int, segno: int, records: dict) -> Segment:
    data = encode_segment(level, segno, records)
    path = os.path.join(outdir, seg_filename(segno))
    with open(path, "wb") as handle:
        handle.write(data)
    return Segment(segno, level, dict(records), len(data))


def remove_segment(outdir: str, segno: int) -> None:
    os.remove(os.path.join(outdir, seg_filename(segno)))


def load_segments(outdir: str) -> list[Segment]:
    """按新->旧顺序读入输出目录里的全部存活段。"""
    segs: list[Segment] = []
    if not os.path.isdir(outdir):
        return segs
    for name in os.listdir(outdir):
        if not is_seg_filename(name):
            continue
        with open(os.path.join(outdir, name), "rb") as handle:
            segs.append(parse_segment(handle.read()))
    return newer_first(segs)


def newer_first(segs: list[Segment]) -> list[Segment]:
    """层号小的更新，同层段号大的更新。"""
    return sorted(segs, key=lambda seg: (seg.level, -seg.segno))


def is_older(seg: Segment, other: Segment) -> bool:
    """seg 是否比 other 旧。"""
    return (seg.level, -seg.segno) > (other.level, -other.segno)
