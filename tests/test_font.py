"""FONT.BIN(해제본) 코덱 테스트."""
import os

import pytest

from tools.font import Font, FontError, sjis_code
from tools.sl00 import decompress

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = os.path.join(ROOT, "work", "ex", "DATAIMG", "FONT", "FONT.BIN")
need = pytest.mark.skipif(not os.path.exists(FONT), reason="추출 파일 없음")


@pytest.fixture(scope="module")
def raw():
    return decompress(open(FONT, "rb").read())


def test_sjis_code():
    assert sjis_code("あ") == 0x82A0
    assert sjis_code("A") == 0x41


@need
def test_parse_and_roundtrip(raw):
    f = Font.parse(raw)
    assert (f.width, f.height, len(f.codes)) == (22, 22, 2090)
    assert f.codes == sorted(f.codes)
    assert f.to_bytes() == raw


@need
def test_palette_alpha(raw):
    f = Font.parse(raw)
    assert f.alpha[0] == 0 and f.alpha[2] == 0x80 and f.alpha[5] == 0x20


@need
def test_glyph_first_row(raw):
    f = Font.parse(raw)
    g = f.glyph(f.index(sjis_code("あ")))
    # 'あ' 첫 줄: 8,9열에 획(값≠0), 그 외 0
    assert [x for x in range(22) if g[0][x]] == [8, 9]


def _blank_font():
    return Font(bytes(0x40), 1, 22, 22, [0x889F], [bytes(242)])


def test_low_nibble_is_left_pixel():
    """게임은 글리프 바이트를 그대로 PSMT4 텍스처로 올림(0x1a0fd0 바이트 복사) → GS 는 하위 니블이 왼쪽."""
    f = _blank_font()
    px = [[0] * 22 for _ in range(22)]
    px[0][0], px[0][1], px[1][3] = 1, 2, 5
    px[2][0], px[2][1] = 15, 15                     # 0xF 가 옆 니블로 번지지 않음
    f.set_glyph_indices(0, px)
    assert f.glyphs[0][0] == 0x21 and f.glyphs[0][12] == 0x50 and f.glyphs[0][22] == 0xFF
    assert f.glyph(0) == px


@need
def test_set_glyph_quantizes_to_palette(raw):
    f = Font.parse(raw)
    i = f.index(sjis_code("荒"))
    alpha = [[(x * 6) % 256 for x in range(22)] for _ in range(22)]
    f.set_glyph_alpha(i, alpha)
    g = f.glyph(i)
    for y in range(22):
        for x in range(22):
            want = min(alpha[y][x] * 0x80 // 255, 0x80)
            got = f.alpha[g[y][x]]
            assert abs(got - want) <= 0x10  # 최대 팔레트 간격(0→0x20)의 절반
    assert len(f.to_bytes()) == len(raw)


@need
def test_replace_code_keeps_table_sorted(raw):
    f = Font.parse(raw)
    with pytest.raises(FontError):
        f.index(0xFFFF)
    n = len(f.codes)
    f.set_codes(list(reversed(f.codes)), reorder_glyphs=True)
    assert f.codes == sorted(f.codes) and len(f.codes) == n
    assert f.to_bytes() == raw


def test_render_hangul_fits_cell():
    from tools.font import render_alpha, DEFAULT_TTF
    if not os.path.exists(DEFAULT_TTF[0]):
        pytest.skip("폰트 없음")
    a = render_alpha("한", 22, 22)
    assert len(a) == 22 and all(len(r) == 22 for r in a)
    ink = [(x, y) for y in range(22) for x in range(22) if a[y][x] > 128]
    assert len(ink) > 40
    # 테두리 한 줄은 비워 둠(옆 글자와 붙지 않게)
    assert all(a[y][21] == 0 for y in range(22))


def test_default_ttf_is_noto_kr_bold():
    """D10: 한글 글리프는 Noto Sans CJK KR Bold."""
    from tools.font import DEFAULT_TTF
    if not os.path.exists(DEFAULT_TTF[0]):
        pytest.skip("폰트 없음")
    from PIL import ImageFont
    assert ImageFont.truetype(DEFAULT_TTF[0], 20, index=DEFAULT_TTF[1]).getname() == ("Noto Sans CJK KR", "Bold")


def test_fix_pair_order_rejects_odd_width():
    f = Font(bytes(0x40), 1, 21, 22, [0x889F], [bytes(21 * 22 // 2)])
    with pytest.raises(FontError):
        f.fix_pair_order(0)


def test_put_hangul_fixes_originals_then_renders():
    """D10 순서: 원래 글리프는 픽셀 쌍 교환, 배정 슬롯은 렌더 결과 그대로(교환되지 않음)."""
    from tools.font import put_hangul
    f = Font(bytes(0x40), 1, 22, 22, [0x8140, 0x889F], [bytes([0x21]) + bytes(241)] * 2)
    f.clut = bytes(f.clut[:4]) + b"\xf0\xf0\xf0\x80" + bytes(f.clut[8:])
    alpha = [[255 if x == 0 else 0 for x in range(22)] for _ in range(22)]
    put_hangul(f, {"가": 0x889F}, lambda ch, w, h: alpha)
    assert f.glyphs[0][0] == 0x12                       # 원래 글리프: 교환
    assert f.glyph(1)[0][:2] == [1, 0]                  # 한글: 맨 왼쪽 픽셀이 그대로 왼쪽


def test_fix_pair_order_swaps_each_pixel_pair():
    """D10: 원래 글리프(상위 니블=왼쪽으로 그려짐)를 화면 순서로 바로잡음 = 바이트마다 니블 교환."""
    f = _blank_font()
    f.glyphs[0] = bytes([0x21, 0x50]) + bytes(240)
    before = f.glyph(0)
    f.fix_pair_order(0)
    assert f.glyphs[0][:2] == bytes([0x12, 0x05])
    assert f.glyph(0)[0][:4] == [before[0][1], before[0][0], before[0][3], before[0][2]]


@need
def test_fix_pair_order_makes_original_stroke_solid(raw):
    """원래 「 의 세로 획(상위 니블=왼쪽으로 3·2·6)이 바로잡은 뒤 화면 순서로 이어진 획이 된다."""
    f = Font.parse(raw)
    i = f.index(sjis_code("「"))
    f.fix_pair_order(i)
    assert f.glyph(i)[3][15:18] == [3, 2, 6]
