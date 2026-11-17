"""전투 명령 창 가운데 맞춤(tools/ui_layout.py) 테스트.

원본 실행 파일(work/ex/SCPS_110.07)이 있으면 표의 명령이 실제로 `addiu a1, zero, x` 이고
원문 글자 수와 x 가 메뉴마다 같은 가운데를 만드는지(근거) 확인한다.
"""
import json
import os
import struct

import pytest

from tools.build import selected_texts
from tools.elf_text import layout_from_elf
from tools.ui_layout import CENTERED, UiLayoutError, apply

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ELF = os.path.join(ROOT, "work/ex/SCPS_110.07")
need_elf = pytest.mark.skipif(not os.path.exists(ELF), reason="원본 실행 파일 없음")
DELTA = 0x1000


def addiu_a1(x):
    return struct.pack("<I", 0x24050000 | (x & 0xFFFF))


def blob_with(entries):
    """entries = [(명령 VA, 원래 x)] 를 담은 가짜 실행 파일."""
    out = bytearray(0x400)
    for va, x in entries:
        out[va - DELTA:va - DELTA + 4] = addiu_a1(x)
    return out


TABLE = (("m", 0x1100, 48, "ELF#000010"),)
TABLE36 = (("m", 0x1100, 36, "ELF#000010"),)


def test_shorter_translation_moves_right_by_half_advance_per_char():
    elf = blob_with([(0x1100, 48)])
    apply(elf, DELTA, {"ELF#000010": "たたかう"}, {"ELF#000010": "공격"}, TABLE)
    assert elf[0x100:0x104] == addiu_a1(72)


def test_untranslated_keeps_x():
    elf = blob_with([(0x1100, 48)])
    apply(elf, DELTA, {"ELF#000010": "たたかう"}, {}, TABLE)
    assert elf[0x100:0x104] == addiu_a1(48)


def test_longer_translation_moves_left():
    elf = blob_with([(0x1100, 48)])
    apply(elf, DELTA, {"ELF#000010": "たたかう"}, {"ELF#000010": "스토리지다"}, TABLE)
    assert elf[0x100:0x104] == addiu_a1(36)


def test_leading_spaces_are_position_not_width():
    # 원본 「　まほう」(x 36) 의 보이는 가운데 = 36 + 24 + 12×3 = 96. 「마법」 은 x 72, 「　마법」 은 x 48.
    elf = blob_with([(0x1100, 36)])
    apply(elf, DELTA, {"ELF#000010": "　まほう"}, {"ELF#000010": "마법"}, TABLE36)
    assert elf[0x100:0x104] == addiu_a1(72)
    elf = blob_with([(0x1100, 36)])
    apply(elf, DELTA, {"ELF#000010": "　まほう"}, {"ELF#000010": "　마법"}, TABLE36)
    assert elf[0x100:0x104] == addiu_a1(48)


def test_unexpected_instruction_fails():
    elf = blob_with([(0x1100, 50)])
    with pytest.raises(UiLayoutError):
        apply(elf, DELTA, {"ELF#000010": "たたかう"}, {"ELF#000010": "공격"}, TABLE)


@pytest.mark.parametrize("bad", ["공격 ", " 공격", "공격　", "　", ""])
def test_spaces_other_than_leading_fullwidth_fail(bad):
    elf = blob_with([(0x1100, 48)])
    with pytest.raises(UiLayoutError):
        apply(elf, DELTA, {"ELF#000010": "たたかう"}, {"ELF#000010": bad}, TABLE)


def test_missing_source_fails_as_layout_error():
    with pytest.raises(UiLayoutError):
        apply(blob_with([(0x1100, 48)]), DELTA, {}, {}, TABLE)


def test_x_below_zero_fails():
    elf = blob_with([(0x1100, 12)])
    table = (("m", 0x1100, 12, "ELF#000010"),)
    with pytest.raises(UiLayoutError):
        apply(elf, DELTA, {"ELF#000010": "あ"}, {"ELF#000010": "가나다"}, table)


def _jsonl(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return [json.loads(l) for l in f]


def _center(x, s):
    shown = s.lstrip("　")
    return x + 24 * (len(s) - len(shown)) + 12 * len(shown)


@need_elf
def test_real_table_is_centered_addiu():
    with open(ELF, "rb") as f:
        raw = f.read()
    delta = layout_from_elf(raw).delta
    src = {r["id"]: r["src"] for r in _jsonl("text/elf_src.jsonl")}
    centers = {}
    for menu, insn, x, rid in CENTERED:
        w, = struct.unpack_from("<I", raw, insn - delta)
        assert w == 0x24050000 | x, hex(insn)
        centers.setdefault(menu, set()).add(_center(x, src[rid]))
    assert centers == {"battle": {96}, "summon": {98}}


@need_elf
def test_real_translations_keep_centers():
    """빌드와 같은 인자 순서(원문, 번역)로 실제 번역을 적용하면 보이는 가운데가 그대로."""
    with open(ELF, "rb") as f:
        elf = bytearray(f.read())
    delta = layout_from_elf(bytes(elf)).delta
    src = {r["id"]: r["src"] for r in _jsonl("text/elf_src.jsonl")}
    ko = selected_texts(_jsonl("text/ko_ui/ELF.jsonl"))
    apply(elf, delta, src, ko)
    for menu, insn, _x, rid in CENTERED:
        x = struct.unpack_from("<I", elf, insn - delta)[0] & 0xFFFF
        assert _center(x, ko.get(rid, src[rid])) == {"battle": 96, "summon": 98}[menu], rid
