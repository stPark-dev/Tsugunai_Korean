"""실행 파일 텍스트 추출·적용 테스트."""
import os
import struct

import pytest

from tools.elf_text import ElfText, ElfTextError, Layout, layout_from_elf
from tools.elfrefs import Ref, find_refs
from tools.textcodec import encode_sjis

DELTA = 0x250000          # va = 파일 오프셋 + DELTA
A0 = 4


def lui(rt, imm):
    return (0x0F << 26) | (rt << 16) | (imm & 0xFFFF)


def addiu(rt, rs, imm):
    return (0x09 << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def sj(s):
    return s.encode("cp932")


def _blob():
    b = bytearray(0x100)

    def put(off, data):
        b[off:off + len(data)] = data

    code = [lui(A0, 0x25), addiu(A0, A0, 0x60),      # S1 @0x60 (hilo)
            lui(A0, 0x25), addiu(A0, A0, 0x80),      # S4 @0x80 (hilo)
            lui(A0, 0x25), addiu(A0, A0, 0x70)]      # S3 @0x70 (hilo, 디버그)
    put(0, b"".join(struct.pack("<I", w) for w in code))
    put(0x40, struct.pack("<II", 0x250068, 0x250088))  # S2 포인터, 0x88 는 문자열 아닌 데이터
    put(0x60, sj("あいう") + b"\0")                     # 7바이트, 다음 문자열 0x68
    put(0x68, sj("か") + b"\0")
    put(0x70, sj("エラー") + b"\n\0")                    # 디버그 (용량 0x70..0x80)
    put(0x80, sj("さ") + b"\0")                          # 다음 0x88 은 참조되는 데이터
    put(0x88, b"\x01\x02\x03\x04")
    put(0x90, sj("レイス") + b"\0")                      # 참조 없음, 고정 버퍼
    return bytes(b)


LAYOUT = Layout(delta=DELTA, text=(0, 0x40), data=((0x40, 0x48),), str_ranges=((0x60, 0x100),),
                gp=0, fixed=(0x250090,))
CODES = {int.from_bytes(sj(c), "big") for c in "あいうかエラーさレイスアイウエオ"}


def _rows(et):
    return {r["id"]: r for r in et.rows()}


def test_extract_rows():
    et = ElfText.parse(_blob(), LAYOUT, CODES)
    rows = _rows(et)
    assert set(rows) == {"ELF#250060", "ELF#250068", "ELF#250070", "ELF#250080", "ELF#250090"}
    assert rows["ELF#250060"]["src"] == "あいう" and rows["ELF#250060"]["cap"] == 7
    assert rows["ELF#250080"]["cap"] == 7          # 0x88 의 참조 데이터 직전까지
    assert rows["ELF#250070"]["debug"] is True
    assert rows["ELF#250090"]["refs"] == 0 and rows["ELF#250090"]["cap"] == 6


def test_apply_nothing_is_identity():
    raw = _blob()
    assert ElfText.parse(raw, LAYOUT, CODES).apply({}, encode_sjis) == raw
    same = {r["id"]: r["src"] for r in ElfText.parse(raw, LAYOUT, CODES).rows()}
    assert ElfText.parse(raw, LAYOUT, CODES).apply(same, encode_sjis) == raw


def test_in_place_when_fits():
    raw = _blob()
    new = ElfText.parse(raw, LAYOUT, CODES).apply({"ELF#250060": "アイ"}, encode_sjis)
    assert new[0x60:0x68] == sj("アイ") + b"\0" * 4
    assert new[:0x60] == raw[:0x60] and new[0x68:] == raw[0x68:]


def test_move_into_debug_slot_and_patch_refs():
    raw = _blob()
    new = ElfText.parse(raw, LAYOUT, CODES).apply({"ELF#250080": "アイウエオ"}, encode_sjis)
    # 디버그 문자열 자리(0x70)로 옮기고 lo 만 수정
    assert new[0x70:0x7B] == sj("アイウエオ") + b"\0"
    assert struct.unpack_from("<I", new, 12)[0] == addiu(A0, A0, 0x70)
    assert new[0x88:0x8C] == b"\x01\x02\x03\x04"


def test_move_without_space_fails():
    with pytest.raises(ElfTextError):
        ElfText.parse(_blob(), LAYOUT, CODES).apply(
            {"ELF#250080": "アイウエオアイウエオ"}, encode_sjis)


def test_fixed_buffer_capacity():
    et = ElfText.parse(_blob(), LAYOUT, CODES)
    assert et.apply({"ELF#250090": "アイウ"}, encode_sjis)[0x90:0x97] == sj("アイウ") + b"\0"
    with pytest.raises(ElfTextError):
        ElfText.parse(_blob(), LAYOUT, CODES).apply({"ELF#250090": "アイウエ"}, encode_sjis)


def test_unknown_id():
    with pytest.raises(ElfTextError):
        ElfText.parse(_blob(), LAYOUT, CODES).apply({"ELF#250061": "ア"}, encode_sjis)


ELF = os.path.join(os.path.dirname(__file__), "..", "work", "ex", "SCPS_110.07")
FONT = os.path.join(os.path.dirname(__file__), "..", "work", "ex", "DATAIMG", "FONT", "FONT.BIN")


@pytest.fixture(scope="module")
def real():
    if not (os.path.exists(ELF) and os.path.exists(FONT)):
        pytest.skip("추출 파일 없음")
    from tools.font import Font
    from tools.sl00 import decompress
    raw = open(ELF, "rb").read()
    codes = set(Font.parse(decompress(open(FONT, "rb").read())).codes)
    return raw, layout_from_elf(raw), codes


def test_real_layout(real):
    raw, lay, _ = real
    assert lay.delta == 0xFF000 and lay.gp == 0x261970
    assert lay.text == (0x1000, 0x1000 + 0x1321BC)


def test_real_inventory(real):
    raw, lay, codes = real
    rows = _rows(ElfText.parse(raw, lay, codes))
    assert rows["ELF#250290"]["src"].startswith("　スロット１のメモリーカード")
    assert rows["ELF#2565c0"]["src"] == "たたかう"
    assert rows["ELF#255d70"]["src"] == "戦闘結果"
    assert rows["ELF#249fd0"]["src"] == "レイス" and rows["ELF#249fd0"]["refs"] == 0
    assert all(r["refs"] > 0 for r in rows.values() if r["id"] not in ("ELF#249fd0", "ELF#24c880"))
    assert ElfText.parse(raw, lay, codes).apply({}, encode_sjis) == raw


def test_real_move_roundtrip(real):
    raw, lay, codes = real
    long = "たたかうたたかうたたかう"
    new = ElfText.parse(raw, lay, codes).apply({"ELF#2565c0": long}, encode_sjis)
    rows = {r["src"]: r for r in ElfText.parse(new, lay, codes).rows()}
    assert long in rows and rows[long]["refs"] >= 1
    assert "たたかう" not in rows
