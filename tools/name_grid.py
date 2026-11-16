"""이름 입력 음절표(D9): 히라가나·가타카나 쪽의 열 문자열을 한글 음절로 제자리 교체.

실행 파일 0x2380b0 = 모드별 열 포인터 표(모드 하나 0x50바이트 = 20칸). 모드 0 히라가나,
모드 1 가타카나는 18열 × 5자(열 문자열 = 전각 5자 10바이트 + NUL). 모드 2(영문·숫자)는 그대로 둔다.
음절표 원본: text/name_grid.txt (한 줄 = 화면 한 행 5칸, 쪽마다 왼쪽 묶음 10행 + 오른쪽 묶음 8행).
"""

TABLE = 0x2380B0
PAGE_STRIDE = 0x50
PAGES, COLS, ROWS = 2, 18, 5


class NameGridError(ValueError):
    pass


def load(path):
    return [l.strip() for l in open(path, encoding="utf-8") if l.strip() and not l.startswith("#")]


def apply(elf, delta, cols, encoder):
    """elf(bytearray)를 제자리 수정. delta = 가상 주소 - 파일 오프셋."""
    if len(cols) != PAGES * COLS or any(len(c) != ROWS for c in cols):
        raise NameGridError(f"음절표 모양이 {PAGES * COLS}열 × {ROWS}자가 아님")
    for page in range(PAGES):
        for col in range(COLS):
            p = TABLE + PAGE_STRIDE * page + 4 * col - delta
            va = int.from_bytes(elf[p:p + 4], "little")
            o = va - delta
            if not 0 < o < len(elf) - 2 * ROWS or elf[o + 2 * ROWS] != 0 or 0 in elf[o:o + 2 * ROWS]:
                raise NameGridError(f"쪽 {page} 열 {col}: 원래 10바이트 열 문자열이 아님 ({va:#x})")
            new = encoder(cols[page * COLS + col])
            if len(new) != 2 * ROWS:
                raise NameGridError(f"쪽 {page} 열 {col}: 인코딩 길이 {len(new)}")
            elf[o:o + 2 * ROWS] = new
