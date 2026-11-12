"""MODE2/2352 CD 이미지: Form1 섹터 인코딩(EDC/ECC), ISO9660 목록, FILEZ.DAT.

FILEZ.DAT: u32 슬롯 수(2486, 실제 사용 2483) 다음 40바이트 슬롯 3750개.
  슬롯 = u32 사용플래그, u32 크기, u32 LBA, u32 미상A, u32 미상B,
         이름 16바이트(전체 경로에서 '/'·'.' 제거, 뒤 16자), u32 0
"""
import struct
from dataclasses import dataclass

SECTOR = 2352
SYNC = b"\x00" + b"\xff" * 10 + b"\x00"

# --- EDC / ECC (ECMA-130) ---
_EDC = []
for i in range(256):
    e = i
    for _ in range(8):
        e = (e >> 1) ^ (0xD8018001 if e & 1 else 0)
    _EDC.append(e)
_F = [0] * 256
_B = [0] * 256
for i in range(256):
    j = (i << 1) ^ (0x11D if i & 0x80 else 0)
    _F[i] = j
    _B[i ^ j] = i


def edc(data: bytes) -> int:
    e = 0
    for b in data:
        e = (e >> 8) ^ _EDC[(e ^ b) & 0xFF]
    return e


def _ecc_pq(buf: bytearray, major_count, minor_count, major_mult, minor_inc, out_off):
    size = major_count * minor_count
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        a = b = 0
        for _ in range(minor_count):
            t = buf[12 + index]
            index += minor_inc
            if index >= size:
                index -= size
            a ^= t
            b ^= t
            a = _F[a]
        a = _B[_F[a] ^ b]
        buf[out_off + major] = a
        buf[out_off + major + major_count] = a ^ b


def _bcd(n):
    return ((n // 10) << 4) | (n % 10)


def encode_form1(lba: int, subheader: bytes, data: bytes) -> bytes:
    assert len(subheader) == 8 and len(data) == 2048
    a = lba + 150
    hdr = bytes([_bcd(a // 4500), _bcd(a // 75 % 60), _bcd(a % 75), 2])
    buf = bytearray(SYNC + hdr + subheader + data + bytes(4 + 276))
    struct.pack_into("<I", buf, 2072, edc(buf[16:2072]))
    saved = bytes(buf[12:16])
    buf[12:16] = bytes(4)  # Mode2: ECC 계산 시 헤더 0
    _ecc_pq(buf, 86, 24, 2, 86, 2076)   # P
    _ecc_pq(buf, 52, 43, 86, 88, 2076 + 172)  # Q
    buf[12:16] = saved
    return bytes(buf)


# --- ISO9660 ---
@dataclass
class IsoFile:
    path: str
    lba: int
    size: int
    rec_lba: int   # 디렉터리 레코드가 있는 섹터
    rec_off: int   # 섹터 내 오프셋


class Image:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")

    def sector(self, lba):
        self.f.seek(lba * SECTOR)
        return self.f.read(SECTOR)

    def data(self, lba, count=1):
        return b"".join(self.sector(lba + i)[24:24 + 2048] for i in range(count))

    def read_file(self, f: IsoFile) -> bytes:
        return self.data(f.lba, (f.size + 2047) // 2048)[:f.size]

    def list_files(self):
        root = self.data(16)[156:156 + 34]
        out = []
        self._walk(*struct.unpack_from("<I", root, 2), struct.unpack_from("<I", root, 10)[0], "/", out)
        return out

    def _walk(self, lba, size, path, out):
        for s in range((size + 2047) // 2048):
            d = self.data(lba + s)
            i = 0
            while i < 2048 and d[i]:
                ln = d[i]
                r = d[i:i + ln]
                el, sz = struct.unpack_from("<I", r, 2)[0], struct.unpack_from("<I", r, 10)[0]
                name = r[33:33 + r[32]]
                if name not in (b"\0", b"\1"):
                    nm = name.decode("ascii")
                    if r[25] & 2:
                        self._walk(el, sz, path + nm + "/", out)
                    else:
                        out.append(IsoFile(path + nm.split(";")[0], el, sz, lba + s, i))
                i += ln


# --- FILEZ.DAT ---
@dataclass
class FilezEntry:
    slot: int
    flag: int
    size: int
    lba: int
    a: int
    b: int
    name: bytes
    tail: bytes


def filez_name(path: str) -> bytes:
    return path.replace("/", "").replace(".", "").encode()[-16:]


class Filez:
    def __init__(self, count, slots):
        self.count = count
        self.slots = slots  # list of FilezEntry|None(raw bytes)

    @classmethod
    def parse(cls, raw: bytes):
        count = struct.unpack_from("<I", raw, 0)[0]
        slots = []
        for i in range((len(raw) - 4) // 40):
            e = raw[4 + i * 40:44 + i * 40]
            if any(e):
                fl, sz, lba, a, b = struct.unpack_from("<5I", e)
                slots.append(FilezEntry(i, fl, sz, lba, a, b, e[20:36], e[36:]))
            else:
                slots.append(None)
        return cls(count, slots)

    @property
    def entries(self):
        return [s for s in self.slots if s is not None]

    def find(self, path: str) -> FilezEntry:
        key = filez_name(path)
        hits = [e for e in self.entries if e.name.rstrip(b"\0") == key]
        if len(hits) != 1:
            raise KeyError(f"FILEZ 항목 {path}: {len(hits)}건")
        return hits[0]

    def to_bytes(self) -> bytes:
        out = bytearray(struct.pack("<I", self.count))
        for s in self.slots:
            if s is None:
                out += bytes(40)
            else:
                out += struct.pack("<5I", s.flag, s.size, s.lba, s.a, s.b) + s.name + s.tail
        return bytes(out)
