"""SCP(맵 이벤트 스크립트) 파서/직렬화기.

구조 (조사: docs/survey.md, 검증: tests/test_scp.py)
  +0x00 u32×8  구역 진입 오프셋(0=없음)
  +0x20~EOF    레코드 열. 레코드 = u16 op, u16 len(헤더 포함), 4바이트 정렬
               FFFF FFFF = 구분자
               op & 0x8000 = 컨테이너, 자식이 +4부터. 실제 크기가 64KB를 넘으면
               len 필드는 하위 16비트만 남는다(M21_00, M24_01 원본).
  op 0x01      +4 u32 = 파일 내 절대 오프셋(레코드·구분자 시작 또는 EOF)
  텍스트 op    본문 = Shift-JIS 문자열 + NUL 1~4개(4바이트 정렬)
"""
import struct

TEXT_OPS = frozenset({0x14, 0x38, 0x39, 0x3B})  # 장소명, 화자, 대사, 선택지
JUMP_OP = 0x01
SEP = b"\xff\xff\xff\xff"


class ScpError(ValueError):
    pass


class Node:
    pos = None


class Sep(Node):
    op = None

    def size(self):
        return 4


class Rec(Node):
    def __init__(self, op, payload):
        self.op, self.payload = op, payload

    def size(self):
        return 4 + len(self.payload)

    @property
    def text(self):
        return self.payload.split(b"\0", 1)[0]

    def set_text(self, b: bytes):
        if b"\0" in b:
            raise ScpError("텍스트에 NUL 불가")
        self.payload = b + b"\0" * (4 - len(b) % 4)


class Jump(Rec):
    target = None       # 파싱 시 원래 오프셋
    target_node = None  # Node 또는 EOF

    def target_node_desc(self):
        t = self.target_node
        return "EOF" if t is EOF else (type(t).__name__, t.op, t.index)


class Cont(Node):
    def __init__(self, op, children):
        self.op, self.children = op, children

    def size(self):
        return 4 + sum(c.size() for c in self.children)


EOF = object()


def _parse_seq(d, p, end):
    out = []
    while p < end:
        if p + 4 > end:
            raise ScpError(f"레코드 헤더 잘림 @{p:#x}")
        if d[p:p + 4] == SEP:
            n = Sep()
            n.pos = p
            out.append(n)
            p += 4
            continue
        op, ln = struct.unpack_from("<HH", d, p)
        if ln < 4 or ln % 4:
            raise ScpError(f"잘못된 길이 {ln:#x} @{p:#x}")
        if op & 0x8000:
            last = None
            for k in range(4):
                real = ln + k * 0x10000
                if p + real > end:
                    break
                try:
                    kids = _parse_seq(d, p + 4, p + real)
                except ScpError as e:
                    last = e
                    continue
                n = Cont(op, kids)
                break
            else:
                raise last or ScpError(f"컨테이너 범위 초과 @{p:#x}")
            if p + real > end:
                raise last or ScpError(f"컨테이너 범위 초과 @{p:#x}")
        else:
            real = ln
            if p + real > end:
                raise ScpError(f"레코드 범위 초과 @{p:#x}")
            payload = d[p + 4:p + ln]
            n = (Jump if op == JUMP_OP else Rec)(op, payload)
            if op == JUMP_OP:
                if ln != 8:
                    raise ScpError(f"점프 길이 {ln} @{p:#x}")
                n.target = struct.unpack_from("<I", payload)[0]
        n.pos = p
        out.append(n)
        p += real
    return out


class Script:
    def __init__(self, header, nodes, header_nodes):
        self.header = header
        self.nodes = nodes
        self.header_nodes = header_nodes

    def walk(self, nodes=None):
        for n in self.nodes if nodes is None else nodes:
            yield n
            if isinstance(n, Cont):
                yield from self.walk(n.children)

    @classmethod
    def parse(cls, raw: bytes):
        header = list(struct.unpack_from("<8I", raw, 0))
        nodes = _parse_seq(raw, 0x20, len(raw))
        s = cls(header, nodes, None)
        at = {}
        for i, n in enumerate(s.walk()):
            n.index = i
            at.setdefault(n.pos, n)
        at[len(raw)] = EOF

        def resolve(off, what):
            if off not in at:
                raise ScpError(f"{what}: 오프셋 {off:#x}가 노드 시작이 아님")
            return at[off]

        for n in s.walk():
            if isinstance(n, Jump):
                n.target_node = resolve(n.target, f"점프 @{n.pos:#x}")
        s.header_nodes = [resolve(h, "헤더") if h else None for h in header]
        return s

    def texts(self):
        return [n for n in self.walk() if isinstance(n, Rec) and n.op in TEXT_OPS]

    def jumps(self):
        return [n for n in self.walk() if isinstance(n, Jump)]

    def containers(self):
        return [n for n in self.walk() if isinstance(n, Cont)]

    def _layout(self, nodes, p):
        for n in nodes:
            n.pos = p
            if isinstance(n, Cont):
                self._layout(n.children, p + 4)
            p += n.size()
        return p

    def to_bytes(self) -> bytes:
        total = self._layout(self.nodes, 0x20)

        def off(n):
            return total if n is EOF else n.pos

        out = bytearray(struct.pack("<8I", *[off(n) if n is not None else 0 for n in self.header_nodes]))

        def emit(nodes):
            for n in nodes:
                if isinstance(n, Sep):
                    out.extend(SEP)
                elif isinstance(n, Cont):
                    out.extend(struct.pack("<HH", n.op, n.size() & 0xFFFF))
                    emit(n.children)
                elif isinstance(n, Jump):
                    n.target = off(n.target_node)
                    out.extend(struct.pack("<HHI", n.op, 8, n.target))
                else:
                    if n.size() > 0xFFFF:
                        raise ScpError("레코드 64KB 초과")
                    out.extend(struct.pack("<HH", n.op, n.size()) + n.payload)

        emit(self.nodes)
        assert len(out) == total
        return bytes(out)

