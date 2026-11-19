"""퀘스트 제목 카드(tools/gfx_card.py) 테스트."""
import json
import os

import pytest

from tools.gfx_card import CARD_FONTS, GfxCardError, check_titles, compose
from tools.psi import Psi, clut_swizzle

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
need_font = pytest.mark.skipif(not all(os.path.exists(p) for p, _ in CARD_FONTS.values()), reason="글꼴 없음")
W, H = 512, 128
GOLD, PALE, HALF, ORN = 1, 2, 3, 4


def _psi():
    clut = bytearray(1024)
    for i, rgba in {GOLD: (200, 170, 60, 0x80), PALE: (230, 220, 160, 0x80), HALF: (200, 170, 60, 0x40),
                    ORN: (150, 120, 40, 0x80)}.items():
        clut[clut_swizzle(i) * 4:clut_swizzle(i) * 4 + 4] = bytes(rgba)
    px = bytearray(W * H)
    for y in range(40, 80):                       # 왼쪽 장식 + 위로 뻗은 팔(글자 열 위까지)
        for x in range(40, 80):
            px[y * W + x] = ORN
    for x in range(80, 140):
        px[39 * W + x] = ORN
    for y in range(40, 80):                       # 오른쪽 장식
        for x in range(380, 420):
            px[y * W + x] = ORN
    for y in range(45, 75):                       # 글자(위 밝음, 아래 금색, 가장자리 반투명)
        for x in range(120, 340):
            if (x // 6) % 2 == 0:
                px[y * W + x] = PALE if y < 60 else GOLD
            elif x % 6 == 1:
                px[y * W + x] = HALF
    return Psi(bytes(32), W, H, 8, bytes(clut), bytes(px))


def _ink(p, idx=None):
    return {(i % W, i // W) for i, v in enumerate(p.pixels) if (v == idx if idx is not None else v)}


@need_font
def test_compose_moves_ornaments_and_keeps_center_and_gaps():
    p = _psi()
    q = compose(p, "가나")
    orn0, orn1 = _ink(p, ORN), _ink(q, ORN)
    assert len(orn0) == len(orn1)
    lx = min(x for x, _ in orn1) - min(x for x, _ in orn0)
    rx = max(x for x, _ in orn1) - max(x for x, _ in orn0)
    assert lx > 0 and rx < 0                       # 짧아진 글자 쪽으로 장식이 들어옴
    text = {(x, y) for x, y in _ink(q) if (x, y) not in orn1}
    tx0, tx1 = min(x for x, _ in text), max(x for x, _ in text) + 1
    assert abs((tx0 + tx1) / 2 - 230) <= 2          # 원래 글자 가운데(120..340)
    left_inner = max(x for x, y in orn1 if 40 <= y < 80 and x < tx0) + 1
    right_inner = min(x for x, y in orn1 if 40 <= y < 80 and x >= tx1)
    assert abs((tx0 - left_inner) - 40) <= 1 and abs((right_inner - tx1) - 40) <= 1   # 원래 틈 40px
    assert {q.pixels[y * W + x] for x, y in text} <= {GOLD, PALE, HALF}
    assert all(45 <= y < 75 for _, y in text)


@need_font
def test_longer_text_pushes_ornaments_out():
    p = _psi()
    q = compose(p, "가나다라마바사아자")
    assert min(x for x, _ in _ink(q, ORN)) < 40


@need_font
def test_text_that_pushes_ornaments_off_card_fails():
    with pytest.raises(GfxCardError):
        compose(_psi(), "가나다라마바사아자차카타파하가나다라")


@need_font
def test_bad_text_fails():
    for bad in ("", " ", "가A"):
        with pytest.raises(GfxCardError):
            compose(_psi(), bad)


def test_card_without_two_ornaments_fails():
    p = _psi()
    px = bytearray(p.pixels)
    for i, v in enumerate(px):
        if v == ORN:
            px[i] = 0
    with pytest.raises(GfxCardError):
        compose(Psi(p.header, W, H, 8, p.clut, bytes(px)), "가나")


def _jsonl(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def test_titles_match_reviewed_quest_titles():
    check_titles(_jsonl("text/gfx/TITLE.jsonl"), _jsonl("text/ko_ui/DATA.jsonl"))


def test_check_titles_rejects_mismatch():
    rows = [{"id": "TITLE#00", "src": "試練の始まり", "ko": "다른 제목", "state": "reviewed",
             "path": "/DATAIMG/TITLE/TITLE00.PSI", "record": "RECORD#000.title"}]
    data = [{"id": "RECORD#000.title", "src": "試練の始まり", "ko": "시련의 시작", "state": "reviewed"}]
    with pytest.raises(GfxCardError):
        check_titles(rows, data)


def _title(**kw):
    r = {"id": "TITLE#00", "src": "試練の始まり", "ko": "시련의 시작", "state": "reviewed",
         "path": "/DATAIMG/TITLE/TITLE00.PSI", "record": "RECORD#000.title"}
    r.update(kw)
    return r


DATA_OK = [{"id": "RECORD#000.title", "src": "試練の始まり", "ko": "시련의 시작", "state": "reviewed"}]


@pytest.mark.parametrize("rows,data", [
    ([{k: v for k, v in _title().items() if k != "record"}], DATA_OK),                 # record 없음
    ([_title()], [dict(DATA_OK[0], state="needs_human_review")]),                      # 짝이 미검수
    ([_title(state="untranslated")], DATA_OK),                                          # 번역 있는데 untranslated
    ([_title(state="draft")], DATA_OK),                                                 # 허용 안 된 상태
    ([_title(), _title(id="TITLE#01", path="/DATAIMG/TITLE/TITLE00.PSI")], DATA_OK),     # path 중복·id 불일치
    ([_title(path="/DATAIMG/TITLE/TITLE05.PSI")], DATA_OK),                            # id↔path 불일치
])
def test_check_titles_rejects(rows, data):
    with pytest.raises(GfxCardError):
        check_titles(rows, data)


def test_check_titles_allows_listed_card_without_record():
    check_titles([_title(id="TITLE#34", path="/DATAIMG/TITLE/TITLE34.PSI", src="異国のカクテル",
                         ko="이국의 칵테일", record=None)], DATA_OK)


@need_font
def test_overlap_between_text_and_ornament_fails(monkeypatch):
    import tools.gfx_card as gc
    real = gc._mask
    monkeypatch.setattr(gc, "_mask", lambda ko, h: (lambda w, m: (w + 300, [line + [1.0] * 300 for line in m]))(*real(ko, h)))
    with pytest.raises(GfxCardError):
        compose(_psi(), "가")


def test_32bpp_card_rejected():
    with pytest.raises(GfxCardError):
        compose(Psi(bytes(32), W, H, 32, None, bytes(W * H * 4)), "가")


def test_single_font():
    assert set(CARD_FONTS) == {"medium"}
