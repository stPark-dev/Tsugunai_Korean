"""데이터 파일 텍스트 코덱 (ITEM / INVENT / WEAPON / MAGIC / AMULET / RECORD / EST).

오프셋 표 파일(TableFile): 파일 앞 u32 오프셋 표 → 레코드. 표 길이는 따로 없고,
  유효한(파일 안·단조 증가) 값이 이어지는 데까지가 레코드 수다. 표 뒤의 0xCD 칸은 그대로 둔다.
  레코드 = 고정 머리(str_at 바이트, lens_at 에 필드별 u8 길이) + NUL 종료 문자열 필드들.
  - ITEM   머리 0x20 + 길이 2개(+2 패딩), 필드 4정렬: 이름, 설명
  - INVENT 길이 2개(+2), 필드 정렬 없음(길이 = 문자열+NUL): 이름, 설명
  - WEAPON 머리 8 + 길이 3개(+1), 4정렬: 이름, 필살기 이름, 설명
  - AMULET 머리 6 + 길이 2개, 4정렬: 호부 이름, 소환수 이름.
           0번 레코드는 머리가 오프셋 표에 덮여 있다(표가 나중에 늘어난 흔적).
           이런 레코드는 표 끝부터 필드가 이어진다고 보고 제자리에서만 고친다(용량 고정).
  - MAGIC  머리 0x24, 길이 바이트 없음, 설명 1개
RECORD: u32 개수 c + 오프셋 2c개(제목, 설명) + 빈틈없이 이어진 문자열.
EST: u32×128 그룹 표(0 = 빈 칸) → 그룹 = 84바이트 몬스터 레코드 묶음, +0 에 32바이트 고정 이름 칸.
"""
import struct
from dataclasses import dataclass, field


class DataFileError(ValueError):
    pass


@dataclass(frozen=True)
class Spec:
    nfields: int
    str_at: int
    lens_at: int | None
    falign: int


SPECS = {
    "ITEM": Spec(2, 0x24, 0x20, 4),
    "INVENT": Spec(2, 4, 0, 1),
    "WEAPON": Spec(3, 0x0C, 8, 4),
    "AMULET": Spec(2, 8, 6, 4),
    "MAGIC": Spec(1, 0x24, None, 1),
}


def pad(b: bytes, n: int) -> bytes:
    return b + b"\0" * (-len(b) % n)


def _cstr(b: bytes, where: str) -> bytes:
    i = b.find(0)
    if i < 0:
        raise DataFileError(f"NUL 없는 문자열 {where}")
    return b[:i]


@dataclass
class Rec:
    start: int
    end: int
    fields: list
    orig: tuple
    caps: list | None = None   # 제자리 레코드: 필드별 (위치, 용량)
    dirty: bool = False

    @property
    def changed(self):
        return self.dirty or tuple(self.fields) != self.orig


@dataclass
class TableFile:
    raw: bytes
    spec: Spec
    table_end: int
    records: list = field(default_factory=list)

    @staticmethod
    def _offsets(raw):
        offs = []
        while 4 * len(offs) + 4 <= len(raw):
            v = struct.unpack_from("<I", raw, 4 * len(offs))[0]
            if v >= len(raw) or (offs and v < offs[-1]):
                break
            offs.append(v)
        if not offs:
            raise DataFileError("오프셋 표 없음")
        return offs

    @classmethod
    def parse(cls, raw: bytes, spec: Spec):
        offs = cls._offsets(raw)
        table_end = max(4 * len(offs), offs[0])
        f = cls(raw, spec, table_end)
        ends = offs[1:] + [len(raw)]
        for a, b in zip(offs, ends):
            if a < table_end:
                fields, caps = f._parse_inplace(b)
            else:
                fields, caps = f._parse_rec(a, b), None
            f.records.append(Rec(a, b, fields, tuple(fields), caps))
        return f

    def _parse_inplace(self, end):
        fields, caps, p = [], [], self.table_end
        for _ in range(self.spec.nfields):
            s = _cstr(self.raw[p:end], f"@{p:#x}")
            cap = len(pad(s + b"\0", self.spec.falign))
            fields.append(s)
            caps.append((p, cap))
            p += cap
        return fields, caps

    def _parse_rec(self, a, b):
        sp, raw = self.spec, self.raw
        p = a + sp.str_at
        if sp.lens_at is None:
            return [_cstr(raw[p:b], f"@{p:#x}")]
        fields = []
        for ln in raw[a + sp.lens_at:a + sp.lens_at + sp.nfields]:
            s = _cstr(raw[p:p + ln], f"@{p:#x}")
            fields.append(s)
            p += ln
        if p > b:
            raise DataFileError(f"레코드 @{a:#x} 길이 초과")
        return fields

    def _build_rec(self, r):
        sp = self.spec
        head = bytearray(self.raw[r.start:r.start + sp.str_at])
        body = b""
        for k, s in enumerate(r.fields):
            fb = pad(s + b"\0", sp.falign)
            if sp.lens_at is not None:
                if len(fb) > 0xFF:
                    raise DataFileError(f"필드 길이 255 초과 @{r.start:#x}")
                head[sp.lens_at + k] = len(fb)
            body += fb
        return pad(bytes(head) + body, 4)

    def to_bytes(self) -> bytes:
        out = bytearray(self.raw[:self.table_end])
        normal = [r for r in self.records if r.caps is None]
        inplace_end = normal[0].start if normal else len(self.raw)
        out += self.raw[self.table_end:inplace_end]
        for r in self.records:
            if r.caps is not None and r.changed:
                for s, (p, cap) in zip(r.fields, r.caps):
                    if len(s) + 1 > cap:
                        raise DataFileError(f"제자리 필드 용량 {cap - 1}바이트 초과 @{p:#x}")
                    out[p:p + cap] = (s + b"\0").ljust(cap, b"\0")
        for i, r in enumerate(self.records):
            if r.caps is not None:
                continue
            out += b"\0" * (-len(out) % 4)
            struct.pack_into("<I", out, 4 * i, len(out))
            out += self._build_rec(r) if r.changed else self.raw[r.start:r.end]
        return bytes(out)


@dataclass
class RecordFile:
    raw: bytes
    fields: list

    @classmethod
    def parse(cls, raw: bytes):
        c = struct.unpack_from("<I", raw, 0)[0]
        if 4 + 8 * c > len(raw):
            raise DataFileError("RECORD 개수 이상")
        offs = struct.unpack_from(f"<{2 * c}I", raw, 4)
        return cls(raw, [_cstr(raw[o:], f"@{o:#x}") for o in offs])

    def to_bytes(self) -> bytes:
        head = bytearray(self.raw[:4 + 8 * (len(self.fields) // 2)])
        body = b""
        for k, s in enumerate(self.fields):
            struct.pack_into("<I", head, 4 + 4 * k, len(head) + len(body))
            body += s + b"\0"
        return bytes(head) + body


EST_SLOTS, EST_REC, EST_NAME = 128, 84, 32


@dataclass
class EstFile:
    raw: bytes
    pos: dict          # (슬롯, 그룹 내 순번) → 이름 칸 위치
    new: dict = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: bytes):
        tab = struct.unpack_from(f"<{EST_SLOTS}I", raw, 0)
        starts = sorted({o for o in tab if o})
        ends = dict(zip(starts, starts[1:] + [len(raw)]))
        pos = {}
        for slot, o in enumerate(tab):
            if not o:
                continue
            if (ends[o] - o) % EST_REC:
                raise DataFileError(f"EST 그룹 @{o:#x} 크기가 84의 배수가 아님")
            for k in range((ends[o] - o) // EST_REC):
                pos[(slot, k)] = o + k * EST_REC
        return cls(raw, pos)

    def names(self):
        return [(key, _cstr(self.new.get(key, self.raw[p:p + EST_NAME]), f"@{p:#x}"))
                for key, p in sorted(self.pos.items())]

    def set_name(self, key, s: bytes):
        if key not in self.pos:
            raise DataFileError(f"EST 키 없음 {key}")
        if len(s) + 1 > EST_NAME:
            raise DataFileError(f"EST 이름 {EST_NAME - 1}바이트 초과: {key}")
        self.new[key] = (s + b"\0").ljust(EST_NAME, b"\0")

    def to_bytes(self) -> bytes:
        out = bytearray(self.raw)
        for key, b in self.new.items():
            p = self.pos[key]
            out[p:p + EST_NAME] = b
        return bytes(out)
