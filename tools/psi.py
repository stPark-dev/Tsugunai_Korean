"""PSI 이미지 (SL00 압축일 수도 있음, 호출 쪽에서 해제).

+0x00 32바이트 헤더 (GS TEX0 등, +0x18 u16 폭, +0x1A u16 높이)
이후 크기로 형식 판별:
  32 + 1024 + w*h   → 8bpp, CLUT 256×RGBA (PS2 CSM1 배치, 8-15 ↔ 16-23 교환)
  32 + w*h*4        → 32bpp RGBA
알파 0x80 = 불투명.
"""
import struct


class PsiError(ValueError):
    pass


def clut_swizzle(i):
    return (i & ~0x18) | ((i & 0x08) << 1) | ((i & 0x10) >> 1)


def _a2png(a):
    return min(255, a * 2) if a < 0x80 else 255


def _png2a(a):
    return (a + 1) // 2


class Psi:
    def __init__(self, header, width, height, bpp, clut, pixels):
        self.header, self.width, self.height, self.bpp = header, width, height, bpp
        self.clut, self.pixels = clut, pixels

    @classmethod
    def parse(cls, raw: bytes):
        if len(raw) < 32:
            raise PsiError("헤더 잘림")
        w, h = struct.unpack_from("<HH", raw, 0x18)
        if len(raw) == 32 + 1024 + w * h:
            return cls(raw[:32], w, h, 8, raw[32:1056], raw[1056:])
        if len(raw) == 32 + w * h * 4:
            return cls(raw[:32], w, h, 32, None, raw[32:])
        raise PsiError(f"크기 {len(raw)} 가 {w}x{h} 형식과 맞지 않음")

    def to_bytes(self):
        return self.header + (self.clut or b"") + self.pixels

    def palette(self):
        """논리 인덱스 → (r,g,b,a255)"""
        out = []
        for i in range(256):
            r, g, b, a = self.clut[clut_swizzle(i) * 4:clut_swizzle(i) * 4 + 4]
            out.append((r, g, b, _a2png(a)))
        return out

    def to_rgba(self):
        if self.bpp == 8:
            pal = self.palette()
            return [pal[v] for v in self.pixels]
        p = self.pixels
        return [(p[i], p[i + 1], p[i + 2], _a2png(p[i + 3])) for i in range(0, len(p), 4)]

    def to_png(self, path):
        from PIL import Image
        im = Image.new("RGBA", (self.width, self.height))
        im.putdata(self.to_rgba())
        im.save(path)

    def with_rgba(self, rgba):
        """32bpp: 그대로 저장. 8bpp: 기존 팔레트에 최근접 매핑."""
        if len(rgba) != self.width * self.height:
            raise PsiError("픽셀 수 불일치")
        if self.bpp == 32:
            px = bytearray()
            for r, g, b, a in rgba:
                px += bytes((r, g, b, _png2a(a)))
            return Psi(self.header, self.width, self.height, 32, None, bytes(px))
        pal = self.palette()
        cache = {}

        def near(c):
            if c not in cache:
                cache[c] = min(range(256), key=lambda i: sum((x - y) ** 2 for x, y in zip(pal[i], c)))
            return cache[c]
        return Psi(self.header, self.width, self.height, 8, self.clut, bytes(near(tuple(c)) for c in rgba))
