"""데이터 파일 텍스트 추출·적용 테스트 (실제 추출 파일 필요)."""
import os

import pytest

from tools.data_text import PATHS, DataTextError, apply_texts, extract_all
from tools.datafile import DataFileError
from tools.textcodec import encode_sjis

EX = os.path.join(os.path.dirname(__file__), "..", "work", "ex")


@pytest.fixture(scope="module")
def files():
    out = {}
    for p in PATHS.values():
        fn = EX + p
        if not os.path.exists(fn):
            pytest.skip("추출 파일 없음")
        out[p] = open(fn, "rb").read()
    return out


def _by_id(rows):
    return {r["id"]: r["src"] for r in rows}


def test_extract_known_strings(files):
    t = _by_id(extract_all(files))
    assert t["ITEM#000.name"] == "回復薬"
    assert t["ITEM#000.desc"] == "つかうと、Ｈｐが小回復する"
    assert t["WEAPON#000.skill"] == "ハイランド・ブレイヴ"
    assert t["INVENT#069.desc"] == "『運命に逆らえ』と書かれたメモ"
    assert t["MAGIC#000.desc"] == "敵１体に火炎系の小ダメージ"
    assert t["AMULET#000.name"] == "鳥の護符"
    assert t["RECORD#000.title"] == "試練の始まり"
    assert t["EST#000-0.name"] == "アンシリーコート"
    assert all(r["src"] for r in extract_all(files))


def test_ids_unique(files):
    rows = extract_all(files)
    assert len({r["id"] for r in rows}) == len(rows)


def test_apply_roundtrip_and_change(files):
    rows = extract_all(files)
    assert apply_texts(files, {}, encode_sjis) == {}
    # 원문 그대로 넣으면 바뀌는 파일 없음
    same = apply_texts(files, {r["id"]: r["src"] for r in rows}, encode_sjis)
    assert same == {}
    out = apply_texts(files, {"ITEM#000.name": "回復薬回復薬回復薬", "EST#000-0.name": "アンシリー"},
                      encode_sjis)
    assert set(out) == {PATHS["ITEM"], PATHS["EST"]}
    t = _by_id(extract_all({**files, **out}))
    assert t["ITEM#000.name"] == "回復薬回復薬回復薬"
    assert t["ITEM#001.name"] == _by_id(rows)["ITEM#001.name"]
    assert t["EST#000-0.name"] == "アンシリー"


def test_apply_errors(files):
    with pytest.raises(DataTextError):
        apply_texts(files, {"ITEM#999.name": "x"}, encode_sjis)
    with pytest.raises(DataTextError):
        apply_texts(files, {"NOPE#000.name": "x"}, encode_sjis)
    with pytest.raises(DataTextError):
        apply_texts(files, {"ITEM#000.bogus": "x"}, encode_sjis)
    with pytest.raises(DataFileError):
        apply_texts(files, {"EST#000-0.name": "あ" * 16}, encode_sjis)
