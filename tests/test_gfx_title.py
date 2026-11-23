"""타이틀 로고(tools/gfx_title.py, G1) 테스트."""
import hashlib
import os

import numpy as np
import pytest

import tools.gfx_title as gt
from tools.gfx_title import (BOX, PIECES, GfxTitleError, apply_title, compose, join, register, split)
from tools.psi import Psi

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG = os.path.join(ROOT, "orig", "tsugunai.bin")
ASSET = os.path.join(ROOT, "assets", "title_ko.png")


def _bg(h=448, w=640, seed=1):
    """특징점이 잘 잡히는 무늬 배경(RGB)."""
    import cv2
    rng = np.random.default_rng(seed)
    a = rng.integers(0, 256, (h // 8, w // 8, 3), dtype=np.uint8)
    a = cv2.resize(a, (w, h), interpolation=cv2.INTER_CUBIC)
    for i in range(0, w, 37):
        cv2.line(a, (i, 0), (w - i, h), (255, 255, 255), 1)
    return a


def _pieces(seed=2):
    rng = np.random.default_rng(seed)
    out = {}
    for name, (x, y, w, h) in PIECES.items():
        px = rng.integers(0, 256, (h, w, 4), dtype=np.uint8)
        px[..., 3] = 0x80
        out[name] = Psi(bytes(32), w, h, 32, None, px.tobytes())
    return out


def test_join_split_round_trip():
    ps = _pieces()
    rgba = join(ps)
    assert rgba.shape == (512, 640, 4)
    back = split(rgba, ps)
    assert all(back[k].to_bytes() == ps[k].to_bytes() for k in ps)


def test_join_rejects_8bpp_or_wrong_size():
    ps = _pieces()
    ps["A"] = Psi(bytes(32), 256, 256, 8, bytes(1024), bytes(256 * 256))
    with pytest.raises(GfxTitleError):
        join(ps)
    ps = _pieces()
    ps["C"] = Psi(bytes(32), 64, 256, 32, None, bytes(64 * 256 * 4))
    with pytest.raises(GfxTitleError):
        join(ps)


def test_register_aligns_outpainted_4x3_image():
    import cv2
    o = _bg()
    tall = np.concatenate([o, o[-32:][::-1]], axis=0)            # 아래 32줄을 덧그린 640×480
    new = cv2.resize(tall, (1448, 1086), interpolation=cv2.INTER_CUBIC)
    w = register(o, new)
    assert w.shape == o.shape
    assert np.abs(w.astype(int) - o.astype(int)).mean() < 8


def test_register_rejects_shifted_image():
    import cv2
    o = _bg()
    shifted = np.roll(o, 12, axis=1)                              # 12px 어긋난 그림(허용 변위 3px 초과)
    with pytest.raises(GfxTitleError):
        register(o, cv2.resize(shifted, (1280, 896), interpolation=cv2.INTER_CUBIC))


def test_register_rejects_unrelated_image():
    with pytest.raises(GfxTitleError):
        register(_bg(seed=1), _bg(1086, 1448, seed=9))


def test_compose_changes_only_strong_differences_inside_box():
    o = _bg()
    new = o.copy()
    x0, y0, x1, y1 = BOX
    new[y0 + 40:y0 + 80, x0 + 40:x0 + 120] = 255                 # 상자 안 새 획
    new[10:30, 10:60] = 0                                         # 상자 밖 차이는 무시
    out = compose(o, new)
    assert (out[y0 + 50:y0 + 70, x0 + 60:x0 + 100] == 255).all()
    mask = np.ones(o.shape[:2], bool)
    mask[y0:y1, x0:x1] = False
    assert (out[mask] == o[mask]).all()
    assert (out[20, 30] == o[20, 30]).all()


def test_compose_feather_vanishes_at_box_edge():
    o = _bg()
    new = 255 - o                                                 # 어디나 크게 다름
    out = compose(o, new)
    x0, y0, x1, y1 = BOX
    assert (out[y0:y1, x0] == o[y0:y1, x0]).all()                 # 왼쪽 경계 열은 원본(이음새 없음)
    assert (out[y0, x0:x1] == o[y0, x0:x1]).all() and (out[y1 - 1, x0:x1] == o[y1 - 1, x0:x1]).all()
    assert (out[(y0 + y1) // 2, x0 + 40] == new[(y0 + y1) // 2, x0 + 40]).all()


def test_apply_title_rejects_missing_or_wrong_asset(tmp_path):
    with pytest.raises(GfxTitleError):
        apply_title(lambda p: b"", str(tmp_path / "none.png"))
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not the reviewed image")
    with pytest.raises(GfxTitleError):
        apply_title(lambda p: b"", str(bad))


@pytest.mark.skipif(not (os.path.exists(ORIG) and os.path.exists(ASSET)), reason="원본 이미지·타이틀 그림 없음")
def test_apply_title_on_real_files_keeps_everything_outside_logo():
    from tools import cdimage
    img = cdimage.Image(ORIG)
    by = {f.path: f for f in img.list_files()}
    read = lambda p: img.read_file(by[p])
    out = apply_title(read, ASSET)
    paths = {f"/DATAIMG/TITLE/TITLE{k}.PSI" for k in PIECES}
    assert set(out) == paths
    old = join({k: Psi.parse(read(f"/DATAIMG/TITLE/TITLE{k}.PSI")) for k in PIECES})
    new = join({k: Psi.parse(out[f"/DATAIMG/TITLE/TITLE{k}.PSI"]) for k in PIECES})
    x0, y0, x1, y1 = BOX
    mask = np.ones(old.shape[:2], bool)
    mask[y0:y1, x0:x1] = False
    assert (new[mask] == old[mask]).all()                         # 로고 상자 밖·아래 64줄·투명 줄 그대로
    assert (new[..., 3] == old[..., 3]).all()
    assert (new[y0:y1, x0:x1] != old[y0:y1, x0:x1]).any(axis=2).mean() > 0.05
    h = hashlib.sha1(b"".join(out[p] for p in sorted(out))).hexdigest()
    assert h == gt.TITLE_OUT_SHA1                                 # 기록된 출력(재현성)


@pytest.mark.skipif(not (os.path.exists(ORIG) and os.path.exists(ASSET)), reason="원본 이미지·타이틀 그림 없음")
def test_apply_title_fails_when_output_differs_from_record(monkeypatch):
    from tools import cdimage
    img = cdimage.Image(ORIG)
    by = {f.path: f for f in img.list_files()}
    monkeypatch.setattr(gt, "TITLE_OUT_SHA1", "0" * 40)
    with pytest.raises(GfxTitleError):
        apply_title(lambda p: img.read_file(by[p]), ASSET)
