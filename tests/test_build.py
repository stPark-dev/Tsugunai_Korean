"""제품 빌드(tools/build.py) 검사 함수 테스트."""
import hashlib

import pytest

from tools.build import (BuildError, NAME_IDS, default_names, publish, reject_reassigned,
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
