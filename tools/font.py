"""FONT.BIN(SL00 해제본) 코덱.

+0x00 CLUT 16×RGBA(32bit), 알파만 의미(0..0x80). 인덱스 15는 툴 쓰레기값.
+0x40 u32 1, +0x44 폭, +0x45 높이, +0x46 u16 글자 수 N
+0x48 코드표 N×u16 (Shift-JIS 값, 오름차순)
이후 글리프 N개, 4bpp, 행 우선, 상위 니블이 왼쪽 픽셀
"""
import struct


class FontError(ValueError):
    pass


def sjis_code(ch: str) -> int:
    return int.from_bytes(ch.encode("cp932"), "big")


class Font:
    def __init__(self, clut, unk40, width, height, codes, glyphs):
        self.clut = bytes(clut)
        self.unk40 = unk40
        self.width, self.height = width, height
        self.codes = list(codes)
        self.glyphs = [bytes(g) for g in glyphs]

    @property
    def gsize(self):
        return self.width * self.height // 2

    @property
    def alpha(self):
        return [self.clut[i * 4 + 3] for i in range(15)]

    @classmethod
    def parse(cls, raw: bytes):
        unk40 = struct.unpack_from("<I", raw, 0x40)[0]
        w, h, n = raw[0x44], raw[0x45], struct.unpack_from("<H", raw, 0x46)[0]
        codes = struct.unpack_from(f"<{n}H", raw, 0x48)
        base = 0x48 + 2 * n
        gs = w * h // 2
        if base + n * gs != len(raw):
            raise FontError(f"크기 불일치 {base + n * gs} != {len(raw)}")
        return cls(raw[:0x40], unk40, w, h, codes,
                   [raw[base + i * gs:base + (i + 1) * gs] for i in range(n)])

    def to_bytes(self) -> bytes:
        if list(self.codes) != sorted(set(self.codes)):
            raise FontError("코드표는 중복 없는 오름차순이어야 함")
        n = len(self.codes)
        hdr = self.clut + struct.pack("<IBBH", self.unk40, self.width, self.height, n)
        return hdr + struct.pack(f"<{n}H", *self.codes) + b"".join(self.glyphs)

    def index(self, code: int) -> int:
        try:
            return self.codes.index(code)
        except ValueError:
            raise FontError(f"코드 {code:#x} 없음") from None

    def glyph(self, i):
        g = self.glyphs[i]
        w = self.width
        return [[(g[(y * w + x) // 2] >> 4) if x % 2 == 0 else (g[(y * w + x) // 2] & 0xF)
                 for x in range(w)] for y in range(self.height)]

    def set_glyph_indices(self, i, px):
        w = self.width
        out = bytearray(self.gsize)
        for y in range(self.height):
            for x in range(w):
                v = px[y][x]
                k = (y * w + x) // 2
                out[k] |= (v << 4) if x % 2 == 0 else v
        self.glyphs[i] = bytes(out)

    def set_glyph_alpha(self, i, alpha255):
        """0..255 알파 비트맵을 팔레트 알파(0..0x80)에 최근접 양자화."""
        pal = self.alpha
        cands = sorted({a: k for k, a in reversed(list(enumerate(pal)))}.items())
        def q(a):
            t = min(a * 0x80 // 255, 0x80)
            return min(cands, key=lambda c: abs(c[0] - t))[1]
        self.set_glyph_indices(i, [[q(a) for a in row] for row in alpha255])

    def set_codes(self, codes, reorder_glyphs=False):
        """코드 목록 교체. reorder_glyphs면 (code, glyph) 쌍을 코드순으로 정렬."""
        if len(codes) != len(self.glyphs):
            raise FontError("코드 수와 글리프 수가 다름")
        pairs = list(zip(codes, self.glyphs))
        if reorder_glyphs:
            orig = dict(zip(self.codes, self.glyphs))
            pairs = sorted((c, orig.get(c, g)) for c, g in pairs)
        self.codes = [c for c, _ in pairs]
        self.glyphs = [g for _, g in pairs]


DEFAULT_TTF = ("/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc", 1)  # Noto Sans CJK KR Medium


def render_alpha(ch, w, h, ttf=DEFAULT_TTF, size=20):
    """글자를 w×h 0..255 알파 비트맵으로. 오른쪽 1열은 비운다."""
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(ttf[0], size, index=ttf[1])
    im = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(im)
    l, t, r, b = dr.textbbox((0, 0), ch, font=font)
    ox = (w - 1 - (r - l)) // 2 - l
    oy = (h - (b - t)) // 2 - t
    dr.text((ox, oy), ch, font=font, fill=255)
    px = im.load()
    return [[px[x, y] if x < w - 1 else 0 for x in range(w)] for y in range(h)]
