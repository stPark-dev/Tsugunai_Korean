"""용어집 형식 검사·원문 근거 확인 테스트."""
import json
import os

import pytest

from tools.glossary import GlossaryError, load, missing_in_sources, validate

OK = {"id": "G0001", "cat": "char", "ja": "フィセラ", "ko": "피세라", "na": "Fisela",
      "state": "draft", "note": ""}


def _e(**kw):
    return {**OK, **kw}


def test_valid_entry_passes():
    validate([OK, _e(id="G0002", ja="イフェム", ko="이페무")])


@pytest.mark.parametrize("bad", [
    _e(id="X1"),                 # ID 형식
    _e(cat="unknown"),           # 분류
    _e(state="done"),            # 상태
    _e(ko=""),                   # 빈 번역
    {k: v for k, v in OK.items() if k != "ja"},   # 필수 필드 없음
])
def test_invalid_entry_rejected(bad):
    with pytest.raises(GlossaryError):
        validate([bad])


def test_duplicate_id_rejected():
    with pytest.raises(GlossaryError):
        validate([OK, _e(ja="イフェム")])


def test_same_term_needs_distinct_scope():
    with pytest.raises(GlossaryError):
        validate([OK, _e(id="G0002")])
    validate([OK, _e(id="G0002", scope="MQ21")])


def test_unresolved_may_have_empty_ko():
    validate([_e(state="unresolved", ko="")])


def test_missing_in_sources():
    entries = [OK, _e(id="G0002", ja="イフェム"), _e(id="G0003", ja="ラフルク")]
    texts = ["おや、フィセラ…", "{c:09}イフェム{c:08}の家"]
    assert [e["id"] for e in missing_in_sources(entries, texts)] == ["G0003"]


def test_load_roundtrip(tmp_path):
    p = tmp_path / "g.jsonl"
    p.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in [OK]) + "\n", encoding="utf-8")
    assert load(str(p)) == [OK]


GLOSSARY = os.path.join(os.path.dirname(__file__), "..", "text", "glossary.jsonl")
TEXTS = [os.path.join(os.path.dirname(__file__), "..", "text", f)
         for f in ("scp_src.jsonl", "data_src.jsonl", "elf_src.jsonl")]


def test_project_glossary_valid_and_grounded():
    if not os.path.exists(GLOSSARY):
        pytest.skip("용어집 없음")
    entries = load(GLOSSARY)
    validate(entries)
    texts = [json.loads(l)["src"] for f in TEXTS for l in open(f, encoding="utf-8")]
    assert missing_in_sources(entries, texts) == []
    # 반각 영숫자·기호는 화면에 안 그려짐(PoC3) → 전각만
    assert [e["id"] for e in entries if any(0x21 <= ord(c) <= 0x7E for c in e["ko"])] == []
