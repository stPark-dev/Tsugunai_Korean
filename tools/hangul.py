"""한글 음절 → 폰트 슬롯(원래 한자 코드) 배정과 번역문 인코딩.

받침 있는 음절을 슬롯 앞쪽(lo ≤ 코드 < split), 없는 음절을 뒤쪽에 둔다.
그래서 조사 훅(docs/poc.md PoC5)은 비교 한 번으로 받침을 판정한다.
{j:A/B} → 03 xx (xx = 조사 쌍 표 번호, 1부터 — 0 은 NUL 이라 문자열이 끊김). 0번 칸은 비워 둔다.
표 한 칸 = JOSA_REC 바이트: A(앞 절반), B(뒤 절반),
각각 Shift-JIS 코드 열 + NUL 채움. 조사는 3자까지.
"""
from dataclasses import dataclass

from tools.textcodec import split_tokens

CTRL = {"c": 1, "n": 2}
JOSA_CODE = 3
JOSA_REC = 16
JOSA_MAX = JOSA_REC // 2 // 2 - 1          # 반 칸 8바이트 = 3자 + NUL


class HangulError(ValueError):
    pass


def is_hangul(ch):
    return "가" <= ch <= "힣"


def sjis_bytes(ch):
    """펼치기 함수가 바르게 읽는 Shift-JIS(2바이트 전각 또는 반각 공백)면 바이트, 아니면 None.
    반각 가나(1바이트 0xA1–0xDF)·제어 문자는 바이트 경계가 어긋나므로 거부한다."""
    try:
        b = ch.encode("cp932")
    except UnicodeEncodeError:
        return None
    return b if (len(b) == 2 and b[0] >= 0x81) or b == b" " else None


def has_batchim(ch):
    return is_hangul(ch) and (ord(ch) - 0xAC00) % 28 != 0


@dataclass(frozen=True)
class Allocation:
    cmap: dict          # 음절 → 슬롯 코드
    lo: int             # 첫 슬롯 코드
    split: int          # 받침 없는 음절의 첫 코드(받침 있는 음절은 lo ≤ 코드 < split)


KANJI_RANGES = ((0x889F, 0x9FFC), (0xE040, 0xEAA4))       # Shift-JIS 제1·2수준 한자


def kanji_slots(codes):
    """폰트 코드표에서 한글로 바꿔 쓸 한자 슬롯(오름차순)."""
    return sorted(c for c in codes if any(a <= c <= b for a, b in KANJI_RANGES))


def allocate(chars, slots):
    syl = set(chars)
    bad = sorted(c for c in syl if not is_hangul(c))
    if bad:
        raise HangulError(f"한글 음절이 아님: {''.join(bad)!r}")
    wrong = [c for c in slots if not (0x40 <= (c & 0xFF) <= 0xFC and c & 0xFF != 0x7F)]
    if wrong:
        raise HangulError(f"Shift-JIS 2바이트 코드가 아닌 슬롯 {wrong[0]:#x}")
    order = sorted(syl, key=lambda c: (not has_batchim(c), c))
    slots = sorted(slots)
    if len(order) > len(slots):
        raise HangulError(f"슬롯 부족: 음절 {len(order)} > 슬롯 {len(slots)}")
    cmap = dict(zip(order, slots))
    n_bat = sum(has_batchim(c) for c in order)
    split = slots[n_bat] if n_bat < len(slots) else slots[-1] + 1
    return Allocation(cmap, slots[0], split)


def josa_pairs(texts):
    return sorted({tuple(v.split("/")) for s in texts for k, v in _josa_tokens(s)})


def _josa_tokens(s):
    i = 0
    while (i := s.find("{j:", i)) >= 0:
        j = s.index("}", i)
        yield "j", s[i + 3:j]
        i = j + 1


def _enc_text(t, cmap):
    out = bytearray()
    for ch in t:
        if is_hangul(ch):
            if ch not in cmap:
                raise HangulError(f"배정 안 된 한글 {ch!r}")
            out += cmap[ch].to_bytes(2, "big")
        else:
            b = sjis_bytes(ch)
            if b is None:
                raise HangulError(f"인코딩할 수 없는 글자 {ch!r}")
            out += b
    return bytes(out)


def encode(s, cmap, pairs):
    idx = {p: i + 1 for i, p in enumerate(pairs)}
    out = bytearray()
    pos = 0
    while pos < len(s):
        j = s.find("{j:", pos)
        chunk = s[pos:] if j < 0 else s[pos:j]
        for kind, val in split_tokens(chunk):
            if kind is None:
                out += _enc_text(val, cmap)
            elif kind in CTRL:
                out += bytes([CTRL[kind], val])
            else:
                raise HangulError(f"알 수 없는 토큰 {kind}")
        if j < 0:
            break
        end = s.index("}", j)
        pair = tuple(s[j + 3:end].split("/"))
        if pair not in idx:
            raise HangulError(f"조사 표에 없는 쌍 {pair}")
        out += bytes([JOSA_CODE, idx[pair]])
        pos = end + 1
    return bytes(out)


def josa_table(pairs, cmap):
    half = JOSA_REC // 2
    out = bytearray(JOSA_REC)                      # 0번 칸(쓰지 않음)
    for pair in pairs:
        for p in pair:
            if len(p) > JOSA_MAX:
                raise HangulError(f"조사가 {JOSA_MAX}자를 넘음: {p}")
            out += _enc_text(p, cmap).ljust(half, b"\0")
    return bytes(out)
