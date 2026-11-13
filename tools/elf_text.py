"""실행 파일(SCPS_110.07) 텍스트 추출과 적용.

대상: .rodata·.sdata 안의 NUL 종료 Shift-JIS 문자열 가운데 코드에서 참조되는 것
      (`tools/elfrefs.py`: 포인터 / lui+lo / gp), 그리고 참조 없는 고정 버퍼(Layout.fixed).
ID = "ELF#<가상 주소 6자리 hex>".
용량(cap) = 문자열 시작부터 다음 0 아닌 바이트·다음 피참조 주소·다음 문자열 직전까지 - NUL 1바이트.
적용 규칙
  1. 번역이 cap 안이면 제자리에 쓰고 원래 문자열 나머지는 0으로 지운다.
  2. 넘치면 빈 자리로 옮기고 참조를 고친다. 빈 자리 = 디버그 문자열(\n 으로 끝남, 화면에 안 나옴)
     자리 + 이미 옮겨 간 문자열의 원래 자리. lui 는 고치지 않으므로 하위 16비트로 닿는 자리만 쓴다.
  3. 고정 버퍼(참조 없음)는 원래 길이 안에서 제자리만 허용.
  4. 문자열 안쪽 주소를 가리키는 참조가 있으면 옮기지 않는다.
"""
import json
import struct
import sys
from dataclasses import dataclass, field

from tools.elfrefs import ElfRefError, find_refs, patch_ref
from tools.textcodec import decode_sjis

BACKTRACK = 256
SPACE = 0x8140   # 전각 공백: 폰트에 글리프가 없지만 문자열에 쓰인다
FIXED_VA = (0x249FD0, 0x24C880)   # 초기화 데이터 안 기본 이름 「レイス」


class ElfTextError(ValueError):
    pass


@dataclass(frozen=True)
class Layout:
    delta: int                 # 가상 주소 - 파일 오프셋
    text: tuple                # 코드 파일 오프셋 범위
    data: tuple                # 포인터를 찾을 파일 오프셋 범위들
    str_ranges: tuple          # 문자열을 찾을 파일 오프셋 범위들
    gp: int
    fixed: tuple = ()          # 제자리 전용 문자열 가상 주소


def layout_from_elf(raw: bytes) -> Layout:
    shoff, = struct.unpack_from("<I", raw, 0x20)
    shnum, shstrndx = struct.unpack_from("<HH", raw, 0x30)
    secs = [struct.unpack_from("<10I", raw, shoff + 40 * i) for i in range(shnum)]
    stroff = secs[shstrndx][4]

    def name(s):
        n = raw[stroff + s[0]:]
        return n[:n.index(0)].decode()
    by = {name(s): s for s in secs}

    def rng(n):
        s = by[n]
        return (s[4], s[4] + s[5])
    t = by[".text"]
    delta = t[3] - t[4]
    for n in (".data", ".rodata", ".sdata"):
        if by[n][3] - by[n][4] != delta:
            raise ElfTextError(f"{n} 주소-오프셋 차이가 .text 와 다름")
    gp, = struct.unpack_from("<I", raw, by[".reginfo"][4] + 20)
    return Layout(delta, rng(".text"), tuple(rng(n) for n in (".data", ".rodata", ".lit4", ".sdata")),
                  (rng(".rodata"), rng(".sdata")), gp, FIXED_VA)


@dataclass
class Str:
    va: int
    raw: bytes
    refs: list
    cap: int
    fixed: bool = False
    inner: int = 0             # 문자열 안쪽을 가리키는 참조 수

    @property
    def debug(self):
        return self.raw.endswith(b"\n")


def _scan_one(blob, i, end, codes):
    """i 에서 시작하는 문자열 끝(NUL 위치)과 2바이트 글자 수, 아니면 None."""
    j, dbl = i, 0
    while j < end and blob[j]:
        c = blob[j]
        if 0x81 <= c <= 0x9F or 0xE0 <= c <= 0xFC:
            if j + 1 >= end or ((c << 8) | blob[j + 1]) not in codes:
                return None
            dbl += 1
            j += 2
        elif 0x20 <= c < 0x7F or c == 0x0A:
            j += 1
        else:
            return None
    if j >= end or dbl == 0 or dbl * 4 < j - i:
        return None
    return j, dbl


def _candidates(blob, layout, codes):
    codes = set(codes) | {SPACE}
    out = {}
    for a, b in layout.str_ranges:
        i = a
        while i < b:
            if (i == a or blob[i - 1] == 0) and blob[i]:
                r = _scan_one(blob, i, b, codes)
                if r:
                    out[i + layout.delta] = blob[i:r[0]]
                    i = r[0] + 1
                    continue
            i += 1
    return out


@dataclass
class ElfText:
    blob: bytes
    layout: Layout
    strs: dict = field(default_factory=dict)       # va → Str

    @classmethod
    def parse(cls, blob: bytes, layout: Layout, codes):
        cands = _candidates(blob, layout, codes)
        lo = min(a for a, _ in layout.str_ranges) + layout.delta
        hi = max(b for _, b in layout.str_ranges) + layout.delta
        # 문자열 시작 참조는 되짚기까지, 용량을 자르는 다른 피참조 주소는 직선 추적만(오탐 줄임)
        allrefs = find_refs(blob, layout.text, layout.data, layout.gp, range(lo, hi))
        ref_addrs = sorted(allrefs)
        strrefs = find_refs(blob, layout.text, layout.data, layout.gp, set(cands), BACKTRACK)
        et = cls(blob, layout)
        starts = sorted(cands)
        for k, va in enumerate(starts):
            refs = strrefs.get(va, [])
            if not refs:
                continue
            raw = cands[va]
            nxt = starts[k + 1] if k + 1 < len(starts) else hi
            end = et._slot_end(va, len(raw), min(nxt, hi), ref_addrs)
            inner = sum(len(allrefs[a]) for a in ref_addrs if va < a <= va + len(raw))
            et.strs[va] = Str(va, raw, refs, end - va - 1, inner=inner)
        for va in layout.fixed:
            off = va - layout.delta
            raw = blob[off:blob.index(0, off)]
            et.strs[va] = Str(va, raw, [], len(raw), fixed=True)
        return et

    def _slot_end(self, va, n, limit, ref_addrs):
        off = va - self.layout.delta
        p = off + n + 1
        while p + self.layout.delta < limit and self.blob[p] == 0:
            p += 1
        end = p + self.layout.delta
        for a in ref_addrs:
            if va < a < end:
                return a
        return end

    def rows(self):
        return [{"id": f"ELF#{s.va:06x}", "src": decode_sjis(s.raw), "refs": len(s.refs),
                 "cap": s.cap, "debug": s.debug} for _, s in sorted(self.strs.items())]

    def apply(self, texts: dict, encoder) -> bytes:
        out = bytearray(self.blob)
        moves = []
        for rid, text in sorted(texts.items()):
            s = self._get(rid)
            data = encoder(text)
            if data == s.raw:
                continue
            if b"\0" in data:
                raise ElfTextError(f"NUL 포함 {rid}")
            if len(data) <= s.cap:
                self._write(out, s.va, data, len(s.raw) + 1)
            elif s.fixed or not s.refs or s.inner:
                raise ElfTextError(f"{rid}: 제자리 용량 {s.cap}바이트 초과({len(data)}), 옮길 수 없음")
            else:
                moves.append((s, data))
        changed = {s.va for s, _ in moves} | {int(r[4:], 16) for r in texts}
        pool = [(s.va, s.va + s.cap + 1) for s in self.strs.values()
                if s.debug and s.va not in changed]
        for s, data in moves:
            self._move(out, s, data, pool)
            pool.append((s.va, s.va + s.cap + 1))
        return bytes(out)

    def _get(self, rid):
        try:
            va = int(rid.partition("#")[2], 16)
        except ValueError:
            raise ElfTextError(f"잘못된 ID {rid}") from None
        if not rid.startswith("ELF#") or va not in self.strs:
            raise ElfTextError(f"알 수 없는 ID {rid}")
        return self.strs[va]

    def _write(self, out, va, data, old_len):
        off = va - self.layout.delta
        n = max(len(data) + 1, old_len)
        out[off:off + n] = data + b"\0" * (n - len(data))

    def _move(self, out, s, data, pool):
        need = len(data) + 1
        for k, (a, b) in enumerate(pool):
            start = (a + 3) & ~3
            if b - start < need:
                continue
            trial = bytearray(out)
            try:
                for r in s.refs:
                    patch_ref(trial, r, s.va, start, self.layout.gp)
            except ElfRefError:
                continue
            off = s.va - self.layout.delta
            trial[off:off + len(s.raw) + 1] = bytes(len(s.raw) + 1)
            self._write(trial, start, data, 0)
            out[:] = trial
            pool[k] = (start + need, b)
            return
        raise ElfTextError(f"ELF#{s.va:06x}: 옮길 빈 자리 없음({need}바이트)")


def main(elf_path, font_path, out_path):
    from tools.font import Font
    from tools.sl00 import decompress
    raw = open(elf_path, "rb").read()
    codes = Font.parse(decompress(open(font_path, "rb").read())).codes
    rows = ElfText.parse(raw, layout_from_elf(raw), codes).rows()
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(len(rows), "rows ->", out_path)


if __name__ == "__main__":
    main(*sys.argv[1:4])
