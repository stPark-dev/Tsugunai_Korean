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
