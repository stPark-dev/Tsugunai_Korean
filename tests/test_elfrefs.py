"""실행 파일 주소 참조 탐지·수정 테스트 (MIPS R5900, 리틀 엔디언)."""
import struct

import pytest

from tools.elfrefs import ElfRefError, Ref, find_refs, patch_ref

# 레지스터 번호
V0, A0, A1, T0, S0, GP, RA = 2, 4, 5, 8, 16, 28, 31


def lui(rt, imm):
    return (0x0F << 26) | (rt << 16) | (imm & 0xFFFF)


def addiu(rt, rs, imm):
    return (0x09 << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def ori(rt, rs, imm):
    return (0x0D << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def lbu(rt, rs, imm):
    return (0x24 << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def addu(rd, rs, rt):
    return (rs << 21) | (rt << 16) | (rd << 11) | 0x21


def jal(target):
    return (0x03 << 26) | ((target >> 2) & 0x3FFFFFF)


JR_RA = (RA << 21) | 0x08
NOP = 0


def code(*ins):
    return b"".join(struct.pack("<I", i) for i in ins)


def test_lui_addiu_pair():
    c = code(lui(A0, 0x0025), addiu(A0, A0, 0x1234))
    refs = find_refs(c, text=(0, len(c)), data=[], gp=0, targets={0x251234})
    assert refs == {0x251234: [Ref("hilo", 4, 0)]}


def test_negative_lo_sign_adjust():
    c = code(lui(A0, 0x0026), addiu(A1, A0, -0x7000))  # 0x260000 - 0x7000
    refs = find_refs(c, (0, len(c)), [], 0, {0x259000})
    assert refs[0x259000] == [Ref("hilo", 4, 0)]


def test_ori_is_zero_extended_and_load_user():
    c = code(lui(T0, 0x0025), ori(A0, T0, 0x9000), lbu(V0, T0, 0x10))
    refs = find_refs(c, (0, len(c)), [], 0, {0x259000, 0x250010})
    assert refs[0x259000] == [Ref("hilo", 4, 0)]
    assert refs[0x250010] == [Ref("hilo", 8, 0)]


def test_register_overwrite_invalidates():
    c = code(lui(A0, 0x0025), addu(A0, A1, A1), addiu(A0, A0, 0x1234))
    assert find_refs(c, (0, len(c)), [], 0, {0x251234}) == {}


def test_call_clobbers_temporaries_but_not_saved():
    c = code(lui(A0, 0x0025), lui(S0, 0x0025), jal(0x100000), NOP,
             addiu(A1, A0, 0x10), addiu(A1, S0, 0x20))
    refs = find_refs(c, (0, len(c)), [], 0, {0x250010, 0x250020})
    assert 0x250010 not in refs and refs[0x250020] == [Ref("hilo", 20, 4)]


def test_function_end_clears_after_delay_slot():
    c = code(lui(S0, 0x0025), JR_RA, addiu(A0, S0, 0x10), addiu(A0, S0, 0x20))
    refs = find_refs(c, (0, len(c)), [], 0, {0x250010, 0x250020})
    assert 0x250010 in refs and 0x250020 not in refs


def test_gp_relative():
    c = code(addiu(A0, GP, -0x10))
    refs = find_refs(c, (0, len(c)), [], gp=0x261970, targets={0x261960})
    assert refs == {0x261960: [Ref("gp", 0, None)]}


def test_data_pointer_words():
    blob = code(NOP, 0x00251234, NOP, 0x00251234)
    refs = find_refs(blob, text=(0, 4), data=[(4, 16)], gp=0, targets={0x251234})
    assert refs[0x251234] == [Ref("ptr", 4, None), Ref("ptr", 12, None)]


def test_patch_hilo_same_hi_only_changes_lo():
    c = bytearray(code(lui(A0, 0x0025), addiu(A0, A0, 0x1234)))
    patch_ref(c, Ref("hilo", 4, 0), 0x251234, 0x257F00, gp=0)
    assert find_refs(bytes(c), (0, 8), [], 0, {0x257F00}) == {0x257F00: [Ref("hilo", 4, 0)]}
    assert c[:4] == code(lui(A0, 0x0025))


def test_patch_hilo_different_hi_refused():
    c = bytearray(code(lui(A0, 0x0025), addiu(A0, A0, 0x1234)))
    with pytest.raises(ElfRefError):
        patch_ref(c, Ref("hilo", 4, 0), 0x251234, 0x258000, gp=0)  # 0x258000 은 hi 0x26


def test_patch_ori_needs_unsigned_range():
    c = bytearray(code(lui(T0, 0x0025), ori(A0, T0, 0x9000)))
    patch_ref(c, Ref("hilo", 4, 0), 0x259000, 0x25A000, gp=0)
    assert struct.unpack_from("<I", c, 4)[0] & 0xFFFF == 0xA000


def test_patch_gp_and_ptr():
    c = bytearray(code(addiu(A0, GP, -0x10), 0x00251234))
    patch_ref(c, Ref("gp", 0, None), 0x261960, 0x261000, gp=0x261970)
    patch_ref(c, Ref("ptr", 4, None), 0x251234, 0x252000, gp=0)
    refs = find_refs(bytes(c), (0, 4), [(4, 8)], 0x261970, {0x261000, 0x252000})
    assert refs == {0x261000: [Ref("gp", 0, None)], 0x252000: [Ref("ptr", 4, None)]}
    with pytest.raises(ElfRefError):
        patch_ref(c, Ref("gp", 0, None), 0x261000, 0x271000, gp=0x261970)


def test_patch_checks_old_value():
    c = bytearray(code(0x00251234))
    with pytest.raises(ElfRefError):
        patch_ref(c, Ref("ptr", 0, None), 0x999999, 0x252000, gp=0)


def test_jal_delay_slot_still_sees_lui():
    c = code(lui(A1, 0x0025), jal(0x100000), addiu(A1, A1, 0x10), addiu(A0, A1, 0x20))
    refs = find_refs(c, (0, len(c)), [], 0, {0x250010, 0x250020})
    assert refs == {0x250010: [Ref("hilo", 8, 0)]}


def test_branch_path_lui_found_by_backtrack_marked_loose():
    # beql 지연 슬롯의 lui → 분기 대상에서 사용 (직선 추적은 중간 lui/addiu 로 끊김)
    beql = (0x14 << 26) | (S0 << 21) | 3
    c = code(beql, lui(A0, 0x0025), lui(A0, 0x0025), addiu(A0, A0, 0x10), addiu(A0, A0, 0x20))
    refs = find_refs(c, (0, len(c)), [], 0, {0x250010, 0x250020}, backtrack=64)
    assert refs[0x250010] == [Ref("hilo", 12, 8)]
    assert refs[0x250020] == [Ref("hilo", 16, 8, loose=True)]
    assert 0x250020 not in find_refs(c, (0, len(c)), [], 0, {0x250020})


def test_backtrack_ignores_loads_and_stores():
    swc1 = (0x39 << 26) | (A0 << 21) | (2 << 16) | 0x10
    c = code(lui(A0, 0x0025), addu(A0, A1, A1), swc1, lbu(V0, A0, 0x10))
    assert find_refs(c, (0, len(c)), [], 0, {0x250010}, backtrack=64) == {}


def test_branch_likely_delay_slot_lui_not_on_fallthrough():
    bnel = (0x15 << 26) | (V0 << 21) | 4
    c = code(bnel, lui(A1, 0x0025), addiu(V0, A1, 0x400))
    assert find_refs(c, (0, len(c)), [], 0, {0x250400}) == {}
