"""파일 교체·재배치 디스크 빌더 테스트."""
import filecmp
import os

import pytest

from tools import cdimage
from tools.discbuild import build, DiscBuildError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "orig", "tsugunai.bin")
pytestmark = pytest.mark.skipif(not os.path.exists(BIN), reason="원본 이미지 없음")

SCP = "/DATAIMG/MQ00/SCP/M00_00.SCP"     # 4528 B, 3섹터
OTHER = "/DATAIMG/MQ00/SCP/M00_01.SCP"


@pytest.fixture(scope="module")
def orig():
    img = cdimage.Image(BIN)
    return img, {f.path: f for f in img.list_files()}


def _files(path):
    img = cdimage.Image(path)
    by = {f.path: f for f in img.list_files()}
    fz = cdimage.Filez.parse(img.read_file(by["/FILEZ.DAT"]))
    return img, by, fz


def test_no_change_is_identical(tmp_path):
    out = tmp_path / "out.bin"
    build(BIN, {}, out)
    assert filecmp.cmp(BIN, out, shallow=False)


def test_in_place_replacement(tmp_path, orig):
    img0, by0 = orig
    new = b"K" * 5000  # 3섹터 안에 들어감
    out = tmp_path / "out.bin"
    report = build(BIN, {SCP: new}, out)
    img, by, fz = _files(out)
    assert img.read_file(by[SCP]) == new
    assert by[SCP].lba == by0[SCP].lba
    e = fz.find(SCP)
    assert (e.lba, e.size) == (by0[SCP].lba, 5000)
    assert img.read_file(by[OTHER]) == img0.read_file(by0[OTHER])
    assert report.relocated == []


def test_growth_relocates_to_end(tmp_path, orig):
    img0, by0 = orig
    new = bytes(range(256)) * 100  # 25600 B > 3섹터
    out = tmp_path / "out.bin"
    report = build(BIN, {SCP: new}, out)
    img, by, fz = _files(out)
    assert img.read_file(by[SCP]) == new
    assert by[SCP].lba >= 315584 - 150  # 기존 데이터 끝(315434) 이후
    e = fz.find(SCP)
    assert (e.lba, e.size) == (by[SCP].lba, len(new))
    assert report.relocated == [SCP]
    # 볼륨 크기와 실제 섹터 수 일치
    import struct
    vol = struct.unpack_from("<I", img.data(16), 80)[0]
    assert vol * 2352 == os.path.getsize(out)
    # 변경된 모든 섹터의 EDC/ECC가 유효
    for lba in report.written_sectors:
        raw = img.sector(lba)
        assert cdimage.encode_form1(lba, raw[16:24], raw[24:2072]) == raw
    # 나머지 파일 불변
    for p in (OTHER, "/SCPS_110.07", "/SYSTEM.CNF"):
        assert img.read_file(by[p]) == img0.read_file(by0[p])


def test_unknown_path_fails(tmp_path):
    with pytest.raises(DiscBuildError):
        build(BIN, {"/NOPE.BIN": b"x"}, tmp_path / "o.bin")


def test_refuses_to_overwrite_source(tmp_path):
    with pytest.raises(DiscBuildError):
        build(BIN, {}, BIN)
