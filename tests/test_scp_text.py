"""SCP 텍스트 추출·적용 테스트."""
import glob
import os

import pytest

from tools.scp_text import extract_all, apply_texts, ScpTextError
from tools.textcodec import encode_sjis

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(ROOT, "work/ex")
need = pytest.mark.skipif(not os.path.isdir(EX), reason="추출 파일 없음")


def _files():
    out = {}
    for fn in sorted(glob.glob(os.path.join(EX, "DATAIMG/**/SCP/*.SCP"), recursive=True)):
        out["/" + os.path.relpath(fn, EX)] = open(fn, "rb").read()
    return out


@need
def test_extract_counts_and_ids():
    rows = extract_all(_files())
    assert len(rows) == 44290
    assert len({r["id"] for r in rows}) == len(rows)
    first = [r for r in rows if r["id"].startswith("MQ00/M00_25#")][:2]
    assert first[0]["op"] == 0x38 and first[0]["src"] == "ルイ僧官"
    assert first[1]["op"] == 0x39 and first[1]["spk"] == "ルイ僧官"


@need
def test_apply_source_is_identity():
    files = _files()
    rows = extract_all(files)
    out = apply_texts(files, {r["id"]: r["src"] for r in rows}, encode_sjis)
    assert out == {}  # 바뀐 파일 없음


@need
def test_apply_changes_only_target_file():
    files = _files()
    rows = extract_all(files)
    rid = rows[1]["id"]
    out = apply_texts(files, {rid: rows[1]["src"] + "ＡＢ"}, encode_sjis)
    assert len(out) == 1


@need
def test_unknown_id_fails():
    with pytest.raises(ScpTextError):
        apply_texts(_files(), {"MQ99/NOPE#000": "x"}, encode_sjis)


@need
def test_apply_keeps_every_jump_target_including_monster_records():
    """M00_07 대사가 짧아지며 op 0x3F 하위 점프가 어긋나 인카운트 때 멈춘 회귀(상태 슬롯 3)."""
    from tools.scp import Script
    files = _files()
    rows = [r for r in extract_all(files) if r["id"].startswith("MQ00/M00_07#")]
    path = [p for p in files if p.endswith("/M00_07.SCP")][0]
    out = apply_texts(files, {rows[0]["id"]: "Ａ"}, encode_sjis)      # 앞쪽 대사를 줄여 뒤 전부 당김
    assert len(out[path]) < len(files[path])
    old, new = Script.parse(files[path]), Script.parse(out[path])
    assert [j.target_node_desc() for j in new.jumps()] == [j.target_node_desc() for j in old.jumps()]
    assert len(old.jumps()) > 20


def test_apply_fails_when_output_jumps_change(monkeypatch):
    """직렬화가 점프 대상을 잃으면 빌드가 멈춰야 한다(조용히 깨진 SCP 를 내지 않음)."""
    import struct
    import tools.scp_text as st
    from tools.scp import Script
    hdr = struct.pack("<8I", 0x20, 0, 0, 0, 0, 0, 0, 0)
    raw = hdr + struct.pack("<HH", 0x39, 8) + b"AB\0\0" + struct.pack("<HHI", 1, 8, 0x30) + b"\xff" * 4
    orig = Script.to_bytes
    def broken(self):
        b = bytearray(orig(self))
        struct.pack_into("<I", b, len(b) - 8, 0x20)                     # 점프를 다른 노드로
        return bytes(b)
    monkeypatch.setattr(Script, "to_bytes", broken)
    with pytest.raises(st.ScpTextError):
        st.apply_texts({"/DATAIMG/MQ00/SCP/M00_99.SCP": raw}, {"MQ00/M00_99#000": "ABCDEFG"}, encode_sjis)


def test_apply_fails_when_output_header_entry_changes(monkeypatch):
    """구역 진입 오프셋(헤더)이 다른 노드를 가리키게 되면 빌드가 멈춰야 한다."""
    import struct
    import tools.scp_text as st
    from tools.scp import Script
    hdr = struct.pack("<8I", 0x20, 0x28, 0, 0, 0, 0, 0, 0)
    raw = hdr + struct.pack("<HH", 0x39, 8) + b"AB\0\0" + b"\xff" * 4 + struct.pack("<HH", 0x39, 8) + b"CD\0\0"
    orig = Script.to_bytes
    def broken(self):
        b = bytearray(orig(self))
        struct.pack_into("<I", b, 4, 0x20)                               # 두 번째 구역 진입을 첫 레코드로
        return bytes(b)
    monkeypatch.setattr(Script, "to_bytes", broken)
    with pytest.raises(st.ScpTextError):
        st.apply_texts({"/DATAIMG/MQ00/SCP/M00_99.SCP": raw}, {"MQ00/M00_99#000": "ABCDEFG"}, encode_sjis)
