"""GTM 이미지 (STSWIN00·SENNTOU0·WALL_6).

+0x00 32바이트 헤더(+0x0C u16 폭, +0x0E u16 높이) + CLUT 256×u16(ABGR1555, PS2 CSM1 배치) + 8bpp 픽셀(폭×높이).
"""
import struct

from tools.psi import clut_swizzle

HEAD, CLUT = 32, 512


class GtmError(ValueError):
    pass


def _rgba(v):
    c = lambda s: ((v >> s) & 31) * 255 // 31
    return (c(0), c(5), c(10), 255 if v & 0x8000 else 0)


class Gtm:
    def __init__(self, header, width, height, clut, pixels):
        self.header, self.width, self.height = header, width, height
        self.clut, self.pixels = clut, pixels

    @classmethod
    def parse(cls, raw: bytes):
        if len(raw) < HEAD:
            raise GtmError("헤더 잘림")
        w, h = struct.unpack_from("<HH", raw, 0x0C)
        if len(raw) != HEAD + CLUT + w * h:
            raise GtmError(f"크기 {len(raw)} 가 {w}x{h} 8bpp 와 맞지 않음")
        return cls(raw[:HEAD], w, h, raw[HEAD:HEAD + CLUT], bytearray(raw[HEAD + CLUT:]))

    def to_bytes(self) -> bytes:
        return self.header + self.clut + bytes(self.pixels)

    def palette(self):
        """논리 인덱스 → (r, g, b, a255)."""
        return [_rgba(struct.unpack_from("<H", self.clut, 2 * clut_swizzle(i))[0]) for i in range(256)]
