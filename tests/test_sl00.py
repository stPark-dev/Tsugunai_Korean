"""SL00 압축(실행파일 0x19FCA0 해제 루틴) 코덱 테스트."""
import os
import random
import struct

import pytest

from tools.sl00 import compress, decompress, SL00Error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = os.path.join(ROOT, "work", "ex", "DATAIMG", "FONT", "FONT.BIN")


def _hdr(size, count, tail):
    return b"SL00" + struct.pack("<I", size) + struct.pack("<I", (tail << 24) | count)


def test_literal_only_full_group_plus_tail():
    data = _hdr(35, 1, 3) + struct.pack("<I", 0xFFFFFFFF) + bytes(range(32))
    data += struct.pack("<I", 0b111) + b"abc"
    assert decompress(data) == bytes(range(32)) + b"abc"


def test_zero_count_still_runs_one_group():
    # 0x19FCF8 진입은 무조건: count=0이어도 32항목 처리
    data = _hdr(32, 0, 0) + struct.pack("<I", 0xFFFFFFFF) + bytes(range(32))
    assert decompress(data) == bytes(range(32))


def test_backref_short_and_extended():
    # src = out - off - 1, len = (b1 & 0xf) + 2, 니블 0이면 다음 바이트 + 0x12
    lits = bytes(range(30))
    # 30+2 리터럴 뒤 ref(off=1, len=4) → "abab"
    data = _hdr(36, 1, 1) + struct.pack("<I", 0xFFFFFFFF) + lits + b"ab"
    data += struct.pack("<I", 0b0) + bytes([1, 0x02])
    assert decompress(data) == lits + b"ababab"

    data = _hdr(32 + 0x13, 1, 1) + struct.pack("<I", 0xFFFFFFFF) + bytes(32)
    data += struct.pack("<I", 0) + bytes([0, 0x00, 0x01])  # off=0 len=0x13
    assert decompress(data) == bytes(32 + 0x13)


def test_bad_magic():
    with pytest.raises(SL00Error):
        decompress(b"XXXX" + bytes(12))


def test_size_mismatch_is_error():
    data = _hdr(31, 1, 0) + struct.pack("<I", 0xFFFFFFFF) + bytes(32)
    with pytest.raises(SL00Error):
        decompress(data)


@pytest.mark.parametrize("seed", range(5))
def test_roundtrip_random(seed):
    rnd = random.Random(seed)
    src = bytes(rnd.choice(b"aabbc\x00\xff") for _ in range(rnd.randint(32, 5000)))
    assert decompress(compress(src)) == src


def test_roundtrip_long_runs_and_exact_group_boundary():
    for n in (32, 33, 64, 100, 4096, 4200, 70000):
        src = bytes(n)
        assert decompress(compress(src)) == src


def test_compress_rejects_too_short():
    # 32항목 미만은 원본 해제 루틴이 버퍼를 넘어 쓰므로 거부
    with pytest.raises(SL00Error):
        compress(b"abc")


def test_compressed_items_never_below_one_group():
    src = b"a" * 200  # 매치로 줄이면 32항목 미만이 됨 → 리터럴로 채워야 함
    out = compress(src)
    assert decompress(out) == src
    word = struct.unpack_from("<I", out, 8)[0]
    assert (word & 0xFFFFFF) >= 1


@pytest.mark.skipif(not os.path.exists(FONT), reason="추출 파일 없음")
def test_real_font_decompresses_to_declared_size():
    raw = open(FONT, "rb").read()
    out = decompress(raw)
    assert len(out) == struct.unpack_from("<I", raw, 4)[0]
    assert decompress(compress(out)) == out
