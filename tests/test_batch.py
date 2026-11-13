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


def test_apply_fixes_single_row_override():
    """'!id' 는 그 줄만 고친다(화자에 따라 같은 원문을 다르게 옮길 때)."""
    from tools.batch import apply_fixes, rows_errors
    rows = expand(ROWS, {"やあ。": "안녕．"}, skip=("Q/F9",))
    out = apply_fixes(rows, "!Q/F1#004\t안녕하세요．\t다른 화자\n")
    by = {r["id"]: r for r in out}
    assert by["Q/F1#002"]["ko"] == "안녕．" and by["Q/F1#004"]["ko"] == "안녕하세요．"
    src = {r["id"]: r for r in ROWS}
    assert rows_errors(out, src) == []
    bad = apply_fixes(rows, "!Q/F1#004\t안녕.\t반각\n")
    assert [e[0] for e in rows_errors(bad, src)] == ["Q/F1#004"]


def test_quest_group_selection_and_skips():
    """여러 퀘스트를 한 묶음으로: 순서대로 고르고 각 디버그 스크립트를 뺀다."""
    from tools.batch import group_rows, group_skips
    rows = [{"id": "MQ02/M02_00#000", "op": 57, "src": "あ"},
            {"id": "MQ01/M01_00#000", "op": 57, "src": "あ"},
            {"id": "MQ01/M01_99#000", "op": 57, "src": "デバッグ"},
            {"id": "MQ03/M03_00#000", "op": 57, "src": "い"}]
    got = group_rows(rows, "MQ01,MQ02")
    assert [r["id"] for r in got] == ["MQ01/M01_00#000", "MQ01/M01_99#000", "MQ02/M02_00#000"]
    assert group_skips("MQ01,MQ02") == ("MQ01/M01_99", "MQ02/M02_99")
    bs = make_batches(got, {}, 100, group_skips("MQ01,MQ02"))
    assert [r["src"] for r in bs[0] if r["todo"]] == ["あ"]     # 퀘스트를 넘어 한 번만


def test_fix_group_propagates_across_quests(tmp_path, monkeypatch):
    """fix 에 퀘스트 묶음을 주면 같은 원문은 묶음 안 모든 퀘스트에서 고친다."""
    import json
    import tools.batch as tb
    src = [{"id": "MQ01/M01_00#000", "op": 57, "src": "やあ。"},
           {"id": "MQ02/M02_00#000", "op": 57, "src": "やあ。"}]
    (tmp_path / "src.jsonl").write_text("".join(json.dumps(r) + "\n" for r in src))
    ko = tmp_path / "ko"
    ko.mkdir()
    for r in src:
        q = r["id"][:4]
        (ko / f"{q}.jsonl").write_text(json.dumps({**r, "ko": "안녕．", "state": "needs_review"}) + "\n")
    fix = tmp_path / "f.tsv"
    fix.write_text("MQ02/M02_00#000\t안녕하세요．\t존댓말\n")
    monkeypatch.setattr(tb, "SRC_PATH", str(tmp_path / "src.jsonl"))
    monkeypatch.setattr(tb, "KO_DIR", str(ko))
    tb.main("fix", "MQ01,MQ02", str(fix))
    for q in ("MQ01", "MQ02"):
        assert json.loads((ko / f"{q}.jsonl").read_text())["ko"] == "안녕하세요．"
