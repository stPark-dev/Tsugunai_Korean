"""그림 글자 라벨(tools/gfx_label.py) 테스트."""
import json
import os
import struct

import pytest

from tools.gfx_label import FONTS, GfxLabelError, apply_labels, check_rows
from tools.gtm import Gtm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
need_font = pytest.mark.skipif(not all(os.path.exists(p) for p, _ in FONTS.values()), reason="글꼴 없음")
SHEET = os.path.join(ROOT, "work/ex/DATAIMG/STSWIN00.GTM")
DATA = os.path.join(ROOT, "text/gfx/STSWIN00.jsonl")

CREAM, GOLD, DARK, MID = 1, 2, 3, 4
COLORS = {CREAM: (200, 190, 170), GOLD: (180, 170, 100), DARK: (60, 60, 20), MID: (120, 110, 60),
          9: (0, 0, 255)}


def _gtm(w=96, h=40):
    clut = bytearray(512)
    for i, (r, g, b) in COLORS.items():
        v = (r * 31 // 255) | (g * 31 // 255) << 5 | (b * 31 // 255) << 10
        j = (i & ~0x18) | ((i & 0x08) << 1) | ((i & 0x10) >> 1)
        struct.pack_into("<H", clut, 2 * j, v)
    head = bytearray(32)
    struct.pack_into("<HH", head, 0x0C, w, h)
    g = Gtm.parse(bytes(head) + bytes(clut) + bytes(w * h))
    for y in range(8, 24):                       # 원래 라벨: 위 절반 크림, 아래 절반 금색, 가장자리 어두움
        for x in range(10, 60):
            if (x // 3) % 2 == 0:
                g.pixels[y * w + x] = CREAM if y < 16 else GOLD
            elif x % 3 == 1:
                g.pixels[y * w + x] = DARK
    g.pixels[30 * w + 80] = 9                    # 칸 밖 다른 그림
    return g


def _row(**kw):
    r = {"id": "T#0", "src": "あいう", "ko": "가나", "state": "reviewed", "box": [10, 60, 8, 24],
         "align": "L", "style": "gold"}
    r.update(kw)
    return r


def _ink(g, box):
    x0, x1, y0, y1 = box
    return [(x, y) for y in range(y0, y1) for x in range(x0, x1) if g.pixels[y * g.width + x]]


@need_font
def test_gold_label_uses_original_colors_and_stays_in_box():
    g = _gtm()
    before = bytes(g.pixels)
    apply_labels(g, [_row()])
    ink = _ink(g, (10, 60, 8, 24))
    assert ink and set(ink) != set(_ink(_gtm(), (10, 60, 8, 24)))   # 원래 글자는 지워지고 새 글자
    assert {g.pixels[y * g.width + x] for x, y in ink} <= {CREAM, GOLD, DARK, MID}
    for i, v in enumerate(g.pixels):             # 칸 밖은 그대로
        x, y = i % g.width, i // g.width
        if not (10 <= x < 60 and 8 <= y < 24):
            assert v == before[i]
    top = [g.pixels[y * g.width + x] for x, y in ink if y < 11]
    bottom = [g.pixels[y * g.width + x] for x, y in ink if y >= 20]
    assert top.count(CREAM) > top.count(GOLD) and bottom.count(GOLD) > bottom.count(CREAM)


@need_font
@pytest.mark.parametrize("align", ["L", "R", "C"])
def test_alignment(align):
    g = _gtm()
    apply_labels(g, [_row(align=align, ko="가")])
    xs = [x for x, _ in _ink(g, (10, 60, 8, 24))]
    left, right = min(xs) - 10, 60 - 1 - max(xs)
    if align == "L":
        assert left <= 1 and right > 20
    elif align == "R":
        assert right <= 1 and left > 20
    else:
        assert abs(left - right) <= 2


@need_font
def test_body_limits_ink_rows():
    g = _gtm()
    apply_labels(g, [_row(body=[8, 18])])
    assert max(y for _, y in _ink(g, (10, 60, 8, 24))) < 18


@need_font
def test_untranslated_row_keeps_pixels():
    g = _gtm()
    before = g.to_bytes()
    apply_labels(g, [_row(state="untranslated", ko="")])
    assert g.to_bytes() == before


@need_font
def test_badge_style_uses_given_indices():
    g = _gtm()
    colors = {"top": CREAM, "bottom": GOLD, "shadow": MID, "edge": DARK}
    apply_labels(g, [_row(style="badge", colors=colors, align="C")])
    used = {g.pixels[y * g.width + x] for y in range(8, 24) for x in range(10, 60)}
    assert used <= {0, CREAM, GOLD, MID, DARK} and {CREAM, GOLD, DARK} <= used


@pytest.mark.parametrize("bad", [
    {"align": "X"}, {"style": "neon"}, {"ko": ""}, {"ko": "가A"}, {"box": [10, 5, 8, 24]},
    {"box": [10, 60, 8, 24], "body": [4, 30]}, {"style": "badge"},
    {"ko": " "}, {"box": [10.0, 60, 8, 24]}, {"box": [10, 60, 8]}, {"body": [8]}, {"state": None},
    {"style": "badge", "colors": {"top": 300, "bottom": 1, "shadow": 1, "edge": 1}},
])
def test_check_rows_rejects(bad):
    with pytest.raises(GfxLabelError):
        check_rows([_row(**bad)], 96, 40)


def test_check_rows_rejects_overlap_and_duplicates():
    with pytest.raises(GfxLabelError):
        check_rows([_row(), _row(id="T#1", box=[50, 70, 20, 30])], 96, 40)
    with pytest.raises(GfxLabelError):
        check_rows([_row(), _row(box=[70, 80, 0, 4])], 96, 40)


def _data():
    with open(DATA, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def test_real_rows_valid():
    check_rows(_data(), 512, 512)


@need_font
@pytest.mark.skipif(not os.path.exists(SHEET), reason="추출 파일 없음")
def test_real_sheet_changes_only_inside_boxes():
    raw = open(SHEET, "rb").read()
    g = Gtm.parse(raw)
    rows = _data()
    apply_labels(g, rows)
    inside = set()
    for r in rows:
        x0, x1, y0, y1 = r["box"]
        inside |= {y * 512 + x for y in range(y0, y1) for x in range(x0, x1)}
    old = Gtm.parse(raw).pixels
    changed = {i for i in range(len(old)) if old[i] != g.pixels[i]}
    assert changed and changed <= inside


@need_font
def test_text_that_cannot_fit_fails():
    with pytest.raises(GfxLabelError):
        apply_labels(_gtm(), [_row(ko="가나다라마바사아자차카타파하", box=[10, 30, 8, 24])])


@need_font
def test_box_without_original_glyph_fails():
    with pytest.raises(GfxLabelError):
        apply_labels(_gtm(), [_row(box=[62, 90, 8, 24])])


@need_font
def test_body_without_bright_pixels_fails():
    g = _gtm()
    for i, v in enumerate(g.pixels):
        if v in (CREAM, GOLD):
            g.pixels[i] = DARK
    with pytest.raises(GfxLabelError):
        apply_labels(g, [_row()])


def test_font_hash_mismatch_fails(tmp_path, monkeypatch):
    import tools.gfx_label as gl
    f = tmp_path / "x.ttc"
    f.write_bytes(b"not the font")
    monkeypatch.setattr(gl, "FONTS", {"gold": (str(f), 1), "badge": (str(f), 1)})
    with pytest.raises(GfxLabelError):
        gl.check_fonts()
    monkeypatch.setattr(gl, "FONTS", {"gold": (str(tmp_path / "none.ttc"), 1), "badge": (str(f), 1)})
    with pytest.raises(GfxLabelError):
        gl.check_fonts()


@need_font
def test_system_fonts_match_recorded_hashes():
    import tools.gfx_label as gl
    gl.check_fonts()
