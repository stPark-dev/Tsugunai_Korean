"""게임 텍스트 바이트 ↔ 토큰 문자열.

제어 코드(관찰: SCP op 0x14/0x38/0x39/0x3B)
  01 xx  글자색 (08 = 기본색)       → {c:xx}
  02 xx  이름 변수 (01 = 주인공 등)  → {n:xx}
  0a     줄바꿈(실행 파일 디버그 문자열)  → "\n" 그대로
원문에 '{' '}' 는 나오지 않으므로 토큰 구분자로 쓴다.
"""
import re

CTRL = {1: "c", 2: "n"}
TOKEN_RE = re.compile(r"\{([a-z]):([0-9a-f]{2})\}")


class TextCodecError(ValueError):
    pass


def decode_sjis(b: bytes) -> str:
    out = []
    i = 0
    while i < len(b):
        c = b[i]
        if c < 0x20 and c != 0x0A:                 # 0x0A(실행 파일 문자열의 줄바꿈)는 그대로
            if c not in CTRL or i + 1 >= len(b):
                raise TextCodecError(f"알 수 없는 제어 바이트 {b[i:i+2].hex()} @{i}")
            out.append(f"{{{CTRL[c]}:{b[i + 1]:02x}}}")
            i += 2
            continue
        n = 1 if c < 0x80 or 0xA0 <= c < 0xE0 else 2
        ch = b[i:i + n].decode("cp932")
        if ch in "{}":
            raise TextCodecError("원문에 중괄호")
        out.append(ch)
        i += n
    return "".join(out)


def split_tokens(s: str):
    """문자열을 (토큰종류|None, 값) 조각으로."""
    pos = 0
    for m in TOKEN_RE.finditer(s):
        if m.start() > pos:
            yield None, s[pos:m.start()]
        yield m.group(1), int(m.group(2), 16)
        pos = m.end()
    if pos < len(s):
        yield None, s[pos:]


def encode_sjis(s: str) -> bytes:
    rev = {v: k for k, v in CTRL.items()}
    out = bytearray()
    for kind, val in split_tokens(s):
        if kind is None:
            if "{" in val or "}" in val:
                raise TextCodecError(f"잘못된 토큰: {val!r}")
            out += val.encode("cp932")
        elif kind in rev:
            out += bytes([rev[kind], val])
        else:
            raise TextCodecError(f"알 수 없는 토큰 종류 {kind}")
    return bytes(out)
