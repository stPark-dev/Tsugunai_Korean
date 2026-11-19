"""GTM 이미지(tools/gtm.py) 테스트."""
import os
import struct

import pytest

from tools.gtm import Gtm, GtmError

EX = os.path.join(os.path.dirname(__file__), "..", "work", "ex", "DATAIMG")


def _raw(w, h, clut=None, px=None):
    head = bytearray(32)
    struct.pack_into("<HH", head, 0x0C, w, h)
    clut = clut if clut is not None else bytes(512)
    px = px if px is not None else bytes(range(256)) * (w * h // 256) + bytes(w * h % 256)
    return bytes(head) + clut + px


def test_parse_roundtrip_and_size():
    raw = _raw(16, 16)
    g = Gtm.parse(raw)
    assert (g.width, g.height) == (16, 16)
    assert g.to_bytes() == raw
    g.pixels[0] = 7
    assert g.to_bytes()[32 + 512] == 7


def test_size_mismatch_fails():
    with pytest.raises(GtmError):
        Gtm.parse(_raw(16, 16)[:-1])
    with pytest.raises(GtmError):
        Gtm.parse(b"\0" * 10)


def test_palette_abgr1555_with_csm1_swizzle():
    clut = bytearray(512)
    # 논리 인덱스 8 은 저장 위치 16 (CSM1: 8-15 ↔ 16-23)
    struct.pack_into("<H", clut, 16 * 2, 0x8000 | (31 << 10) | (0 << 5) | 31)   # a=1, b=31, r=31
    struct.pack_into("<H", clut, 1 * 2, (31 << 5))                              # a=0, g=31
    pal = Gtm.parse(_raw(16, 16, bytes(clut))).palette()
    assert pal[8] == (255, 0, 255, 255)
    assert pal[1] == (0, 255, 0, 0)


def test_real_stswin():
    fn = os.path.join(EX, "STSWIN00.GTM")
    if not os.path.exists(fn):
        pytest.skip("추출 파일 없음")
    raw = open(fn, "rb").read()
    g = Gtm.parse(raw)
    assert (g.width, g.height) == (512, 512) and g.to_bytes() == raw
