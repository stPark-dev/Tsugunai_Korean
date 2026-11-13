"""원문 텍스트 ↔ 토큰 문자열 가역 변환 테스트."""
import glob
import os

import pytest

from tools.textcodec import decode_sjis, encode_sjis, TextCodecError
from tools.scp import Script

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCPS = sorted(glob.glob(os.path.join(ROOT, "work/ex/DATAIMG/**/SCP/*.SCP"), recursive=True))


def test_tokens():
    raw = "必ず".encode("cp932") + b"\x01\x0a" + "そうび".encode("cp932") + b"\x01\x08" + b"\x02\x01"
    s = decode_sjis(raw)
    assert s == "必ず{c:0a}そうび{c:08}{n:01}"
    assert encode_sjis(s) == raw


def test_halfwidth_ascii_and_space():
    raw = b"  AB" + "１".encode("cp932")
    assert decode_sjis(raw) == "  AB１"
    assert encode_sjis("  AB１") == raw


def test_unknown_control_rejected():
    with pytest.raises(TextCodecError):
        decode_sjis(b"\x03\x01")
    with pytest.raises(TextCodecError):
        encode_sjis("{x:01}")


def test_literal_brace_rejected_in_source():
    with pytest.raises(TextCodecError):
        decode_sjis(b"{")


@pytest.mark.skipif(not SCPS, reason="추출 파일 없음")
def test_all_script_texts_roundtrip():
    n = 0
    for fn in SCPS:
        for t in Script.parse(open(fn, "rb").read()).texts():
            assert encode_sjis(decode_sjis(t.text)) == t.text, (fn, t.text)
            n += 1
    assert n == 44290


def test_newline_passthrough():
    b = "エラー".encode("cp932") + b"\n"
    assert decode_sjis(b) == "エラー\n"
    assert encode_sjis("エラー\n") == b
