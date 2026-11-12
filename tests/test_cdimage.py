"""MODE2/2352 섹터 인코딩·ISO9660 목록·FILEZ.DAT 해석 테스트."""
import os

import pytest

from tools import cdimage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "orig", "tsugunai.bin")
need_bin = pytest.mark.skipif(not os.path.exists(BIN), reason="원본 이미지 없음")


def test_edc_known_zero():
    assert cdimage.edc(b"") == 0


@need_bin
@pytest.mark.parametrize("lba", [16, 17, 18, 22, 1000, 201066, 314650, 315360])
def test_reencode_matches_original_sector(lba):
    with open(BIN, "rb") as f:
        f.seek(lba * 2352)
        raw = f.read(2352)
    sub = raw[16:24]
    data = raw[24:24 + 2048]
    assert cdimage.encode_form1(lba, sub, data) == raw


@need_bin
def test_iso_listing_and_filez_agree():
    img = cdimage.Image(BIN)
    files = img.list_files()
    assert len(files) == 2486
    by = {f.path: f for f in files}
    assert by["/SYSTEM.CNF"].size == 57
    fz = cdimage.Filez.parse(img.read_file(by["/FILEZ.DAT"]))
    assert len(fz.entries) == 2483  # SYSTEM.CNF·실행파일·FILEZ.DAT 제외
    ent = fz.find("/DATAIMG/CHARA/C00/C00_01.MDL")
    assert (ent.lba, ent.size) == (16990, 642346)
    # 모든 FILEZ 항목이 ISO 디렉터리와 LBA·크기 일치
    iso_by_key = {(f.lba, f.size) for f in files}
    assert all((e.lba, e.size) in iso_by_key for e in fz.entries)


def test_filez_roundtrip_bytes():
    if not os.path.exists(BIN):
        pytest.skip("원본 이미지 없음")
    img = cdimage.Image(BIN)
    by = {f.path: f for f in img.list_files()}
    raw = img.read_file(by["/FILEZ.DAT"])
    assert cdimage.Filez.parse(raw).to_bytes() == raw


def test_filez_name_rule():
    assert cdimage.filez_name("/DATAIMG/FONT/FONT.BIN") == b"TAIMGFONTFONTBIN"
    assert cdimage.filez_name("/DATAIMG/CHARA/C00/C00_01.MDL") == b"HARAC00C00_01MDL"


@need_bin
def test_every_filez_entry_matches_name_rule():
    img = cdimage.Image(BIN)
    files = img.list_files()
    by = {f.path: f for f in files}
    fz = cdimage.Filez.parse(img.read_file(by["/FILEZ.DAT"]))
    key = {(f.lba, f.size): f.path for f in files}
    for e in fz.entries:
        assert e.name.rstrip(b"\0") == cdimage.filez_name(key[(e.lba, e.size)])
