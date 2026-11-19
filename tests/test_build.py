"""제품 빌드(tools/build.py) 검사 함수 테스트."""
import hashlib

import pytest

from tools.build import (BuildError, NAME_IDS, data_layout, default_names, encode_ui, merge_writers, publish, reject_reassigned,
                         selected_texts, stale_kanji, verify_source)


def test_verify_source_rejects_other_image(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"abc")
    verify_source(str(p), hashlib.sha1(b"abc").hexdigest())
    with pytest.raises(BuildError):
        verify_source(str(p), "0" * 40)


def test_selected_texts_skips_untranslated():
    rows = [{"id": "A#000", "ko": "가", "state": "reviewed"},
            {"id": "A#001", "ko": "", "state": "untranslated"}]
    assert selected_texts(rows) == {"A#000": "가"}


def test_default_names_from_glossary():
    gl = [{"ja": ja, "ko": ko, "cat": "char"} for ja, ko in
          [("レイス", "레이스"), ("イフェム", "이펨"), ("ラフルク", "라후르크"), ("フィセラ", "피세라"),
           ("アシュゴ", "아슈고"), ("ナビ", "나비"), ("ミミー", "미미")]]
    names = default_names(gl)
    assert names[NAME_IDS[0]] == "레이스" and names[NAME_IDS[6]] == "미미" and len(names) == 7


def test_default_names_missing_term_fails():
    with pytest.raises(BuildError):
        default_names([{"ja": "レイス", "ko": "레이스", "cat": "char"}])


def test_stale_kanji_lists_kept_source_using_reassigned_slots():
    used = {0x889F}                                     # 亜 슬롯이 한글로 바뀜
    rows = [{"id": "E#1", "src": "亜細"}, {"id": "E#2", "src": "かな"}, {"id": "E#3", "src": "亜"}]
    assert stale_kanji(rows, used, translated={"E#3"}) == {"E#1": "亜"}


def test_reject_reassigned_kanji_in_encoded_text():
    """번역문 속 한자가 한글에 내준 슬롯이면 다른 음절로 보이므로 실패."""
    reject_reassigned({"A#0": "가나", "B#0": "かな"}, {0x889F})
    with pytest.raises(BuildError):
        reject_reassigned({"A#0": "가亜"}, {0x889F})


def test_publish_success_writes_both(tmp_path):
    out = str(tmp_path / "o.bin")
    publish(out, lambda p: open(p, "wb").write(b"img"), lambda: {"distribution": False})
    assert open(out, "rb").read() == b"img"
    assert '"distribution": false' in open(out + ".manifest.json").read()


def test_publish_failure_leaves_nothing(tmp_path):
    out = str(tmp_path / "o.bin")
    open(out, "wb").write(b"old")
    open(out + ".manifest.json", "w").write("{}")
    def bad(p):
        open(p, "wb").write(b"half")
        raise BuildError("계획 밖 섹터 변경")
    with pytest.raises(BuildError):
        publish(out, bad, lambda: {})
    assert sorted(x.name for x in tmp_path.iterdir()) == []


def test_merge_writers_rejects_two_writers_for_one_string():
    """기본 이름·화면 글자·음절표가 쓰는 문자열을 실행 파일 번역이 또 쓰면 실패(덮어쓰기 순서에 맡기지 않음)."""
    assert merge_writers({"ELF#1": "가"}, {"ELF#2": "나"}, set()) == {"ELF#1": "가", "ELF#2": "나"}
    with pytest.raises(BuildError):
        merge_writers({"ELF#1": "가"}, {"ELF#1": "나"}, set())
    with pytest.raises(BuildError):
        merge_writers({"ELF#3": "가"}, {}, {"ELF#3"})


def test_encode_ui_passes_format_tokens_through():
    enc = lambda t: t.encode("cp932") if t else b""
    assert encode_ui("%c%c슬픔%s", lambda t: b"K" * len(t)) == b"%c%cKK%s"
    assert encode_ui("ＨＰ：%d", enc) == "ＨＰ：".encode("cp932") + b"%d"


def test_data_layout_widens_spaces_in_wrapped_quest_text():
    """퀘스트 설명은 게임이 2바이트 단위로 자동 줄바꿈 → 반각 공백(1바이트)이 글자를 반으로 가름."""
    t = {"RECORD#000.desc": "기억을 더듬어", "RECORD#000.title": "시련의 시작", "ITEM#000.desc": "사용하면 회복"}
    out = data_layout(t)
    assert out["RECORD#000.desc"] == "기억을　더듬어"
    assert out["RECORD#000.title"] == "시련의 시작" and out["ITEM#000.desc"] == "사용하면 회복"


def test_data_layout_keeps_words_whole_in_10_cell_lines():
    """설명 칸은 10칸마다 자동 줄바꿈 → 단어가 줄 끝에서 잘리지 않게 줄 끝을 전각 공백으로 채움."""
    s = "영체와 실체로 갈라져 버린 원인은？ 기억을 더듬어"
    out = data_layout({"RECORD#000.desc": s})["RECORD#000.desc"]
    lines = [out[i:i + 10] for i in range(0, len(out), 10)]
    assert [l.strip("　") for l in lines] == ["영체와　실체로", "갈라져　버린", "원인은？　기억을", "더듬어"]


def test_data_layout_fails_when_quest_text_needs_more_than_9_lines():
    with pytest.raises(BuildError):
        data_layout({"RECORD#000.desc": " ".join(["가나다라마바사"] * 10)})


def test_data_layout_does_not_break_inside_brackets():
    out = data_layout({"RECORD#000.desc": "열쇠인 【석판 조각】을 찾아"})["RECORD#000.desc"]
    assert [out[i:i + 10].strip("　") for i in range(0, len(out), 10)] == ["열쇠인", "【석판　조각】을", "찾아"]


def _lines(s):
    out = data_layout({"RECORD#000.desc": s})["RECORD#000.desc"]
    return [out[i:i + 10] for i in range(0, len(out), 10)]


def test_data_layout_splits_long_bracket_group_at_inner_space():
    """【】 묶음 + 조사가 10칸을 넘으면 묶음 안 공백에서 나눈다(뒤 줄이 어긋나지 않게)."""
    assert [l.strip("　") for l in _lines("집 나간 【귀가 긴 고양이】를 찾고 있다")] == \
        ["집　나간　【귀가　긴", "고양이】를　찾고", "있다"]


def test_data_layout_keeps_alignment_after_overlong_word():
    """공백 없는 11칸 단어 뒤에도 각 줄은 단어로 시작한다."""
    lines = _lines("가나다라마바사아자차카 타파")
    assert lines[1].startswith("카") and lines[2].startswith("타파")


@pytest.mark.parametrize("bad", ["【가나 다라", "가나】 다라", " 가나", "가나 ", "가나  다라"])
def test_data_layout_rejects_bad_brackets_and_spaces(bad):
    with pytest.raises(BuildError):
        data_layout({"RECORD#000.desc": bad})


def test_merge_writers_rejects_fixed_overlapping_grid():
    with pytest.raises(BuildError):
        merge_writers({}, {"ELF#5": "가"}, {"ELF#5"})


def test_apply_gfx_redraws_sheet_from_label_rows():
    import os
    from tools.build import GFX, apply_gfx
    from tools.gfx_label import FONTS
    sheet = os.path.join(os.path.dirname(__file__), "..", "work/ex/DATAIMG/STSWIN00.GTM")
    if not os.path.exists(sheet) or not all(os.path.exists(p) for p, _ in FONTS.values()):
        import pytest
        pytest.skip("추출 파일 없음")
    raw = open(sheet, "rb").read()
    assert set(GFX) == {"/DATAIMG/STSWIN00.GTM"}
    out = apply_gfx(lambda p: raw)
    assert set(out) == {"/DATAIMG/STSWIN00.GTM"}
    assert len(out["/DATAIMG/STSWIN00.GTM"]) == len(raw) and out["/DATAIMG/STSWIN00.GTM"] != raw
