"""이름 입력 음절표(D9) 테스트."""
import os
import struct

import pytest

from tools.name_grid import COLS, PAGES, TABLE, NameGridError, apply, load, targets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DELTA = 0xFF000                                    # 가상 주소 - 파일 오프셋


def _fake_elf():
    """포인터 표 + 원래 가나 열 문자열(10바이트 + NUL)을 가진 가짜 실행 파일."""
    elf = bytearray(0x160000)
    s_va = 0x251000
    for page in range(PAGES):
        for col in range(COLS):
            va = s_va + 0x10 * (page * COLS + col)
            struct.pack_into("<I", elf, TABLE + 0x50 * page + 4 * col - DELTA, va)
            elf[va - DELTA:va - DELTA + 11] = "あいうえお".encode("cp932") + b"\0"
    return elf


def test_load_project_grid():
    cols = load(os.path.join(ROOT, "text/name_grid.txt"))
    assert len(cols) == PAGES * COLS and all(len(c) == 5 for c in cols)
    flat = "".join(cols)
    assert len(set(flat)) == 180
    assert all(ch in flat for ch in "레이스펨라후르크피세아슈고나비미")   # 기본 이름이 다 만들어짐


def test_apply_writes_columns_in_place():
    elf = _fake_elf()
    cols = ["가나다라마"] * (PAGES * COLS)
    enc = lambda s: b"".join(bytes([0x88, 0x9F + "가나다라마".index(c)]) for c in s)
    apply(elf, DELTA, cols, enc)
    va = struct.unpack_from("<I", elf, TABLE + 0x50 + 4 * 17 - DELTA)[0]   # 2쪽 마지막 열
    assert elf[va - DELTA:va - DELTA + 11] == enc("가나다라마") + b"\0"


def test_apply_rejects_wrong_shape():
    elf = _fake_elf()
    enc = lambda s: b"\x88\x9f" * len(s)
    with pytest.raises(NameGridError):
        apply(elf, DELTA, ["가나다라"] * (PAGES * COLS), enc)       # 열 길이 5가 아님
    with pytest.raises(NameGridError):
        apply(elf, DELTA, ["가나다라마"] * 3, enc)                   # 열 수 부족
    bad = _fake_elf()
    struct.pack_into("<I", bad, TABLE - DELTA, 0)                     # 원본 표가 아님
    with pytest.raises(NameGridError):
        apply(bad, DELTA, ["가나다라마"] * (PAGES * COLS), enc)


def test_targets_lists_column_strings():
    elf = _fake_elf()
    t = targets(elf, DELTA)
    assert len(t) == PAGES * COLS and "ELF#251000" in t and f"ELF#{0x251000 + 0x10 * 35:06x}" in t
