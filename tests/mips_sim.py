"""테스트용 작은 MIPS(R5900 일부) 해석기. 대사 펼치기 함수 같은 잎 함수만 돌린다.

32비트 레지스터, 지연 슬롯·branch-likely, EE 3피연산자 mult(rd = rs*rt 하위 32비트).
모르는 명령이면 멈추고 예외를 낸다(조용히 넘어가지 않음).
"""
import struct

RA_STOP = 0x0BAD0000


class SimError(RuntimeError):
    pass


def _s16(v):
    return v - 0x10000 if v & 0x8000 else v


class Sim:
    def __init__(self, size=0x2000000):
        self.mem = bytearray(size)
        self.r = [0] * 32

    def load(self, va, data):
        self.mem[va:va + len(data)] = data

    def w32(self, va, v):
        struct.pack_into("<I", self.mem, va, v & 0xFFFFFFFF)

    def r32(self, va):
        return struct.unpack_from("<I", self.mem, va)[0]

    def r16(self, va):
        return struct.unpack_from("<H", self.mem, va)[0]

    def call(self, pc, args, gp, limit=100000):
        r = self.r
        r[:] = [0] * 32
        r[28], r[29], r[31] = gp, 0x1F00000, RA_STOP
        for i, a in enumerate(args):
            r[4 + i] = a & 0xFFFFFFFF
        branch = None
        for _ in range(limit):
            if pc == RA_STOP:
                return
            w = self.r32(pc)
            nxt, skip = self._exec(w, pc)
            if branch is not None:
                pc, branch = branch, None
                if nxt is not None:
                    raise SimError("지연 슬롯 안 분기")
                continue
            if skip:                       # branch-likely 불성립 → 지연 슬롯 건너뜀
                pc += 8
                continue
            if nxt is not None:
                branch = nxt
            pc += 4
            r[0] = 0
        raise SimError("명령 수 한도 초과")

    def _exec(self, w, pc):
        r, m = self.r, self.mem
        op, rs, rt, rd = w >> 26, (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31
        imm, sa, fn = w & 0xFFFF, (w >> 6) & 31, w & 0x3F
        M = 0xFFFFFFFF
        ea = (r[rs] + _s16(imm)) & M

        def setr(i, v):
            if i:
                r[i] = v & M
        if w == 0:
            return None, False
        if op == 0:
            if fn == 0x00:
                setr(rd, r[rt] << sa)
            elif fn == 0x02:
                setr(rd, r[rt] >> sa)
            elif fn == 0x03:
                setr(rd, (r[rt] - (1 << 32) if r[rt] >> 31 else r[rt]) >> sa)
            elif fn == 0x08:
                return r[rs], False
            elif fn in (0x21, 0x2D):                 # addu, daddu(move)
                setr(rd, r[rs] + r[rt])
            elif fn == 0x23:
                setr(rd, r[rs] - r[rt])
            elif fn == 0x24:
                setr(rd, r[rs] & r[rt])
            elif fn == 0x25:
                setr(rd, r[rs] | r[rt])
            elif fn == 0x2A:
                sv = lambda x: x - (1 << 32) if x >> 31 else x
                setr(rd, int(sv(r[rs]) < sv(r[rt])))
            elif fn == 0x2B:
                setr(rd, int(r[rs] < r[rt]))
            elif fn == 0x18:
                sv = lambda x: x - (1 << 32) if x >> 31 else x
                setr(rd, sv(r[rs]) * sv(r[rt]))
            else:
                raise SimError(f"모르는 SPECIAL {w:#010x} @{pc:#x}")
            return None, False
        if op == 0x1C and fn == 0x18:                # mult1 rd
            sv = lambda x: x - (1 << 32) if x >> 31 else x
            setr(rd, sv(r[rs]) * sv(r[rt]))
            return None, False
        tgt = (pc + 4 + (_s16(imm) << 2)) & M
        if op == 0x02:
            return ((pc + 4) & 0xF0000000) | ((w & 0x3FFFFFF) << 2), False
        if op in (0x04, 0x05, 0x14, 0x15):
            take = (r[rs] == r[rt]) == (op in (0x04, 0x14))
            likely = op in (0x14, 0x15)
            return (tgt if take else None), (likely and not take)
        if op == 0x09:
            setr(rt, r[rs] + _s16(imm))
        elif op == 0x0B:
            setr(rt, int(r[rs] < (_s16(imm) & M)))
        elif op == 0x0D:
            setr(rt, r[rs] | imm)
        elif op == 0x0F:
            setr(rt, imm << 16)
        elif op == 0x20:
            v = m[ea]
            setr(rt, v - 0x100 if v & 0x80 else v)
        elif op == 0x21:
            setr(rt, _s16(self.r16(ea)))
        elif op == 0x23:
            setr(rt, self.r32(ea))
        elif op == 0x24:
            setr(rt, m[ea])
        elif op == 0x25:
            setr(rt, self.r16(ea))
        elif op == 0x29:
            struct.pack_into("<H", m, ea, r[rt] & 0xFFFF)
        elif op == 0x2B:
            self.w32(ea, r[rt])
        else:
            raise SimError(f"모르는 명령 {w:#010x} @{pc:#x}")
        return None, False
