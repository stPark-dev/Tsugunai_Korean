"""원본 이미지에서 파일을 교체한 새 MODE2/2352 이미지를 만든다.

- 원래 섹터 수 안에 들어가면 제자리, 아니면 데이터 끝 뒤로 재배치
- ISO9660 디렉터리 레코드, FILEZ.DAT, PVD 볼륨 크기 갱신
- 마지막에 원본과 섹터 단위로 비교해 계획 밖 차이가 있으면 실패
"""
import os
import shutil
import struct
from dataclasses import dataclass, field

from tools import cdimage
from tools.cdimage import SECTOR

SUB_DATA = bytes.fromhex("0000080000000800")
SUB_EOF = bytes.fromhex("0000890000008900")


class DiscBuildError(RuntimeError):
    pass


@dataclass
class BuildReport:
    relocated: list = field(default_factory=list)
    written_sectors: set = field(default_factory=set)


def _nsec(size):
    return max(1, (size + 2047) // 2048)


def build(src, replacements: dict, out) -> BuildReport:
    src, out = os.path.abspath(src), os.path.abspath(out)
    if os.path.realpath(src) == os.path.realpath(out):
        raise DiscBuildError("원본 이미지를 덮어쓸 수 없음")
    img = cdimage.Image(src)
    files = img.list_files()
    by = {f.path: f for f in files}
    unknown = [p for p in replacements if p not in by]
    if unknown:
        raise DiscBuildError(f"디스크에 없는 경로: {unknown}")
    total = os.path.getsize(src) // SECTOR
    data_end = max(f.lba + _nsec(f.size) for f in files)

    report = BuildReport()
    writes = {}  # lba -> (subheader, 2048 bytes)

    def put_file(lba, payload):
        n = _nsec(len(payload))
        buf = payload.ljust(n * 2048, b"\0")
        for i in range(n):
            writes[lba + i] = (SUB_EOF if i == n - 1 else SUB_DATA, buf[i * 2048:(i + 1) * 2048])

    def dir_patch(f, lba, size):
        sec = writes[f.rec_lba][1] if f.rec_lba in writes else img.data(f.rec_lba)
        sub = writes[f.rec_lba][0] if f.rec_lba in writes else img.sector(f.rec_lba)[16:24]
        b = bytearray(sec)
        o = f.rec_off
        struct.pack_into("<I", b, o + 2, lba)
        struct.pack_into(">I", b, o + 6, lba)
        struct.pack_into("<I", b, o + 10, size)
        struct.pack_into(">I", b, o + 14, size)
        writes[f.rec_lba] = (sub, bytes(b))

    fz = cdimage.Filez.parse(img.read_file(by["/FILEZ.DAT"]))
    cursor = data_end
    placed = {}
    for path in sorted(replacements):
        payload = bytes(replacements[path])
        f = by[path]
        if path == "/FILEZ.DAT":
            raise DiscBuildError("FILEZ.DAT는 빌더가 직접 관리")
        if _nsec(len(payload)) <= _nsec(f.size):
            lba = f.lba
        else:
            lba = cursor
            cursor += _nsec(len(payload))
            report.relocated.append(path)
        put_file(lba, payload)
        placed[path] = (lba, len(payload))
        if (lba, len(payload)) != (f.lba, f.size):
            dir_patch(f, lba, len(payload))
        e = next((e for e in fz.entries if (e.lba, e.size) == (f.lba, f.size)), None)
        if e is None and path not in ("/SYSTEM.CNF", "/SCPS_110.07"):
            raise DiscBuildError(f"FILEZ 항목 없음: {path}")
        if e is not None:
            if e.name.rstrip(b"\0") != cdimage.filez_name(path):
                raise DiscBuildError(f"FILEZ 이름 불일치: {path} {e.name!r}")
            e.lba, e.size = lba, len(payload)

    if placed:
        fzraw = fz.to_bytes()
        put_file(by["/FILEZ.DAT"].lba, fzraw)

    new_total = max(total, cursor)
    if new_total != total:
        pvd = bytearray(img.data(16))
        struct.pack_into("<I", pvd, 80, new_total)
        struct.pack_into(">I", pvd, 84, new_total)
        writes[16] = (img.sector(16)[16:24], bytes(pvd))

    shutil.copyfile(src, out)
    with open(out, "r+b") as fo:
        for lba in sorted(writes):
            sub, data = writes[lba]
            fo.seek(lba * SECTOR)
            fo.write(cdimage.encode_form1(lba, sub, data))
        for lba in range(total, new_total):
            if lba not in writes:
                fo.seek(lba * SECTOR)
                fo.write(cdimage.encode_form1(lba, bytes(8), bytes(2048)))
                writes[lba] = None
    report.written_sectors = set(writes)
    _verify(src, out, total, report.written_sectors)
    return report


def _verify(src, out, total, allowed):
    """원본 범위에서 계획되지 않은 섹터 차이가 있으면 실패."""
    block = 256
    with open(src, "rb") as a, open(out, "rb") as b:
        for base in range(0, total, block):
            x = a.read(block * SECTOR)
            y = b.read(block * SECTOR)
            if x == y:
                continue
            for i in range(len(x) // SECTOR):
                lba = base + i
                if x[i * SECTOR:(i + 1) * SECTOR] != y[i * SECTOR:(i + 1) * SECTOR] and lba not in allowed:
                    raise DiscBuildError(f"계획 밖 섹터 변경: LBA {lba}")
