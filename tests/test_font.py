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
def test_glyph_hi_nibble_is_left(raw):
    f = Font.parse(raw)
    g = f.glyph(f.index(sjis_code("あ")))
    # 'あ' 첫 줄: 8,9열에 획(값≠0), 그 외 0
    assert [x for x in range(22) if g[0][x]] == [8, 9]


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
