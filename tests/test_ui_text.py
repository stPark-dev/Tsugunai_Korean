"""실행 파일·데이터 파일 번역(text/ko_ui/*.jsonl) 검사 테스트."""
import pytest

from tools.ui_text import UiTextError, cells, check, field_of, from_glossary, limits

SRC = [{"id": "ELF#000010", "src": "セーブしますか"},
       {"id": "ELF#000020", "src": "レベル：%d　経験値：%d"},
       {"id": "ITEM#000.name", "src": "回復薬"},
       {"id": "ITEM#001.name", "src": "赤い羽の帽子"},
       {"id": "ITEM#000.desc", "src": "つかうと回復"}]


def _r(rid, ko, state="reviewed"):
    s = {r["id"]: r["src"] for r in SRC}[rid]
    return {"id": rid, "src": s, "ko": ko, "state": state}


def test_field_and_limits():
    assert field_of("ITEM#012.name") == "ITEM.name" and field_of("ELF#2509a0") == "ELF#2509a0"
    lim = limits(SRC)
    assert lim["ELF#000010"] == 7                 # 실행 파일: 그 문자열의 원래 폭
    assert lim["ITEM#000.name"] == 6              # 데이터: 같은 필드에서 가장 긴 원문 폭


def test_cells_ignores_format_tokens():
    assert cells("레벨：%d　경험치：%d") == 8


def test_valid_rows_pass():
    check([_r("ELF#000010", "저장할까요"), _r("ELF#000020", "레벨：%d　경험치：%d"),
           _r("ITEM#000.name", "회복약"), _r("ITEM#000.desc", "", "untranslated")], SRC)


@pytest.mark.parametrize("row", [
    _r("ELF#000010", "저장하시겠습니까？？"),             # 폭 초과
    _r("ELF#000020", "레벨：%d　경험치"),                  # 서식 토큰 빠짐
    _r("ELF#000020", "경험치：%d　레벨：%s"),              # 서식 토큰 바뀜
    _r("ITEM#000.name", "HP약"),                           # 반각 영문
    _r("ITEM#000.name", "회복·약"),                        # 인코딩 불가(U+00B7)
    _r("ITEM#000.name", "", "reviewed"),                   # 번역 없음
    _r("ITEM#000.name", "회복약", "done"),                 # 상태
    {"id": "ITEM#000.name", "src": "回復", "ko": "회복", "state": "reviewed"},   # 보호 원문
    {"id": "ITEM#099.name", "src": "回復", "ko": "회복", "state": "reviewed"},   # 없는 ID
])
def test_invalid_rows_fail(row):
    with pytest.raises(UiTextError):
        check([row], SRC)


def test_duplicate_id_fails():
    with pytest.raises(UiTextError):
        check([_r("ITEM#000.name", "회복약")] * 2, SRC)


def test_from_glossary_fills_exact_matches():
    gl = [{"id": "G0100", "ja": "回復薬", "ko": "회복약", "cat": "item"}]
    rows = from_glossary(SRC, gl)
    by = {r["id"]: r for r in rows}
    assert by["ITEM#000.name"]["ko"] == "회복약" and "G0100" in by["ITEM#000.name"]["note"]
    assert by["ITEM#001.name"]["state"] == "untranslated" and len(rows) == len(SRC)


def test_automap_name_widened_to_glossary_width():
    # 나가기 확인 창은 글자 폭만큼 늘어나므로(0x1b3bcc) 원문 3칸이 아닌 4칸까지.
    src = [{"id": "AUTOMAP#000.name", "src": "赤の門"}]
    assert limits(src) == {"AUTOMAP#000.name": 4}
    check([{"id": "AUTOMAP#000.name", "src": "赤の門", "ko": "붉은 문", "state": "reviewed"}], src)
    with pytest.raises(UiTextError):
        check([{"id": "AUTOMAP#000.name", "src": "赤の門", "ko": "붉은 큰문", "state": "reviewed"}], src)
