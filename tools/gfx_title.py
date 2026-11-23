"""타이틀 화면 로고 「つぐない」→「츠구나이」 (D3, docs/graphics_text.md G1, D11).

타이틀 화면 = TITLE/TITLEA–F.PSI(32bpp) 6조각, 640×512(보이는 640×448 + 아래 64줄 검정).
사용자가 원본 화면을 바탕으로 만든 그림(assets/title_ko.png, 커밋 안 함, SHA1 확인)을
원본에 맞춰 정렬(ORB 특징점 + RANSAC 어파인)한 뒤, 로고 상자 안에서 원본과 크게 다른 픽셀만
경계를 부드럽게 해서 가져온다. 상자 밖·아래 64줄·알파(메뉴 자리 투명 줄)는 원본 그대로.
"""
import hashlib
import io
import os

import numpy as np

from tools.psi import Psi

TITLE_SHA1 = "91cd9c0dae5c3eaa62321adcd4c21a48dc590266"
TITLE_OUT_SHA1 = "38da27104728e49699324dae3638a1894f4622a0"             # TITLEA–F 출력 바이트(경로순 이어 붙임) SHA1. OpenCV 4.11.0 기준, docs/build.md
PIECES = {"A": (0, 0, 256, 256), "B": (256, 0, 256, 256), "C": (512, 0, 128, 256),
          "D": (0, 256, 256, 256), "E": (256, 256, 256, 256), "F": (512, 256, 128, 256)}
W, H, VIS_H = 640, 512, 448
BOX = (370, 50, 640, 370)          # x0, y0, x1, y1: 세로 붓글씨 로고(「つぐない」) 영역
DIFF, CLOSE, GROW, FEATHER = 90, 5, 7, 9
INSET = GROW // 2 + FEATHER // 2 + 1   # 상자 안쪽 이만큼에서만 차이를 찾음 → 경계에서 합성 비율 0(이음새 없음)
MIN_INLIERS, MAX_SHIFT = 200, 3.0     # 정렬 변환으로 화면 네 모서리가 움직이는 최대 거리(px)


class GfxTitleError(ValueError):
    pass


def join(psis):
    """조각 Psi 6개 → 640×512 RGBA(PS2 알파 값 그대로) 배열."""
    out = np.zeros((H, W, 4), np.uint8)
    for k, (x, y, w, h) in PIECES.items():
        p = psis[k]
        if p.bpp != 32 or (p.width, p.height) != (w, h):
            raise GfxTitleError(f"TITLE{k}: 32bpp {w}×{h} 가 아님")
        out[y:y + h, x:x + w] = np.frombuffer(p.pixels, np.uint8).reshape(h, w, 4)
    return out


def split(rgba, psis):
    """join 의 역. 헤더는 원래 조각 것을 쓴다."""
    out = {}
    for k, (x, y, w, h) in PIECES.items():
        out[k] = Psi(psis[k].header, w, h, 32, None, np.ascontiguousarray(rgba[y:y + h, x:x + w]).tobytes())
    return out


def register(orig_rgb, new_rgb):
    """새 그림을 원본(보이는 640×448) 좌표로 옮긴 RGB. 정렬이 안 되면 실패."""
    import cv2
    h, w = orig_rgb.shape[:2]
    scale = w / new_rgb.shape[1]
    small = cv2.resize(new_rgb, (w, round(new_rgb.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    orb = cv2.ORB_create(5000)
    k1, d1 = orb.detectAndCompute(cv2.cvtColor(orig_rgb, cv2.COLOR_RGB2GRAY), None)
    k2, d2 = orb.detectAndCompute(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), None)
    if d1 is None or d2 is None:
        raise GfxTitleError("특징점을 찾지 못함")
    m = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d2, d1)
    if len(m) < MIN_INLIERS:
        raise GfxTitleError(f"맞는 특징점이 적음 {len(m)}")
    src = np.float32([k2[x.queryIdx].pt for x in m])
    dst = np.float32([k1[x.trainIdx].pt for x in m])
    a, inl = cv2.estimateAffine2D(src, dst, ransacReprojThreshold=2.0)
    if a is None or int(inl.sum()) < MIN_INLIERS:
        raise GfxTitleError("원본과 정렬되지 않음")
    pts = np.float32([[0, 0, 1], [w, 0, 1], [0, h, 1], [w, h, 1]])
    disp = float(np.abs(pts @ a.T - pts[:, :2]).max())
    if disp > MAX_SHIFT:
        raise GfxTitleError(f"정렬 변위 {disp:.2f}px 가 {MAX_SHIFT}px 를 넘음")
    return cv2.warpAffine(small, a, (w, h), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)


def compose(orig_rgb, new_rgb):
    """로고 상자 안에서 크게 다른 픽셀(+주변)만 새 그림으로. 상자 밖은 원본 그대로."""
    import cv2
    o, n = orig_rgb.astype(np.float32), new_rgb.astype(np.float32)
    x0, y0, x1, y1 = BOX
    d = np.abs(n - o).sum(2)
    ix0, iy0, iy1 = x0 + INSET, y0 + INSET, y1 - INSET     # 오른쪽은 화면 끝이라 안쪽으로 들이지 않음
    m = np.zeros(d.shape, np.uint8)
    m[iy0:iy1, ix0:x1] = d[iy0:iy1, ix0:x1] > DIFF
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((CLOSE, CLOSE), np.uint8))
    m = cv2.dilate(m, np.ones((GROW, GROW), np.uint8))
    f = cv2.GaussianBlur(m.astype(np.float32), (FEATHER, FEATHER), 0)
    keep = np.zeros(d.shape, np.float32)
    keep[y0:y1, x0:x1] = 1
    f = (f * keep)[..., None]
    return np.clip(np.rint(o * (1 - f) + n * f), 0, 255).astype(np.uint8)


def _load(path):
    if not os.path.exists(path):
        raise GfxTitleError(f"타이틀 그림 없음 {path}")
    with open(path, "rb") as fh:
        raw = fh.read()
    if hashlib.sha1(raw).hexdigest() != TITLE_SHA1:
        raise GfxTitleError(f"{path} SHA1 이 기록과 다름")
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as im:
        return np.asarray(im.convert("RGB"))


def apply_title(read, png_path):
    """read(경로) → 원본 바이트. {TITLEA–F 경로: 새 PSI 바이트}."""
    new = _load(png_path)
    psis = {k: Psi.parse(read(f"/DATAIMG/TITLE/TITLE{k}.PSI")) for k in PIECES}
    rgba = join(psis)
    orig = np.ascontiguousarray(rgba[:VIS_H, :, :3])
    out = rgba.copy()
    out[:VIS_H, :, :3] = compose(orig, register(orig, new))
    res = {f"/DATAIMG/TITLE/TITLE{k}.PSI": p.to_bytes() for k, p in split(out, psis).items()}
    got = hashlib.sha1(b"".join(res[p] for p in sorted(res))).hexdigest()
    if got != TITLE_OUT_SHA1:
        raise GfxTitleError(f"타이틀 출력 SHA1 {got} 이 기록과 다름(OpenCV 버전 등 확인, docs/build.md)")
    return res
