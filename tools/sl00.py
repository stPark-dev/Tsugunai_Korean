"""SL00 압축 코덱.

해제 루틴: SCPS_110.07 0x19FCA0 (호출 래퍼 0x19FDF0).
  +0  "SL00"
  +4  u32 해제 크기
  +8  u32: 하위 24비트 = 32항목 그룹 수, 상위 8비트 = 마지막 그룹 항목 수
  이후 그룹마다 u32 LE 플래그(LSB부터), 1=리터럴 1바이트,
  0=참조 2바이트 b0,b1: off = b0 | (b1 & 0xF0) << 4, len = (b1 & 0xF) + 2,
     len == 2 이면 len = 다음 바이트 + 0x12. 복사 원점 = out - off - 1.
  첫 그룹은 그룹 수와 무관하게 무조건 처리된다(0x19FCF8 진입).
"""
import struct

MAGIC = b"SL00"
MAX_DIST = 0x1000
MIN_LEN = 3
MAX_SHORT = 0x11
MAX_LEN = 0xFF + 0x12


class SL00Error(ValueError):
    pass


def decompress(data: bytes) -> bytes:
    if data[:4] != MAGIC:
        raise SL00Error("SL00 매직 아님")
    size, word = struct.unpack_from("<II", data, 4)
    count, tail = word & 0xFFFFFF, word >> 24
    groups = [32] * max(count, 1) + ([tail] if tail else [])
    out = bytearray()
    p = 12
    try:
        for n in groups:
            flags = struct.unpack_from("<I", data, p)[0]
            p += 4
            for _ in range(n):
                if flags & 1:
                    out.append(data[p])
                    p += 1
                else:
                    b0, b1 = data[p], data[p + 1]
                    p += 2
                    off = b0 | ((b1 & 0xF0) << 4)
                    ln = (b1 & 0xF) + 2
                    if ln == 2:
                        ln = data[p] + 0x12
                        p += 1
                    src = len(out) - off - 1
                    if src < 0:
                        raise SL00Error(f"참조가 버퍼 앞을 가리킴 (pos={len(out)})")
                    for i in range(ln):
                        out.append(out[src + i])
                flags >>= 1
    except (IndexError, struct.error) as e:
        raise SL00Error(f"입력이 잘림: {e}") from e
    if len(out) != size:
        raise SL00Error(f"해제 크기 불일치: 헤더 {size}, 실제 {len(out)}")
    return bytes(out)


def _tokens(src: bytes, literal_prefix: int):
    """탐욕적 LZ 토큰화. (None, byte) 리터럴 / (off, len) 참조."""
    heads = {}
    toks = []
    i, n = 0, len(src)
    while i < n:
        best_len, best_off = 0, 0
        if i >= literal_prefix and i + MIN_LEN <= n:
            key = src[i:i + MIN_LEN]
            limit = min(MAX_LEN, n - i)
            for j in reversed(heads.get(key, ())):
                if i - j > MAX_DIST:
                    break
                ln = MIN_LEN
                while ln < limit and src[j + ln] == src[i + ln]:
                    ln += 1
                if ln > best_len:
                    best_len, best_off = ln, i - j - 1
                    if ln == limit:
                        break
        step = best_len if best_len >= MIN_LEN else 1
        toks.append((best_off, best_len) if step > 1 else (None, src[i]))
        for k in range(i, i + step):
            if k + MIN_LEN <= n:
                lst = heads.setdefault(src[k:k + MIN_LEN], [])
                lst.append(k)
                if len(lst) > 64:
                    del lst[:32]
        i += step
    return toks


def compress(src: bytes) -> bytes:
    if len(src) < 32:
        raise SL00Error("32바이트 미만은 원본 해제 루틴과 호환되지 않음")
    toks = _tokens(src, 0)
    if len(toks) < 32:
        toks = _tokens(src, 32)
    body = bytearray()
    for g in range(0, len(toks), 32):
        grp = toks[g:g + 32]
        flags = 0
        chunk = bytearray()
        for k, (off, val) in enumerate(grp):
            if off is None:
                flags |= 1 << k
                chunk.append(val)
            elif val <= MAX_SHORT:
                chunk += bytes([off & 0xFF, ((off >> 4) & 0xF0) | (val - 2)])
            else:
                chunk += bytes([off & 0xFF, (off >> 4) & 0xF0, val - 0x12])
        body += struct.pack("<I", flags) + chunk
    count, tail = divmod(len(toks), 32)
    return MAGIC + struct.pack("<II", len(src), (tail << 24) | count) + bytes(body)
