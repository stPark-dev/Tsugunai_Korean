"""실행 파일(MIPS R5900) 안의 주소 참조 탐지·수정.

참조 종류
  hilo  lui rX,hi 뒤에 rX 를 베이스로 쓰는 addiu/daddiu/ori/로드/스토어 (lo 명령 위치, lui 위치)
  gp    gp($28) 상대 addiu/로드/스토어 (.sdata·.lit4 등)
  ptr   데이터 구역의 4바이트 정렬 워드
레지스터 값 추적은 직선 코드 기준 근사다. 다른 명령이 레지스터를 덮어쓰면, 호출(jal/jalr) 뒤
임시 레지스터는(지연 슬롯 다음부터), 함수 끝(jr 다음 지연 슬롯 뒤)에는 모두 버린다. 잘못 짝지은 경우를 막으려고
계산된 주소가 targets(문자열 시작 주소)에 정확히 맞을 때만 참조로 본다.
"""
import struct
from dataclasses import dataclass


class ElfRefError(ValueError):
    pass


@dataclass(frozen=True)
class Ref:
    kind: str
    off: int           # 수정할 명령/워드의 파일 오프셋
    lui_off: int | None
    loose: bool = False   # 직선 추적 실패 후 되짚기로 찾음 → 검토 대상


LUI, ORI = 0x0F, 0x0D
ADDI_OPS = {0x09, 0x19}                                   # addiu, daddiu
LOAD_OPS = {0x20, 0x21, 0x23, 0x24, 0x25, 0x27, 0x37, 0x1E, 0x31, 0x22, 0x26, 0x1A, 0x1B}
STORE_OPS = {0x28, 0x29, 0x2B, 0x3F, 0x1F, 0x39, 0x2A, 0x2E, 0x2C, 0x2D}
ADDR_OPS = ADDI_OPS | {ORI}                               # 주소를 만드는 명령
USER_OPS = ADDR_OPS | LOAD_OPS | STORE_OPS
RT_WRITERS = ADDI_OPS | {LUI, ORI, 0x0C, 0x0E, 0x0A, 0x0B, 0x08, 0x18} | LOAD_OPS
SAVED = set(range(16, 24)) | {28, 29, 30}
LIKELY_OPS = {0x14, 0x15, 0x16, 0x17}                     # beql, bnel, blezl, bgtzl


def _is_likely(w):
    op = w >> 26
    return op in LIKELY_OPS or (op == 0x01 and ((w >> 16) & 31) in (0x02, 0x03, 0x12, 0x13))
GP = 28


def _s16(v):
    return v - 0x10000 if v & 0x8000 else v


def _lo_value(op, imm):
    return imm if op == ORI else _s16(imm)


def _dest(w):
    op = w >> 26
    if op in RT_WRITERS:
        return (w >> 16) & 31
    if op in (0x00, 0x1C):                                 # SPECIAL, MMI → rd
        return (w >> 11) & 31
    return None


def find_refs(blob: bytes, text, data, gp, targets, backtrack=0):
    """text = (시작, 끝) 파일 오프셋, data = [(시작, 끝), ...]. 반환: 주소 → [Ref].
    backtrack > 0 이면 직선 추적에 없는 베이스 레지스터를 그 명령 수만큼 거슬러 lui 를 찾는다
    (분기 경로로 들어오는 값). 주소를 만드는 addiu/ori 만 인정하고 loose=True 로 표시한다."""
    out = {}

    def hit(addr, ref):
        if addr in targets:
            out.setdefault(addr, []).append(ref)

    regs = {}
    last_lui = {}                                             # 무효화 없는 최근 lui (되짚기용)
    clear_at = call_at = None
    likely_slot = False                                       # branch-likely 지연 슬롯 = 분기할 때만 실행
    for off in range(text[0], text[1] - 3, 4):
        if clear_at == off:
            regs.clear()
            clear_at = None
        if call_at == off:                                    # 지연 슬롯 다음부터 호출 효과
            regs = {r: v for r, v in regs.items() if r in SAVED}
            call_at = None
        w = struct.unpack_from("<I", blob, off)[0]
        op, rs, rt, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
        if op in USER_OPS:
            if rs in regs:
                hi, lui_off = regs[rs]
                hit((hi + _lo_value(op, imm)) & 0xFFFFFFFF, Ref("hilo", off, lui_off))
            elif rs == GP and gp:
                hit((gp + _s16(imm)) & 0xFFFFFFFF, Ref("gp", off, None))
            elif backtrack and op in ADDR_OPS and rs in last_lui and off - last_lui[rs][1] <= 4 * backtrack:
                hi, lui_off = last_lui[rs]
                hit((hi + _lo_value(op, imm)) & 0xFFFFFFFF, Ref("hilo", off, lui_off, True))
        in_likely, likely_slot = likely_slot, _is_likely(w)
        if op == LUI:
            last_lui[rt] = (imm << 16, off)
            if in_likely:
                regs.pop(rt, None)
            else:
                regs[rt] = last_lui[rt]
            continue
        if op == 0x03 or (op == 0 and (w & 0x3F) == 0x09):   # jal, jalr
            call_at = off + 8
        if op == 0 and (w & 0x3F) == 0x08:                    # jr
            clear_at = off + 8
        d = _dest(w)
        if d is not None and op not in STORE_OPS:
            regs.pop(d, None)
    for a, b in data:
        for off in range(a, b - 3, 4):
            hit(struct.unpack_from("<I", blob, off)[0], Ref("ptr", off, None))
    return out


def _hi_of(addr):
    return ((addr + 0x8000) >> 16) & 0xFFFF


def patch_ref(blob: bytearray, ref: Ref, old: int, new: int, gp: int):
    w = struct.unpack_from("<I", blob, ref.off)[0]
    if ref.kind == "ptr":
        if w != old:
            raise ElfRefError(f"포인터 값 불일치 @{ref.off:#x}")
        struct.pack_into("<I", blob, ref.off, new)
        return
    op, imm = w >> 26, w & 0xFFFF
    if ref.kind == "gp":
        if (gp + _s16(imm)) & 0xFFFFFFFF != old:
            raise ElfRefError(f"gp 참조 불일치 @{ref.off:#x}")
        d = new - gp
        if not -0x8000 <= d < 0x8000:
            raise ElfRefError(f"gp 범위 밖 {new:#x}")
        struct.pack_into("<I", blob, ref.off, (w & 0xFFFF0000) | (d & 0xFFFF))
        return
    hi = (struct.unpack_from("<I", blob, ref.lui_off)[0] & 0xFFFF) << 16
    if (hi + _lo_value(op, imm)) & 0xFFFFFFFF != old:
        raise ElfRefError(f"hi/lo 참조 불일치 @{ref.off:#x}")
    lo = new - hi
    ok = 0 <= lo < 0x10000 if op == ORI else -0x8000 <= lo < 0x8000
    if not ok:
        raise ElfRefError(f"lui 를 바꿔야 하는 이동 {old:#x}→{new:#x} @{ref.off:#x}")
    struct.pack_into("<I", blob, ref.off, (w & 0xFFFF0000) | (lo & 0xFFFF))
