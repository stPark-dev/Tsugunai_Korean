"""PSI 이미지 코덱 테스트."""
import struct

import pytest

from tools.psi import Psi, PsiError, clut_swizzle


def _make(w, h, bpp):
    hdr = bytearray(32)
    struct.pack_into("<HH", hdr, 0x18, w, h)
    if bpp == 8:
        clut = bytes(range(256)) * 4
        return bytes(hdr) + clut + bytes((i * 7) & 0xFF for i in range(w * h))
    return bytes(hdr) + bytes((i * 3) & 0xFF for i in range(w * h * 4))


def test_clut_swizzle_is_involution():
    idx = list(range(256))
    sw = [clut_swizzle(i) for i in idx]
    assert [clut_swizzle(i) for i in sw] == idx
    assert clut_swizzle(8) == 16 and clut_swizzle(16) == 8 and clut_swizzle(0) == 0


@pytest.mark.parametrize("bpp", [8, 32])
def test_roundtrip(bpp):
    raw = _make(16, 8, bpp)
    p = Psi.parse(raw)
    assert (p.width, p.height, p.bpp) == (16, 8, bpp)
    assert p.to_bytes() == raw


def test_rgba_8bpp_uses_swizzled_clut():
    raw = bytearray(_make(2, 1, 8))
    # 픽셀 값 8 → CLUT 위치 16 의 색
    raw[32 + 1024] = 8
    struct.pack_into("<4B", raw, 32 + 16 * 4, 10, 20, 30, 0x80)
    rgba = Psi.parse(bytes(raw)).to_rgba()
    assert rgba[0] == (10, 20, 30, 255)


def test_bad_size():
    with pytest.raises(PsiError):
        Psi.parse(bytes(32) + b"x")


def test_from_rgba_32bpp_roundtrip():
    raw = _make(4, 2, 32)
    p = Psi.parse(raw)
    p2 = p.with_rgba(p.to_rgba())
    assert p2.to_bytes() == raw or p2.to_rgba() == p.to_rgba()
