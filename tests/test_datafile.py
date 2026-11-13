"""데이터 파일(ITEM/INVENT/WEAPON/MAGIC/AMULET/RECORD/EST) 코덱 테스트."""
import os
import struct

import pytest

from tools.datafile import (SPECS, DataFileError, EstFile, RecordFile,
                            TableFile, pad)

EX = os.path.join(os.path.dirname(__file__), "..", "work", "ex", "DATAIMG")


def _table(recs, slots=None, garbage=b"\xcd" * 4):
    """recs: 레코드 바이트 목록 → 오프셋 표 + 레코드. slots > len(recs) 이면 남는 칸은 쓰레기."""
    slots = slots or len(recs)
    pos = slots * 4
    offs = []
    body = b""
    for r in recs:
        offs.append(pos + len(body))
        body += r
    head = b"".join(struct.pack("<I", o) for o in offs) + garbage * (slots - len(recs))
    return head + body


def _item_rec(name, desc, fill=b"\x11" * 0x20):
    n, d = pad(name + b"\0", 4), pad(desc + b"\0", 4)
    return fill + bytes([len(n), len(d)]) + b"\xcc\xcc" + n + d


def test_pad():
    assert pad(b"abc", 4) == b"abc\0" and pad(b"abcd", 4) == b"abcd" and pad(b"ab", 1) == b"ab"


def test_item_parse_and_identity():
    raw = _table([_item_rec(b"AB", b"CDEFG"), _item_rec(b"XYZ", b"Q")], slots=4)
    f = TableFile.parse(raw, SPECS["ITEM"])
    assert len(f.records) == 2
    assert f.records[0].fields == [b"AB", b"CDEFG"]
    assert f.records[1].fields == [b"XYZ", b"Q"]
    assert f.to_bytes() == raw


def test_item_lengthen_relocates_and_updates_lengths():
    raw = _table([_item_rec(b"AB", b"CD"), _item_rec(b"XYZ", b"Q")], slots=3)
    f = TableFile.parse(raw, SPECS["ITEM"])
    f.records[0].fields[1] = b"0123456789"
    new = f.to_bytes()
    g = TableFile.parse(new, SPECS["ITEM"])
    assert g.records[0].fields == [b"AB", b"0123456789"]
    assert g.records[1].fields == [b"XYZ", b"Q"]
    # 고정 머리, 길이 바이트(4 정렬), 쓰레기 표 칸 보존
    o0 = struct.unpack_from("<I", new, 0)[0]
    assert new[o0:o0 + 0x20] == b"\x11" * 0x20
    assert new[o0 + 0x20:o0 + 0x22] == bytes([4, 12])
    assert new[8:12] == b"\xcd" * 4
    # 바뀌지 않은 레코드는 바이트 그대로
    o1 = struct.unpack_from("<I", new, 4)[0]
    assert new[o1:] == _item_rec(b"XYZ", b"Q")


def test_invent_exact_lengths_and_trailing_bytes_kept_when_unchanged():
    def rec(n, d, tail=b""):
        r = bytes([len(n) + 1, len(d) + 1, 0, 0]) + n + b"\0" + d + b"\0" + tail
        return pad(r, 4)
    raw = _table([rec(b"AAA", b"BB", b"F\0"), rec(b"C", b"D")])
    f = TableFile.parse(raw, SPECS["INVENT"])
    assert f.to_bytes() == raw
    f.records[1].fields[0] = b"CCCCC"
    g = TableFile.parse(f.to_bytes(), SPECS["INVENT"])
    assert g.records[1].fields == [b"CCCCC", b"D"]
    o1 = struct.unpack_from("<I", f.to_bytes(), 4)[0]
    assert f.to_bytes()[o1:o1 + 2] == bytes([6, 2])


def test_magic_without_length_bytes():
    def rec(d):
        return pad(b"\x22" * 0x24 + d + b"\0", 4)
    raw = _table([rec(b"abc"), rec(b"defgh")], slots=6)
    f = TableFile.parse(raw, SPECS["MAGIC"])
    assert [r.fields for r in f.records] == [[b"abc"], [b"defgh"]]
    f.records[0].fields[0] = b"abcdefghij"
    g = TableFile.parse(f.to_bytes(), SPECS["MAGIC"])
    assert [r.fields for r in g.records] == [[b"abcdefghij"], [b"defgh"]]


def test_weapon_three_fields():
    def rec(a, b, c):
        a, b, c = pad(a + b"\0", 4), pad(b + b"\0", 4), pad(c + b"\0", 4)
        return b"\x33" * 8 + bytes([len(a), len(b), len(c)]) + b"\xcc" + a + b + c
    raw = _table([rec(b"n", b"skill", b"desc")])
    f = TableFile.parse(raw, SPECS["WEAPON"])
    assert f.records[0].fields == [b"n", b"skill", b"desc"]
    assert f.to_bytes() == raw


def test_bad_length_byte_rejected():
    r = b"\x11" * 0x20 + bytes([2, 4]) + b"\xcc\xcc" + b"AB" + b"CDEF"  # NUL 없음
    with pytest.raises(DataFileError):
        TableFile.parse(_table([r]), SPECS["ITEM"])


def _amulet():
    """첫 레코드 머리가 오프셋 표에 덮인 AMULET 모양(실제 파일과 같은 배치)."""
    def rec(a, b):
        a, b = pad(a + b"\0", 4), pad(b + b"\0", 4)
        return b"\x01\x00\x1e\x00\x14\x04" + bytes([len(a), len(b)]) + a + b
    r1, r2 = rec(b"SECOND", b"S2"), rec(b"THIRD", b"T3")
    first = pad(b"FIRST\0", 4) + pad(b"SUMMON\0", 4)          # 0x0c 부터
    body_start = 0x0c + len(first)
    offs = [0x04, body_start, body_start + len(r1)]          # 0번은 표 안쪽을 가리킨다
    return b"".join(struct.pack("<I", o) for o in offs) + first + r1 + r2


def test_amulet_overlapped_first_record_in_place():
    raw = _amulet()
    f = TableFile.parse(raw, SPECS["AMULET"])
    assert [r.fields for r in f.records] == [[b"FIRST", b"SUMMON"], [b"SECOND", b"S2"], [b"THIRD", b"T3"]]
    assert f.to_bytes() == raw
    f.records[0].fields[0] = b"F1234"           # 용량(8) 안
    f.records[1].fields[0] = b"SECOND-LONGER"
    g = TableFile.parse(f.to_bytes(), SPECS["AMULET"])
    assert [r.fields for r in g.records][:2] == [[b"F1234", b"SUMMON"], [b"SECOND-LONGER", b"S2"]]
    assert f.to_bytes()[:4] == raw[:4]


def test_amulet_overlapped_record_capacity():
    f = TableFile.parse(_amulet(), SPECS["AMULET"])
    f.records[0].fields[0] = b"TOO-LONG-NAME"
    with pytest.raises(DataFileError):
        f.to_bytes()


def test_record_file_packed():
    strs = [b"T1", b"D1", b"T22", b"D22"]
    base = 4 + 8 * 2
    offs, body = [], b""
    for s in strs:
        offs.append(base + len(body))
        body += s + b"\0"
    raw = struct.pack("<I", 2) + b"".join(struct.pack("<I", o) for o in offs) + body
    f = RecordFile.parse(raw)
    assert f.fields == strs
    assert f.to_bytes() == raw
    f.fields[0] = b"TITLE"
    g = RecordFile.parse(f.to_bytes())
    assert g.fields == [b"TITLE", b"D1", b"T22", b"D22"]


def _est():
    def rec(name, i):
        return (name + b"\0").ljust(32, b"\xfd") + bytes([i]) * 52
    tab = [0] * 128
    tab[0] = 512
    tab[3] = 512 + 84 * 2
    body = rec(b"MONA", 1) + rec(b"MONA", 2) + rec(b"MONB", 3)
    return b"".join(struct.pack("<I", o) for o in tab) + body


def test_est_fixed_name_fields():
    raw = _est()
    f = EstFile.parse(raw)
    assert [(k, n) for k, n in f.names()] == [((0, 0), b"MONA"), ((0, 1), b"MONA"), ((3, 0), b"MONB")]
    assert f.to_bytes() == raw
    f.set_name((3, 0), b"X" * 31)
    new = f.to_bytes()
    assert len(new) == len(raw)
    assert EstFile.parse(new).names()[2] == ((3, 0), b"X" * 31)
    assert new[:512 + 84 * 2] == raw[:512 + 84 * 2]
    with pytest.raises(DataFileError):
        f.set_name((0, 0), b"Y" * 32)


REAL = [("ITEM", "ITEM/ITEM.DAT", 168), ("INVENT", "INVENT/INVENT.DAT", 70),
        ("WEAPON", "WEAPON/WEAPON.DAT", 20), ("MAGIC", "MAGIC/MAGIC.DAT", 54),
        ("AMULET", "AMULET/AMULET.DAT", 11)]


@pytest.mark.parametrize("key,path,count", REAL)
def test_real_table_files(key, path, count):
    fn = os.path.join(EX, path)
    if not os.path.exists(fn):
        pytest.skip("추출 파일 없음")
    raw = open(fn, "rb").read()
    f = TableFile.parse(raw, SPECS[key])
    assert len(f.records) == count
    assert f.to_bytes() == raw
    # 전부 다시 쓰기(같은 내용)해도 다시 읽으면 같은 문자열
    for r in f.records:
        r.dirty = True
    g = TableFile.parse(f.to_bytes(), SPECS[key])
    assert [r.fields for r in g.records] == [r.fields for r in f.records]


def test_real_record_and_est():
    rec, est = os.path.join(EX, "INVENT/RECORD.DAT"), os.path.join(EX, "BATTLE/EST.BIN")
    if not (os.path.exists(rec) and os.path.exists(est)):
        pytest.skip("추출 파일 없음")
    r = open(rec, "rb").read()
    assert len(RecordFile.parse(r).fields) == 68 and RecordFile.parse(r).to_bytes() == r
    e = open(est, "rb").read()
    ef = EstFile.parse(e)
    assert len({k[0] for k, _ in ef.names()}) == 69 and ef.to_bytes() == e
