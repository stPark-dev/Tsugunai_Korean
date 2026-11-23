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
    assert TEXT_OPS == {0x14, 0x38, 0x39, 0x3B}


@need
def test_all_text_records_follow_padding_rule():
    for fn in SCPS:
        for t in Script.parse(open(fn, "rb").read()).texts():
            n = len(t.text)
            assert t.payload == t.text + b"\0" * (4 - n % 4), (fn, t.op, t.payload)


def _embedded(op, head=b"", tail_len=20):
    """하위 스크립트를 품은 레코드(op 0x3F/0x8A: 시퀀스+20바이트 꼬리, op 0xA1: 64바이트 머리+시퀀스).

    파일: 헤더 + 0x39 "AB" + [op: head | 0x800D{ 0x01 → 아래 0x60, 0x01 → 아래 FFFF } 0x60 FFFF | tail] + FFFF
    하위 점프는 파일 기준 절대 오프셋(실제 M00_07.SCP 의 op 0x3F 와 같은 구조).
    """
    text = _rec(0x39, b"AB\0\0")
    base = 0x20 + len(text) + 4 + len(head)          # 하위 시퀀스 시작(파일 오프셋)
    j1_at, j2_at = base + 4, base + 12
    rec60_at = base + 4 + 16
    sep_at = rec60_at + 8
    cont = struct.pack("<HH", 0x800D, 4 + 16) + _rec(0x01, struct.pack("<I", rec60_at)) + _rec(0x01, struct.pack("<I", sep_at))
    seq = cont + _rec(0x60, b"\0\0\0\0") + b"\xff" * 4
    emb = _rec(op, head + seq + bytes(range(tail_len)))
    data = struct.pack("<8I", 0x20, 0, 0, 0, 0, 0, 0, 0) + text + emb + b"\xff" * 4
    assert data[j1_at:j1_at + 2] == b"\x01\x00" and data[j2_at:j2_at + 2] == b"\x01\x00"
    return data, j1_at, j2_at


@pytest.mark.parametrize("op,head,tail", [(0x3F, b"", 20), (0x8A, b"", 20), (0xA1, bytes(64), 0)])
def test_embedded_script_jumps_relocate(op, head, tail):
    raw, j1_at, j2_at = _embedded(op, head, tail)
    s = Script.parse(raw)
    assert s.to_bytes() == raw
    s.texts()[0].set_text(b"ABCDEFGHIJK")                     # 8바이트 늘림 → 뒤 레코드 전부 +8
    out = s.to_bytes()
    t1, t2 = (struct.unpack_from("<I", out, a + 8 + 4)[0] for a in (j1_at, j2_at))
    assert out[t1:t1 + 2] == b"\x60\x00"                      # 같은 하위 레코드를 가리킴
    assert out[t2:t2 + 4] == b"\xff" * 4                      # 하위 구분자
    assert out[-4 - tail:-4] == bytes(range(tail))            # 꼬리 그대로
    assert Script.parse(out).to_bytes() == out


def test_embedded_jump_to_middle_of_record_rejected():
    raw, j1_at, _ = _embedded(0x3F)
    raw = bytearray(raw)
    struct.pack_into("<I", raw, j1_at + 4, struct.unpack_from("<I", raw, j1_at + 4)[0] + 4)
    with pytest.raises(ScpError):
        Script.parse(bytes(raw))


@need
def test_grow_every_text_keeps_embedded_jumps_in_all_scripts():
    """M00_07.SCP 몬스터 배치(op 0x3F) 하위 점프가 안 옮겨져 인카운트 때 멈춘 회귀."""
    for fn in SCPS:
        s = Script.parse(open(fn, "rb").read())
        before = [j.target_node_desc() for j in s.jumps()]
        for t in s.texts():
            t.set_text(t.text + "가나".encode("cp949"))
        s2 = Script.parse(s.to_bytes())
        assert [j.target_node_desc() for j in s2.jumps()] == before, fn


@need
def test_no_jump_like_pattern_left_in_opaque_records():
    """아직 모르는 '점프를 품은 op' 가 남아 있으면 실패(이번 결함처럼 가드가 못 보는 점프)."""
    from tools.scp import Rec, Jump
    for fn in SCPS:
        s = Script.parse(open(fn, "rb").read())
        starts = {n.pos for n in s.walk()}
        for n in s.walk():
            if type(n) is Rec and n.op not in TEXT_OPS:
                p = n.payload
                for i in range(0, len(p) - 7, 4):
                    if p[i:i + 4] == b"\x01\x00\x08\x00":
                        assert struct.unpack_from("<I", p, i + 4)[0] not in starts, (fn, hex(n.pos), hex(n.op))
