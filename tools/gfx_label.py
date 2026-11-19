"""그림 글자 라벨(GTM 시트 위 고정 칸)을 한글로 다시 그린다 (D3, docs/graphics_text.md G4).

게임이 시트의 어느 칸을 잘라 쓰는지는 몰라도, 원래 글자가 차지한 칸(box, 원래 글자의 연결 영역) 안에서만
지우고 그리면 잘라 쓰는 범위와 상관없이 같은 자리에 나온다. 행(text/gfx/*.jsonl):
  {id, src, ko, state, box: [x0, x1, y0, y1], align: L|R|C, style: gold|badge, body?: [y0, y1], colors?}
  gold  = 원래 라벨의 줄별 밝은 색 × 글자 덮임 → 그 칸이 원래 쓰던 팔레트 인덱스 중 가장 가까운 것(팔레트 그대로).
  badge = 지정 인덱스: 위·아래 채움(top/bottom), 오른쪽 아래 그림자(shadow), 바깥 테두리(edge), 나머지 0.
  body  = 새 글자를 그릴 줄 범위(기본 = 원래 글자 위아래). 아래 칸이 잘라 쓰는 줄에 닿지 않게 줄일 때.
  align = 메뉴 목록은 L(왼쪽 끝 유지), 쌍점 앞 능력치 이름은 R, 한 글자 속성은 C.
글꼴은 D10 과 같은 Noto Sans CJK KR(라벨 Black, 작은 배지 Bold).
"""
import hashlib
import os

from tools.hangul import is_hangul

FONTS = {"gold": ("/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc", 1),
         "badge": ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 1)}
FONT_SHA1 = {"gold": "aae77a58b5d711e051a73facd39a41775f41ef40",      # 다른 판이면 결과가 달라지므로 빌드 실패
             "badge": "43f0027121b407326b3f06d0466df83887879e1b"}
SS = 4                 # 안티에일리어싱용 확대 배율
GOLD_MIN, GOLD_GAIN, BRIGHT = 0.25, 1.15, 120
MIN_HEIGHT = 0.7       # 폭에 맞추느라 글자 높이가 원래의 70% 밑으로 줄면 실패(읽을 수 없음)
BADGE_MIN = 150
STATES_SKIP = {"untranslated"}
COLOR_KEYS = {"top", "bottom", "shadow", "edge"}


class GfxLabelError(ValueError):
    pass


def check_fonts():
    for k, (path, _) in FONTS.items():
        if not os.path.exists(path):
            raise GfxLabelError(f"글꼴 없음 {path}")
        with open(path, "rb") as f:
            got = hashlib.sha1(f.read()).hexdigest()
        if got != FONT_SHA1[k]:
            raise GfxLabelError(f"글꼴 {path} SHA1 {got} != {FONT_SHA1[k]}")


def _ints(v, n):
    return isinstance(v, list) and len(v) == n and all(type(x) is int for x in v)


def check_rows(rows, width, height):
    seen, boxes = set(), []
    for r in rows:
        rid = r.get("id")
        if rid in seen:
            raise GfxLabelError(f"{rid}: 중복")
        seen.add(rid)
        if not _ints(r.get("box"), 4) or ("body" in r and not _ints(r["body"], 2)):
            raise GfxLabelError(f"{rid}: box 는 정수 4개, body 는 정수 2개")
        if r.get("state") is None:
            raise GfxLabelError(f"{rid}: 상태 없음")
        x0, x1, y0, y1 = r["box"]
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise GfxLabelError(f"{rid}: 칸 {r['box']}")
        b0, b1 = r.get("body", [y0, y1])
        if not y0 <= b0 < b1 <= y1:
            raise GfxLabelError(f"{rid}: body {r.get('body')} 가 칸 밖")
        if r.get("align") not in ("L", "R", "C"):
            raise GfxLabelError(f"{rid}: align {r.get('align')}")
        if r.get("style") not in ("gold", "badge"):
            raise GfxLabelError(f"{rid}: style {r.get('style')}")
        if r["style"] == "badge" and (set(r.get("colors", {})) != COLOR_KEYS or
                                      not all(type(v) is int and 0 <= v < 256 for v in r["colors"].values())):
            raise GfxLabelError(f"{rid}: badge 색 {sorted(COLOR_KEYS)} 필요(0..255)")
        if r.get("state") not in STATES_SKIP:
            ko = r.get("ko", "")
            if not ko.strip() or any(not (is_hangul(c) or c == " ") for c in ko):
                raise GfxLabelError(f"{rid}: 한글·공백만 그릴 수 있음 {ko!r}")
        for o in boxes:
            if x0 < o[1] and o[0] < x1 and y0 < o[3] and o[2] < y1:
                raise GfxLabelError(f"{rid}: 다른 칸 {o} 과 겹침")
        boxes.append((x0, x1, y0, y1))


def _mask(text, w, h, align, font, min_alpha):
    """높이 h·폭 w 에 맞춘 글자 덮임(0..1) 행렬."""
    from PIL import Image, ImageDraw, ImageFont
    size = h * SS * 2
    while True:
        f = ImageFont.truetype(font[0], size, index=font[1])
        l, t, r, b = f.getbbox(text)
        if b - t <= h * SS and r - l <= w * SS:
            if b - t < MIN_HEIGHT * h * SS:
                raise GfxLabelError(f"{text!r} 가 {w}×{h} 칸에 들어가려면 너무 작아짐")
            break
        if size <= SS:
            raise GfxLabelError(f"{text!r} 가 {w}×{h} 칸에 안 들어감")
        size -= 1
    im = Image.new("L", (w * SS, h * SS), 0)
    room = w * SS - (r - l)
    left = {"L": 0, "R": room, "C": room // 2}[align]
    ImageDraw.Draw(im).text((left - l, (h * SS - (b - t)) // 2 - t), text, font=f, fill=255)
    im = im.resize((w, h), Image.BOX)
    return [[im.getpixel((x, y)) / 255 if im.getpixel((x, y)) >= min_alpha * 255 else 0
             for x in range(w)] for y in range(h)]


def _lum(c):
    return 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]


def _gold(g, r, pal):
    W = g.width
    x0, x1, y0, y1 = r["box"]
    px = lambda x, y: g.pixels[y * W + x]
    rows = [y for y in range(y0, y1) if any(px(x, y) for x in range(x0, x1))]
    if not rows:
        raise GfxLabelError(f"{r['id']}: 칸에 원래 글자 없음")
    b0, b1 = r.get("body", [rows[0], rows[-1] + 1])
    cand = sorted({px(x, y) for y in range(y0, y1) for x in range(x0, x1)} - {0})
    bright, last = {}, None
    for y in list(range(b0, b1)) + list(reversed(range(b0, b1))):   # 빈 줄은 이웃 줄 색
        cs = [pal[px(x, y)] for x in range(x0, x1) if px(x, y) and _lum(pal[px(x, y)]) > BRIGHT]
        bright[y] = bright.get(y) or (tuple(sum(c[i] for c in cs) / len(cs) for i in range(3)) if cs else last)
        last = bright[y]
    if any(v is None for v in bright.values()):
        raise GfxLabelError(f"{r['id']}: 원래 글자에 밝은 색이 없어 색을 정할 수 없음")
    m = _mask(r["ko"], x1 - x0, b1 - b0, r["align"], FONTS["gold"], GOLD_MIN)
    _clear(g, r["box"])
    for yy, line in enumerate(m):
        for xx, a in enumerate(line):
            if a:
                t = [c * min(1, a * GOLD_GAIN) for c in bright[b0 + yy]]
                g.pixels[(b0 + yy) * W + x0 + xx] = min(cand, key=lambda i: sum((pal[i][k] - t[k]) ** 2 for k in range(3)))


def _badge(g, r):
    W = g.width
    x0, x1, y0, y1 = r["box"]
    c = r["colors"]
    _clear(g, r["box"])
    m = _mask(r["ko"], x1 - x0 - 2, y1 - y0 - 3, r["align"], FONTS["badge"], BADGE_MIN / 255)
    fill = {(x0 + 1 + x, y0 + 1 + y) for y, line in enumerate(m) for x, a in enumerate(line) if a}
    shadow = {(x + 1, y + 1) for x, y in fill} - fill
    edge = {(x + dx, y + dy) for x, y in fill | shadow for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - fill - shadow
    mid = y0 + (y1 - y0) // 2
    for pts, idx in ((edge, lambda y: c["edge"]), (shadow, lambda y: c["shadow"]),
                     (fill, lambda y: c["top"] if y < mid else c["bottom"])):
        for x, y in pts:
            if x0 <= x < x1 and y0 <= y < y1:
                g.pixels[y * W + x] = idx(y)


def _clear(g, box):
    x0, x1, y0, y1 = box
    for y in range(y0, y1):
        g.pixels[y * g.width + x0:y * g.width + x1] = bytes(x1 - x0)


def apply_labels(g, rows):
    """g(Gtm) 제자리 수정. untranslated 행은 건드리지 않는다."""
    check_rows(rows, g.width, g.height)
    check_fonts()
    pal = g.palette()
    for r in rows:
        if r["state"] in STATES_SKIP:
            continue
        if r["style"] == "gold":
            _gold(g, r, pal)
        else:
            _badge(g, r)
