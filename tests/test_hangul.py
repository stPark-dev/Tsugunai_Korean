"""한글 음절 → 폰트 슬롯 배정, 조사 토큰 인코딩 테스트."""
import pytest

from tools.hangul import (JOSA_REC, HangulError, allocate, encode, has_batchim, josa_pairs,
                          josa_table, kanji_slots)

SLOTS = [0x889F, 0x88A0, 0x88A1, 0x88A2, 0x88A3]


def test_has_batchim():
    assert has_batchim("은") and has_batchim("각") and has_batchim("힣")
    assert not has_batchim("나") and not has_batchim("가")
    assert not has_batchim("Ａ") and not has_batchim("ア")      # 한글이 아니면 받침 없음으로 봄


def test_allocate_puts_batchim_syllables_first():
    a = allocate("레이스나각", SLOTS)
    assert set(a.cmap) == set("레이스나각")
    assert a.cmap["각"] == 0x889F                              # 받침 있는 음절이 앞
    assert {a.cmap[c] for c in "레이스나"} == {0x88A0, 0x88A1, 0x88A2, 0x88A3}
    assert a.lo == 0x889F and a.split == 0x88A0
    for c, code in a.cmap.items():                              # 판정 = 비교 한 번
        assert (a.lo <= code < a.split) == has_batchim(c)


def test_allocate_fails_when_too_many_or_not_hangul():
    with pytest.raises(HangulError):
        allocate("가나다라마바", SLOTS)
    with pytest.raises(HangulError):
        allocate("가Ａ", SLOTS)
    with pytest.raises(HangulError):
        allocate("가", [0x8B00])                                 # 둘째 바이트가 Shift-JIS 범위 밖(NUL)


def test_allocate_all_open_syllables():
    a = allocate("가나", SLOTS)
    assert a.split == a.lo                                       # 받침 있는 음절 없음 → 범위 비어 있음


def test_josa_pairs_sorted_unique():
    texts = ["{n:01}{j:은/는} 왔다．", "{n:02}{j:이/가}", "{n:03}{j:은/는}"]
    assert josa_pairs(texts) == [("은", "는"), ("이", "가")]


def test_encode_maps_hangul_tokens_and_josa():
    a = allocate("이가은는다", SLOTS)
    pairs = [("은", "는"), ("이", "가")]
    got = encode("{c:09}{n:01}{j:이/가} 다．", a.cmap, pairs)
    da = a.cmap["다"].to_bytes(2, "big")
    assert got == b"\x01\x09\x02\x01\x03\x02 " + da + "．".encode("cp932")   # 표 번호는 1부터


def test_encode_fails_on_unmapped_or_unknown_josa():
    a = allocate("가", SLOTS)
    with pytest.raises(HangulError):
        encode("나", a.cmap, [])                                 # 배정 안 된 한글 → 빌드 실패
    with pytest.raises(HangulError):
        encode("{n:01}{j:은/는}", a.cmap, [])
    with pytest.raises(HangulError):
        encode("·", a.cmap, [])                                  # Shift-JIS 에 없는 글자


def test_josa_table_fixed_records():
    a = allocate("은는이구먼", SLOTS)
    pairs = [("은", "는"), ("이구먼", "구먼")]
    t = josa_table(pairs, a.cmap)
    assert len(t) == 3 * JOSA_REC                                # 0번 칸은 비워 둠(03 00 = NUL 방지)
    assert t[:JOSA_REC] == b"\0" * JOSA_REC
    c = lambda s: b"".join(a.cmap[x].to_bytes(2, "big") for x in s)
    half = JOSA_REC // 2
    r1, r2 = JOSA_REC, 2 * JOSA_REC
    assert t[r1:r1 + half] == c("은").ljust(half, b"\0")
    assert t[r1 + half:r2] == c("는").ljust(half, b"\0")
    assert t[r2:r2 + half] == c("이구먼").ljust(half, b"\0")
    with pytest.raises(HangulError):
        josa_table([("이구먼이", "구먼")], allocate("이구먼", SLOTS).cmap)   # 3자 넘음


def test_kanji_slots_only_kanji_codes():
    codes = [0x8140, 0x82A0, 0x8393, 0x889F, 0x9FFC, 0xE040, 0xEAA4]   # 공백·가나·한자
    assert kanji_slots(codes) == [0x889F, 0x9FFC, 0xE040, 0xEAA4]


def test_encode_first_pair_has_no_nul():
    a = allocate("과와", SLOTS)
    assert b"\0" not in encode("{n:01}{j:과/와}", a.cmap, [("과", "와")])


def test_encode_rejects_single_byte_kana_and_controls():
    a = allocate("가", SLOTS)
    for bad in ("ｱ", "\t"):                                     # 펼치기 함수가 바이트를 잘못 나눔
        with pytest.raises(HangulError):
            encode(bad, a.cmap, [])
    assert encode("가 가", a.cmap, [])[2:3] == b" "               # 반각 공백은 허용


def test_project_translations_encode():
    """실제 번역 전체: 한자 슬롯 수(1,385) 안에 배정되고, 인코딩에 NUL·오류가 없어야 함."""
    import glob
    import json
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rows = [json.loads(l) for p in sorted(glob.glob(os.path.join(root, "text/ko/*.jsonl")))
            for l in open(p, encoding="utf-8")]
    rows = [r for r in rows if r["state"] != "untranslated"]
    if not rows:
        pytest.skip("번역 없음")
    pairs = josa_pairs(r["ko"] for r in rows)
    chars = {c for r in rows for c in r["ko"] if "가" <= c <= "힣"}
    valid = [c for c in range(0x889F, 0xA000) if 0x40 <= (c & 0xFF) <= 0xFC and c & 0xFF != 0x7F]
    a = allocate(chars, valid[:1385])
    for r in rows:
        assert b"\0" not in encode(r["ko"], a.cmap, pairs), r["id"]
