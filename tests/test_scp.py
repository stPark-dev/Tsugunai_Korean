"""SCP 스크립트 파서/직렬화기 테스트."""
import glob
import os
import struct

import pytest

from tools.scp import Script, ScpError, TEXT_OPS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCPS = sorted(glob.glob(os.path.join(ROOT, "work/ex/DATAIMG/**/SCP/*.SCP"), recursive=True))
need = pytest.mark.skipif(not SCPS, reason="추출 파일 없음")


def _rec(op, payload):
    return struct.pack("<HH", op, 4 + len(payload)) + payload


def _synthetic():
    # 헤더(8×u32) + [0x8005 { 0x39 "AB", 0x01 → sep2 }] FFFF + [0x01 → EOF] FFFF
    text = _rec(0x39, b"AB\0\0")
    jump = _rec(0x01, struct.pack("<I", 0))  # 나중에 채움
    cont_len = 4 + len(text) + len(jump)
    body = struct.pack("<HH", 0x8005, cont_len) + text + jump + b"\xff" * 4
    sep2 = 0x20 + len(body) - 4
    jump2 = _rec(0x01, struct.pack("<I", 0))
    data = bytearray(struct.pack("<8I", 0x20, sep2 + 4, 0, 0, 0, 0, 0, 0) + body + jump2 + b"\xff" * 4)
    struct.pack_into("<I", data, 0x20 + 4 + len(text) + 4, sep2)
    struct.pack_into("<I", data, sep2 + 4 + 4, len(data))
    return bytes(data)


def test_synthetic_roundtrip():
    raw = _synthetic()
    assert Script.parse(raw).to_bytes() == raw


def test_grow_text_relocates_offsets():
    raw = _synthetic()
    s = Script.parse(raw)
    t = s.texts()[0]
    t.set_text(b"ABCDEFG")
    out = s.to_bytes()
    s2 = Script.parse(out)
    assert s2.texts()[0].text == b"ABCDEFG"
    # 컨테이너 길이 갱신
    assert struct.unpack_from("<H", out, 0x22)[0] == 4 + 12 + 8
    # 점프가 여전히 같은 논리 위치(구분자, EOF)를 가리킴
    j1, j2 = s2.jumps()
    assert out[j1.target:j1.target + 4] == b"\xff" * 4
    assert j2.target == len(out)
    # 헤더 두 번째 항목이 두 번째 구역 시작으로 이동
    hdr = struct.unpack_from("<8I", out, 0)
    assert hdr[1] == j1.target + 4


def test_text_must_not_contain_nul():
    s = Script.parse(_synthetic())
    with pytest.raises(ScpError):
        s.texts()[0].set_text(b"A\0B")


def test_bad_jump_target_rejected():
    raw = bytearray(_synthetic())
    # 첫 점프를 레코드 중간으로
    off = 0x20 + 4 + 8 + 4
    struct.pack_into("<I", raw, off, 0x26)
    with pytest.raises(ScpError):
        Script.parse(bytes(raw))


@need
def test_all_scripts_roundtrip():
    for fn in SCPS:
        raw = open(fn, "rb").read()
        assert Script.parse(raw).to_bytes() == raw, fn


@need
def test_wrapped_container_length():
    fn = [f for f in SCPS if f.endswith("M21_00.SCP")][0]
    s = Script.parse(open(fn, "rb").read())
    big = [c for c in s.containers() if c.size() > 0xFFFF]
    assert big and big[0].op == 0x8008


@need
def test_grow_every_text_in_real_script_reparses():
    fn = [f for f in SCPS if f.endswith("M00_25.SCP")][0]
    raw = open(fn, "rb").read()
    s = Script.parse(raw)
    before = [(j.target_node_desc()) for j in s.jumps()]
    for t in s.texts():
        t.set_text(t.text + "가나다".encode("cp949"))
    out = s.to_bytes()
    s2 = Script.parse(out)
    assert [j.target_node_desc() for j in s2.jumps()] == before
    assert len(s2.texts()) == len(s.texts())


def test_text_ops_constant():
    assert 0x39 in TEXT_OPS and 0x38 in TEXT_OPS


@need
def test_all_text_records_follow_padding_rule():
    for fn in SCPS:
        for t in Script.parse(open(fn, "rb").read()).texts():
            n = len(t.text)
            assert t.payload == t.text + b"\0" * (4 - n % 4), (fn, t.op, t.payload)
