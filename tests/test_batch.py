"""번역 작업 묶음(배치) 생성·병합 테스트."""
import pytest

from tools.batch import BatchError, expand, make_batches, parse_tsv, render, row_errors

ROWS = [
    {"id": "Q/F1#000", "op": 20, "src": "港"},
    {"id": "Q/F1#001", "op": 56, "src": "町の男"},
    {"id": "Q/F1#002", "op": 57, "src": "やあ。"},
    {"id": "Q/F1#003", "op": 56, "src": "町の男"},
    {"id": "Q/F1#004", "op": 57, "src": "やあ。"},          # 같은 원문 → 한 번만
    {"id": "Q/F2#000", "op": 56, "src": "町の女"},
    {"id": "Q/F2#001", "op": 57, "src": "こんにちは。"},
    {"id": "Q/F9#000", "op": 57, "src": "デバッグ"},
]


def test_make_batches_dedupes_and_skips_known():
    bs = make_batches(ROWS, known={"港": "항구"}, size=100, skip=("Q/F9",))
    assert len(bs) == 1
    todo = [r["src"] for r in bs[0] if r["todo"]]
    assert todo == ["町の男", "やあ。", "町の女", "こんにちは。"]
    assert all(not r["id"].startswith("Q/F9") for r in bs[0])
    assert bs[0][0]["known"] == "항구" and bs[0][2]["speaker"] == "町の男"


def test_make_batches_splits_at_speaker_boundary():
    bs = make_batches(ROWS, known={}, size=2, skip=("Q/F9",))
    assert len(bs) == 2
    assert bs[1][0]["id"] == "Q/F1#003"           # 화자 줄에서 끊음
    assert [r["src"] for r in bs[1] if r["todo"]] == ["町の女", "こんにちは。"]


def test_render_and_parse_roundtrip():
    b = make_batches(ROWS, known={}, size=100, skip=("Q/F9",))[0]
    text = render(b)
    assert "Q/F1#002\t57\t町の男\tやあ。\tTODO" in text
    got = parse_tsv("Q/F1#002\t안녕．\n\nQ/F1#001\t마을 남자\n", b)
    assert got == {"やあ。": "안녕．", "町の男": "마을 남자"}
    with pytest.raises(BatchError):
        parse_tsv("Q/F1#004\t안녕．\n", b)          # TODO 가 아닌 줄


def test_row_errors_collects_all():
    src = {r["id"]: r for r in ROWS}
    errs = row_errors({"やあ。": "안녕.", "こんにちは。": "가" * 30}, ROWS, src)
    assert {e[0] for e in errs} == {"Q/F1#002", "Q/F1#004", "Q/F2#001"}


def test_expand_states():
    out = expand(ROWS, {"港": "항구", "やあ。": "안녕．"}, skip=("Q/F9",), state="needs_review")
    by = {r["id"]: r for r in out}
    assert by["Q/F1#004"]["ko"] == "안녕．" and by["Q/F1#004"]["state"] == "needs_review"
    assert by["Q/F1#001"]["state"] == "untranslated"
    assert by["Q/F9#000"]["state"] == "untranslated" and "디버그" in by["Q/F9#000"]["note"]


def test_apply_fixes_propagates_to_same_source():
    from tools.batch import apply_fixes
    rows = expand(ROWS, {"やあ。": "안녕．", "港": "항구"}, skip=("Q/F9",))
    out = apply_fixes(rows, "Q/F1#004\t안녕하세요．\t존댓말로\n")
    by = {r["id"]: r for r in out}
    assert by["Q/F1#002"]["ko"] == by["Q/F1#004"]["ko"] == "안녕하세요．"
    assert by["Q/F1#000"]["ko"] == "항구"
    with pytest.raises(BatchError):
        apply_fixes(rows, "Q/F1#999\t없음\t이유\n")
    with pytest.raises(BatchError):
        apply_fixes(rows, "Q/F1#001\t번역\t미번역 줄은 검수 대상 아님\n")
