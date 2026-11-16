"""이름 뒤 조사 훅(D8, docs/poc.md PoC5).

대사 펼치기 함수 0x1b3a98 의 "그 밖의 제어 바이트" 경로(0x1b3b48)를 훅으로 돌린다.
  03 xx → 바로 앞 글리프 항목의 코드(이름 마지막 글자) c 를 보고
          lo ≤ c < split(받침 있음)이면 조사 표[xx] 앞 절반, 아니면 뒤 절반을 펼친다.
  그 밖의 바이트 → 원래대로 1바이트 건너뜀.
훅 코드와 조사 표는 아무도 부르지 않는 디버그 함수 자리 0x1bf380–0x1bf77c 에 둔다.
펼치기 함수 안 레지스터: t0 현재 바이트, a1 다음 바이트, t2 = a1+1, t1 항목 쓰기 위치,
t3 x, a0 y, a2 색. 훅은 v0·v1·a3·at 를 임시로 쓰고, 펼친 만큼 t0·t1·t3·a1 을 원래 흐름처럼 바꾼다.
이름이 비어 있으면 앞 항목을 잘못 읽는다(빈 이름 가능 여부는 미확인).
"""
import struct

from tools.hangul import JOSA_CODE, JOSA_REC

EXPANDER = 0x1B3B48                 # b 0x1b3bc4 / lbu t0,0(a1)
ORIG_EXPANDER = struct.pack("<2I", 0x1000001E, 0x90A80000)
LOOP_NEXT = 0x1B3BBC                # t2 = a1+1; t0 = *a1; 다음 글자
LOOP_TEST = 0x1B3BC4
HOOK_VA, HOOK_END = 0x1BF380, 0x1BF780
ORIG_HOOK = {0x1BF380: 0x27BDFF60, 0x1BF778: 0x27BD00A0}   # 디버그 함수 처음·끝(addiu sp)

ZERO, AT, V0, V1, A0, A1, A2, A3, T0, T1, T3 = 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11


class JosaHookError(ValueError):
    pass


def _i(op, rs, rt, imm):
    return (op << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def _r(rs, rt, rd, sa, fn):
    return (rs << 21) | (rt << 16) | (rd << 11) | (sa << 6) | fn


def _j(target):
    return (2 << 26) | ((target >> 2) & 0x3FFFFFF)


def _b(op, rs, rt, at, to):
    return _i(op, rs, rt, (to - at - 4) >> 2)


def addiu(rt, rs, imm): return _i(0x09, rs, rt, imm)
def sltiu(rt, rs, imm): return _i(0x0B, rs, rt, imm)
def ori(rt, rs, imm): return _i(0x0D, rs, rt, imm)
def lui(rt, imm): return _i(0x0F, 0, rt, imm)
def lbu(rt, off, rs): return _i(0x24, rs, rt, off)
def lhu(rt, off, rs): return _i(0x25, rs, rt, off)
def sh(rt, off, rs): return _i(0x29, rs, rt, off)
def sll(rd, rt, sa): return _r(0, rt, rd, sa, 0x00)
def addu(rd, rs, rt): return _r(rs, rt, rd, 0, 0x21)
def subu(rd, rs, rt): return _r(rs, rt, rd, 0, 0x23)
def or_(rd, rs, rt): return _r(rs, rt, rd, 0, 0x25)


NOP = 0


def build(lo, split, table, hook_va=HOOK_VA):
    """반환: {가상 주소: 덮어쓸 바이트}."""
    if not 0 <= split - lo < 0x8000:
        raise JosaHookError(f"받침 범위 {lo:#x}–{split:#x} 이상")
    if len(table) % JOSA_REC:
        raise JosaHookError("조사 표 크기가 칸 크기의 배수가 아님")
    words = _assemble(hook_va, lo, split, None)
    table_va = hook_va + 4 * len(words)
    words = _assemble(hook_va, lo, split, table_va)
    body = struct.pack(f"<{len(words)}I", *words) + table
    if hook_va + len(body) > HOOK_END:
        raise JosaHookError(f"훅 자리 넘침 {len(body)} B")
    entry = struct.pack("<2I", _j(hook_va), addiu(V1, ZERO, JOSA_CODE))
    return {EXPANDER: entry, hook_va: body}


def _assemble(base, lo, split, table_va):
    t = table_va or 0
    hi_t, lo_t = ((t + 0x8000) >> 16) & 0xFFFF, t & 0xFFFF
    L = {}
    prog = [
        ("bne", T0, V1, "other"),             # t0 != 3 → 원래 경로
        lbu(V0, 0, A1),                       # (지연) xx
        lhu(V1, -8, T1),                      # 앞 항목 코드 = 이름 마지막 글자
        lui(AT, lo >> 16), ori(AT, AT, lo & 0xFFFF),
        subu(V1, V1, AT),
        sltiu(AT, V1, split - lo),            # at = 받침 있음
        sll(V0, V0, JOSA_REC.bit_length() - 1),   # xx * JOSA_REC
        lui(A3, hi_t), addiu(A3, A3, lo_t),
        ("bne", AT, ZERO, "emit"),
        addu(A3, A3, V0),                     # (지연) a3 = 표[xx] 앞 절반
        addiu(A3, A3, JOSA_REC // 2),         # 받침 없음 → 뒤 절반
        "emit", lbu(T0, 0, A3),
        ("beq", T0, ZERO, "done"),
        NOP,
        "loop", lbu(V0, 1, A3),
        sll(V1, T0, 8), or_(V0, V0, V1),
        sh(V0, 0, T1), sh(T3, 2, T1), sh(A0, 4, T1), sh(A2, 6, T1),
        addiu(T3, T3, 0x16), addiu(T1, T1, 8), addiu(A3, A3, 2),
        lbu(T0, 0, A3),
        ("bne", T0, ZERO, "loop"),
        NOP,
        "done", ("j", LOOP_NEXT),
        addiu(A1, A1, 1),                     # (지연) xx 건너뜀
        "other", ("j", LOOP_TEST),
        lbu(T0, 0, A1),                       # (지연) 원래 명령
    ]
    k = 0
    for x in prog:
        if isinstance(x, str):
            L[x] = base + 4 * k
        else:
            k += 1
    out = []
    for x in prog:
        if isinstance(x, str):
            continue
        pc = base + 4 * len(out)
        if isinstance(x, tuple):
            if x[0] == "j":
                out.append(_j(x[1]))
            else:
                out.append(_b(0x05 if x[0] == "bne" else 0x04, x[1], x[2], pc, L[x[3]]))
        else:
            out.append(x)
    return out


def apply(elf, delta, patches):
    """원본 바이트를 확인하고 덮어쓴다(제자리). delta = 가상 주소 - 파일 오프셋."""
    def at(va, n):
        o = va - delta
        if o < 0 or o + n > len(elf):
            raise JosaHookError(f"{va:#x} 가 파일 밖")
        return o
    o = at(EXPANDER, 8)
    if bytes(elf[o:o + 8]) != ORIG_EXPANDER:
        raise JosaHookError("펼치기 함수 원본 바이트가 다름")
    for va, w in ORIG_HOOK.items():
        o = at(va, 4)
        if struct.unpack_from("<I", elf, o)[0] != w:
            raise JosaHookError(f"훅 자리 {va:#x} 원본이 다름")
    for va, b in patches.items():
        o = at(va, len(b))
        elf[o:o + len(b)] = b
