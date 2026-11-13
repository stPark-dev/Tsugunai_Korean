"""번역 파일 검사 테스트."""
import json
import os

import pytest

from tools.translation import (TranslationError, check, cells, glossary_hints, load_dir,
                               tokens)

SRC = {"A#000": {"id": "A#000", "op": 57, "src": "{n:01}は{c:09}【宝珠】{c:08}を手に入れた。"},
       "A#001": {"id": "A#001", "op": 56, "src": "若い兵士"},
       "A#002": {"id": "A#002", "op": 57, "src": "あ"}}


def row(i, ko, state="needs_review", **kw):
    return {"id": i, "src": SRC[i]["src"], "ko": ko, "state": state, **kw}


GOOD = row("A#000", "{n:01}{j:은/는} {c:09}【보주】{c:08}를 손에 넣었다．")


def test_tokens_and_cells():
    assert tokens(GOOD["ko"]) == ["{n:01}", "{j:은/는}", "{c:09}", "{c:08}"]
    assert cells("{c:09}가 나{c:08}") == 3
    assert cells("{n:01}{j:은/는}") == 5          # 이름 최장 기본값 4칸(라후르크) + 조사 1칸


def test_good_row_passes():
    assert check([GOOD], SRC) == []


def test_protected_source_mismatch_fails():
    with pytest.raises(TranslationError):
        check([{**GOOD, "src": "変更"}], SRC)


def test_unknown_id_and_duplicate_fail():
    with pytest.raises(TranslationError):
        check([{**GOOD, "id": "A#999"}], SRC)
    with pytest.raises(TranslationError):
        check([GOOD, GOOD], SRC)


def test_token_mismatch_fails():
    with pytest.raises(TranslationError):
        check([row("A#000", "{n:01}{j:은/는} 보주를 손에 넣었다．")], SRC)


def test_josa_must_follow_name():
    with pytest.raises(TranslationError):
        check([row("A#000", "{n:01} {j:은/는} {c:09}【보주】{c:08}를 손에 넣었다．")], SRC)


def test_width_limit_fails_and_warns():
    with pytest.raises(TranslationError):
        check([row("A#002", "가" * 26)], SRC)
    assert check([row("A#002", "가" * 23)], SRC) == [("A#002", "폭 23칸(목표 22)")]


def test_halfwidth_ascii_fails():
    # 반각 영숫자·기호는 화면에 그려지지 않음(PoC3). 반각 공백만 허용
    with pytest.raises(TranslationError):
        check([row("A#002", "가.")], SRC)
    assert check([row("A#002", "가 나．")], SRC) == []


def test_state_rules():
    with pytest.raises(TranslationError):
        check([row("A#002", "", state="needs_review")], SRC)
    with pytest.raises(TranslationError):
        check([row("A#002", "가", state="done")], SRC)
    assert check([row("A#002", "", state="untranslated")], SRC) == []
    assert check([row("A#002", "가", state="reviewed")], SRC) == []


def test_glossary_hints():
    gl = [{"ja": "宝珠", "ko": "보주", "cat": "term"}, {"ja": "若い兵士", "ko": "젊은 병사", "cat": "role"}]
    assert glossary_hints([GOOD, row("A#001", "젊은 군인")], SRC, gl) == [("A#001", "若い兵士→젊은 병사")]


def test_load_dir(tmp_path):
    (tmp_path / "A.jsonl").write_text(json.dumps(GOOD, ensure_ascii=False) + "\n", encoding="utf-8")
    assert load_dir(str(tmp_path)) == [GOOD]


KO = os.path.join(os.path.dirname(__file__), "..", "text", "ko")


def test_project_translations_pass():
    if not os.path.isdir(KO):
        pytest.skip("번역 없음")
    src = {r["id"]: r for r in map(json.loads, open(os.path.join(KO, "..", "scp_src.jsonl"), encoding="utf-8"))}
    check(load_dir(KO), src)
