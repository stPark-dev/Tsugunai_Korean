"""전투 명령 창 글자 가운데 맞춤.

메뉴 문자열 그리기(0x1d5e10 → 0x1a1540)는 글자마다 x 를 24 씩 늘린다(1바이트·2바이트·공백 모두).
원본은 명령마다 x 를 따로 줘서 보이는 글자의 가운데를 맞춘다(앞 전각 공백은 자리 띄우기):
x + 24 × 앞 공백 수 + 12 × 보이는 글자 수 = 전투 명령 96, 소환 하위 명령 98
(たたかう 48, 　まほう 36, しょうかん 36, アイテム 48, ストレージ 36 / よびだす 50, もどす 62, いれかえ 50).
번역 글자 수가 달라지면 그 가운데를 지키도록 `addiu a1, zero, x` 의 x 만 바꾼다.
"""
import struct

ADDIU_A1_ZERO = 0x24050000
ADVANCE = 24
SPACE = "　"

# (메뉴, x 를 주는 명령 VA, 원래 x, 문자열 ID)
CENTERED = (
    ("battle", 0x1D7AA8, 36, "ELF#2565b0"),   # ストレージ
    ("battle", 0x1D7AD0, 48, "ELF#2565c0"),   # たたかう
    ("battle", 0x1D7B84, 36, "ELF#2565d0"),   # 　まほう
    ("battle", 0x1D7BB4, 36, "ELF#2565e0"),   # しょうかん
    ("battle", 0x1D7BE4, 48, "ELF#2565f0"),   # アイテム
    ("summon", 0x1D8AE4, 50, "ELF#256608"),   # よびだす
    ("summon", 0x1D8B14, 62, "ELF#25d6a0"),   # もどす
    ("summon", 0x1D8B74, 50, "ELF#256618"),   # いれかえ
)


class UiLayoutError(ValueError):
    pass


def _shift(s):
    """그리기 시작점에서 보이는 글자 가운데까지 거리."""
    shown = s.lstrip(SPACE)
    if not shown or shown != shown.strip():
        raise UiLayoutError(f"앞 전각 공백 말고는 공백 금지(그려지지 않아 가운데가 어긋남): {s!r}")
    return ADVANCE * (len(s) - len(shown)) + ADVANCE // 2 * len(shown)


def apply(elf, delta, src, texts, table=CENTERED):
    """elf(bytearray) 제자리 수정. src = ID → 원문, texts = ID → 번역(없으면 원문 그대로)."""
    for _menu, va, x0, rid in table:
        off = va - delta
        w, = struct.unpack_from("<I", elf, off)
        if w != ADDIU_A1_ZERO | x0:
            raise UiLayoutError(f"{va:#x}: addiu a1, zero, {x0} 이 아님({w:08x})")
        if rid not in src:
            raise UiLayoutError(f"원문 없음 {rid}")
        x = x0 + _shift(src[rid]) - _shift(texts.get(rid, src[rid]))
        if not 0 <= x < 0x8000:
            raise UiLayoutError(f"{rid}: x {x} 범위 밖")
        struct.pack_into("<I", elf, off, ADDIU_A1_ZERO | x)
