"""퀘스트 제목 카드(TITLE/TITLE00–34.PSI, 512×128 8bpp, SL00) 한글화 (D3, docs/graphics_text.md G2).

카드 = 왼쪽 장식 + 제목 글자 + 오른쪽 장식. 가운데 줄에서 맨 왼쪽·맨 오른쪽 열 덩어리가 장식이고,
그 열에 닿는 2D 연결 영역(위아래로 뻗은 덩굴 포함)이 장식 픽셀이다. 나머지가 글자.
새 글자는 원래 글자 가운데에 놓고, 장식은 원래 글자와의 틈을 그대로 두고 옮긴다.
색: 원래 글자 줄별 밝은 불투명 색 × 덮임(알파) → 원래 글자가 쓰던 인덱스 중 RGBA 가장 가까운 것(팔레트 그대로).
글꼴: Noto Serif CJK KR Medium, 기울임(원본 글자처럼). 큰 카드·작은 카드 모두(원본 글자 높이 34–45px).
"""
import hashlib
import os

from tools.hangul import is_hangul
from tools.psi import Psi

CARD_FONTS = {"medium": ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Medium.ttc", 1)}
CARD_SHA1 = {"medium": "a594de91ea8b5e42645c16297bdc70856e925d56"}
NO_RECORD = {"TITLE#34"}   # 퀘스트 기록(RECORD.DAT)에 없는 카드
STATES = {"reviewed", "untranslated"}
SS, SHEAR = 4, 0.2
MIN_ALPHA, GAIN, BRIGHT_SUM = 0.08, 1.1, 300
BAND = 8              # 가운데 줄 ±BAND 행으로 장식 열을 찾음
ORN_MIN, ORN_DIFF = 20, 4   # 장식 열 덩어리: 양쪽 모두 20px 이상, 폭 차이 4px 이하(원본 모두 약 43px)


class GfxCardError(ValueError):
    pass


def check_fonts():
    for k, (path, _) in CARD_FONTS.items():
        if not os.path.exists(path):
            raise GfxCardError(f"글꼴 없음 {path}")
        with open(path, "rb") as f:
            if hashlib.sha1(f.read()).hexdigest() != CARD_SHA1[k]:
                raise GfxCardError(f"글꼴 {path} SHA1 이 기록과 다름")


def _segments(cols, gap=2):
    out, st, k, last = [], None, 0, 0
    for i, v in enumerate(cols + [False] * (gap + 1)):
        if v:
            st = i if st is None else st
            k, last = 0, i
        elif st is not None:
            k += 1
            if k >= gap:
                out.append((st, last + 1))
                st = None
    return out


def _components(ink, w, h):
    seen, out = set(), []
    for i in ink:
        if i in seen:
            continue
        seen.add(i)
        st, cur = [i], [i]
        while st:
            j = st.pop()
            x, y = j % w, j // w
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    k = (y + dy) * w + x + dx
                    if 0 <= x + dx < w and 0 <= y + dy < h and k in ink and k not in seen:
                        seen.add(k)
                        st.append(k)
                        cur.append(k)
        out.append(cur)
    return out


def _split(p, pal):
    w, h = p.width, p.height
    ink = {i for i, v in enumerate(p.pixels) if pal[v][3]}
    if not ink:
        raise GfxCardError("빈 카드")
    ys = sorted({i // w for i in ink})
    mid = (ys[0] + ys[-1]) // 2
    seg = _segments([any((y * w + x) in ink for y in range(mid - BAND, mid + BAND + 1)) for x in range(w)])
    if len(seg) < 3:
        raise GfxCardError("장식 두 개와 글자를 나눌 수 없음")
    (l0, l1), (r0, r1) = seg[0], seg[-1]
    if min(l1 - l0, r1 - r0) < ORN_MIN or abs((l1 - l0) - (r1 - r0)) > ORN_DIFF:
        raise GfxCardError(f"양 끝 장식을 찾지 못함 {seg[0]} {seg[-1]}")
    left, right, text = set(), set(), set()
    for c in _components(ink, w, h):
        xs = {j % w for j in c}
        if any(l0 <= x < l1 for x in xs):
            left |= set(c)
        elif any(r0 <= x < r1 for x in xs):
            right |= set(c)
        else:
            text |= set(c)
    if not text:
        raise GfxCardError("글자 픽셀 없음")
    return left, right, text


def _mask(ko, h):
    from PIL import Image, ImageDraw, ImageFont
    font = CARD_FONTS["medium"]
    size = h * SS * 2
    while True:
        f = ImageFont.truetype(font[0], size, index=font[1])
        l, t, r, b = f.getbbox(ko)
        if b - t <= h * SS or size <= SS:
            break
        size -= 2
    wpx = (r - l) + int(SHEAR * h * SS) + 2 * SS
    im = Image.new("L", (wpx, h * SS))
    ImageDraw.Draw(im).text((SS - l, (h * SS - (b - t)) // 2 - t), ko, font=f, fill=255)
    im = im.transform(im.size, Image.AFFINE, (1, SHEAR, -SHEAR * h * SS, 0, 1, 0), Image.BICUBIC)
    im = im.resize((wpx // SS, h), Image.BOX)
    m = [[im.getpixel((x, y)) / 255 for x in range(im.width)] for y in range(h)]
    used = [x for x in range(im.width) if any(m[y][x] >= MIN_ALPHA for y in range(h))]
    m = [line[used[0]:used[-1] + 1] for line in m]          # 실제 획이 있는 열만(장식과의 틈을 원래대로)
    return len(m[0]), m


def compose(p, ko):
    """새 Psi(같은 헤더·팔레트). 0 = 투명 배경으로 다시 깐다."""
    if not ko.strip() or any(not (is_hangul(c) or c == " ") for c in ko):
        raise GfxCardError(f"한글·공백만 그릴 수 있음 {ko!r}")
    if p.bpp != 8:
        raise GfxCardError("8bpp 카드만 다룸")
    pal = p.palette()
    if pal[0][3]:
        raise GfxCardError("인덱스 0 이 투명이 아님")
    W = p.width
    left, right, text = _split(p, pal)
    tx0, tx1 = min(j % W for j in text), max(j % W for j in text) + 1
    ty0, ty1 = min(j // W for j in text), max(j // W for j in text) + 1
    h = ty1 - ty0
    cand = sorted({p.pixels[j] for j in text})
    bright, last = {}, None
    for y in list(range(ty0, ty1)) + list(reversed(range(ty0, ty1))):
        cs = [pal[p.pixels[j]] for j in text if j // W == y and pal[p.pixels[j]][3] == 255
              and sum(pal[p.pixels[j]][:3]) > BRIGHT_SUM]
        bright[y] = bright.get(y) or (tuple(sum(c[i] for c in cs) / len(cs) for i in range(3)) if cs else last)
        last = bright[y]
    if any(v is None for v in bright.values()):
        raise GfxCardError("글자 색을 정할 밝은 픽셀이 없음")
    w, m = _mask(ko, h)
    nx0 = int(round((tx0 + tx1) / 2 - w / 2))
    nx1 = nx0 + w
    new = bytearray(len(p.pixels))
    placed = []
    for pts, dx in ((left, nx0 - tx0), (right, nx1 - tx1)):
        for j in pts:
            x = j % W + dx
            if not 0 <= x < W:
                raise GfxCardError(f"{ko!r}: 장식이 카드 밖으로 나감")
            new[j + dx] = p.pixels[j]
        placed.append({j + dx for j in pts})
    if nx0 < 0 or nx1 > W:
        raise GfxCardError(f"{ko!r}: 글자가 카드 밖으로 나감")
    tpos = {(ty0 + yy) * W + nx0 + xx for yy, line in enumerate(m) for xx, a in enumerate(line) if a >= MIN_ALPHA}
    if placed[0] & placed[1] or (placed[0] | placed[1]) & tpos:
        raise GfxCardError(f"{ko!r}: 글자와 장식이 겹침")
    for yy, line in enumerate(m):
        for xx, a in enumerate(line):
            if a < MIN_ALPHA:
                continue
            t = list(bright[ty0 + yy]) + [255 * min(1, a * GAIN)]
            new[(ty0 + yy) * W + nx0 + xx] = min(cand, key=lambda i: sum((pal[i][k] - t[k]) ** 2 for k in range(4)))
    return Psi(p.header, p.width, p.height, 8, p.clut, bytes(new))


def check_titles(rows, data_rows):
    """카드 글은 검수된 퀘스트 제목(RECORD#nnn.title)과 같아야 한다. id·path 짝, 상태도 확인."""
    data = {r["id"]: r for r in data_rows}
    ids, paths = set(), set()
    for r in rows:
        rid, path = r["id"], r.get("path")
        num = rid.partition("#")[2]
        if rid in ids or path in paths:
            raise GfxCardError(f"{rid}: id 또는 path 중복")
        ids.add(rid)
        paths.add(path)
        if path != f"/DATAIMG/TITLE/TITLE{num}.PSI":
            raise GfxCardError(f"{rid}: path {path} 가 id 와 맞지 않음")
        if r.get("state") not in STATES:
            raise GfxCardError(f"{rid}: 상태 {r.get('state')}")
        if r["state"] == "untranslated":
            if r.get("ko"):
                raise GfxCardError(f"{rid}: untranslated 인데 번역이 있음")
            continue
        rec = r.get("record")
        if rec is None:
            if rid not in NO_RECORD or "record" not in r:
                raise GfxCardError(f"{rid}: record 없음")
            continue
        d = data.get(rec)
        if d is None or d.get("state") != "reviewed" or d["src"] != r["src"] or d.get("ko") != r["ko"]:
            raise GfxCardError(f"{rid}: 검수된 {rec} 의 원문·번역과 다름")
