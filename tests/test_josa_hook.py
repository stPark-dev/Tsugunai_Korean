"""이름 뒤 조사 훅(D8, docs/poc.md PoC5) 테스트.

원본 실행 파일(work/ex/SCPS_110.07)이 있으면 원래 대사 펼치기 함수 0x1b3a98 을 훅과 함께
작은 MIPS 해석기로 돌려, 받침에 따라 조사가 갈리는지 확인한다.
"""
import os
import struct

import pytest

from tests.mips_sim import Sim
from tools.hangul import allocate, encode, josa_table
from tools.josa_hook import EXPANDER, HOOK_END, HOOK_VA, JosaHookError, apply, build

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ELF = os.path.join(ROOT, "work/ex/SCPS_110.07")
need_elf = pytest.mark.skipif(not os.path.exists(ELF), reason="원본 실행 파일 없음")

SLOTS = list(range(0x889F, 0x889F + 40))
CHARS = "레이스각은는이가구먼다"
PAIRS = [("은", "는"), ("이", "가"), ("이구먼", "구먼")]


def _parts():
    a = allocate(CHARS, SLOTS)
    return a, josa_table(PAIRS, a.cmap)


def test_build_layout_fits_dead_function():
    a, table = _parts()
    p = build(a.lo, a.split, table)
    assert set(p) == {EXPANDER, HOOK_VA}
    assert len(p[EXPANDER]) == 8
    j = struct.unpack_from("<I", p[EXPANDER])[0]
    assert j >> 26 == 2 and (j & 0x3FFFFFF) << 2 == HOOK_VA     # j HOOK
    assert HOOK_VA + len(p[HOOK_VA]) <= HOOK_END
    assert p[HOOK_VA].endswith(table)
    with pytest.raises(JosaHookError):
        build(a.lo, a.split, b"\0" * 0x400)                     # 자리 넘침


def test_apply_checks_original_bytes():
    a, table = _parts()
    with pytest.raises(JosaHookError):
        apply(bytearray(0x200000), 0xFF000, build(a.lo, a.split, table))   # 원본과 다르면 실패


# ---- 원본 함수 + 훅 실행 ----
CTX, ENT, SAVE, STR = 0x1000000, 0x1100000, 0x1200000, 0x1300000


def _elf_layout(raw):
    phoff = struct.unpack_from("<I", raw, 0x1C)[0]
    _, off, va, _, filesz = struct.unpack_from("<5I", raw, phoff)
    shoff = struct.unpack_from("<I", raw, 0x20)[0]
    shnum, shstr = struct.unpack_from("<HH", raw, 0x30)
    secs = [struct.unpack_from("<10I", raw, shoff + 40 * i) for i in range(shnum)]
    so = secs[shstr][4]
    gp = next(struct.unpack_from("<I", raw, s[4] + 20)[0] for s in secs
              if raw[so + s[0]:].startswith(b".reginfo\0"))
    return off, va, filesz, gp


def _run(names, text, patched=True):
    raw = bytearray(open(ELF, "rb").read())
    off, va, filesz, gp = _elf_layout(raw)
    a, table = _parts()
    if patched:
        apply(raw, va - off, build(a.lo, a.split, table))
    s = Sim()
    s.load(va, raw[off:off + filesz])
    s.w32(gp - 0x4928, SAVE)
    for i, n in enumerate(names):
        s.load(SAVE + 0x7C + 0x16 * i, encode(n, a.cmap, []) + b"\0")
    s.w32(CTX + 0x1E8, ENT)
    s.load(STR, encode(text, a.cmap, PAIRS) + b"\0")
    s.call(0x1B3A98, [CTX, STR, 8], gp)
    end = s.r32(CTX + 0x1E8)
    rev = {v: k for k, v in a.cmap.items()}
    out = [s.r16(p) for p in range(ENT, end, 8)]
    xs = [s.r16(p + 2) for p in range(ENT, end, 8)]
    return "".join(rev.get(c, "?") for c in out), xs


@need_elf
def test_original_expander_runs_names_in_simulator():
    got, xs = _run(["레이스"], "{n:01}다", patched=False)
    assert got == "레이스다"
    assert xs == [8 + 22 * i for i in range(4)]


@need_elf
@pytest.mark.parametrize("name,expect", [("레이스", "레이스는다"), ("각", "각은다"),
                                         ("이각", "이각은다")])
def test_hook_picks_particle_by_batchim(name, expect):
    got, xs = _run([name], "{n:01}{j:은/는}다")
    assert got == expect
    assert xs == [8 + 22 * i for i in range(len(expect))]       # 조사도 한 칸씩 전진


@need_elf
def test_hook_multichar_particle_and_other_names():
    got, _ = _run(["각", "레이"], "{n:02}{j:이구먼/구먼}{n:01}{j:이/가}")
    assert got == "레이구먼각이"


@need_elf
def test_hook_keeps_unknown_control_skip():
    a, _ = _parts()
    raw = bytearray(open(ELF, "rb").read())
    off, va, filesz, gp = _elf_layout(raw)
    apply(raw, va - off, build(a.lo, a.split, _parts()[1]))
    s = Sim()
    s.load(va, raw[off:off + filesz])
    s.w32(gp - 0x4928, SAVE)
    s.w32(CTX + 0x1E8, ENT)
    da = a.cmap["다"].to_bytes(2, "big")
    s.load(STR, b"\x04" + da + b"\0")                          # 모르는 제어 바이트는 원래대로 건너뜀
    s.call(0x1B3A98, [CTX, STR, 8], gp)
    assert s.r32(CTX + 0x1E8) == ENT + 8 and s.r16(ENT) == a.cmap["다"]
