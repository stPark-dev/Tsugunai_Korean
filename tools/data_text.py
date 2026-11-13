"""데이터 파일 텍스트 추출과 적용.

ID = "<묶음>#<레코드 3자리>.<필드>"   예: ITEM#000.name, RECORD#012.desc
     EST 는 "EST#<슬롯 3자리>-<그룹 내 순번>.name"  (슬롯 = 몬스터 번호)
빈 문자열은 추출하지 않는다.
"""
import json
import sys

from tools.datafile import SPECS, EstFile, RecordFile, TableFile
from tools.textcodec import decode_sjis

PATHS = {
    "ITEM": "/DATAIMG/ITEM/ITEM.DAT",
    "INVENT": "/DATAIMG/INVENT/INVENT.DAT",
    "WEAPON": "/DATAIMG/WEAPON/WEAPON.DAT",
    "MAGIC": "/DATAIMG/MAGIC/MAGIC.DAT",
    "AMULET": "/DATAIMG/AMULET/AMULET.DAT",
    "RECORD": "/DATAIMG/INVENT/RECORD.DAT",
    "EST": "/DATAIMG/BATTLE/EST.BIN",
}
FIELDS = {
    "ITEM": ("name", "desc"),
    "INVENT": ("name", "desc"),
    "WEAPON": ("name", "skill", "desc"),
    "MAGIC": ("desc",),
    "AMULET": ("name", "summon"),
    "RECORD": ("title", "desc"),
}


class DataTextError(ValueError):
    pass


def _load(key, raw):
    if key == "EST":
        return EstFile.parse(raw)
    if key == "RECORD":
        return RecordFile.parse(raw)
    return TableFile.parse(raw, SPECS[key])


def _items(key, obj):
    """(ID, 바이트 문자열) 목록."""
    if key == "EST":
        return [(f"EST#{s:03d}-{k}.name", b) for (s, k), b in obj.names()]
    names = FIELDS[key]
    if key == "RECORD":
        flat = obj.fields
    else:
        flat = [b for r in obj.records for b in r.fields]
    return [(f"{key}#{i // len(names):03d}.{names[i % len(names)]}", b) for i, b in enumerate(flat)]


def extract_all(files: dict):
    rows = []
    for key, path in PATHS.items():
        for rid, b in _items(key, _load(key, files[path])):
            if b:
                rows.append({"id": rid, "src": decode_sjis(b)})
    return rows


def _set(key, obj, rid, data):
    _, _, rest = rid.partition("#")
    rec, _, fname = rest.partition(".")
    if key == "EST":
        slot, _, k = rec.partition("-")
        if fname != "name" or not (slot.isdigit() and k.isdigit()):
            raise DataTextError(f"잘못된 ID {rid}")
        if (int(slot), int(k)) not in obj.pos:
            raise DataTextError(f"범위 밖 ID {rid}")
        obj.set_name((int(slot), int(k)), data)
        return
    names = FIELDS[key]
    if fname not in names or not rec.isdigit():
        raise DataTextError(f"잘못된 ID {rid}")
    i, j = int(rec), names.index(fname)
    if key == "RECORD":
        if 2 * i + j >= len(obj.fields):
            raise DataTextError(f"범위 밖 ID {rid}")
        obj.fields[2 * i + j] = data
    else:
        if i >= len(obj.records):
            raise DataTextError(f"범위 밖 ID {rid}")
        obj.records[i].fields[j] = data


def apply_texts(files: dict, texts: dict, encoder):
    """texts: ID → 문자열. 바뀐 파일만 {path: bytes}로 돌려준다."""
    want = {}
    for rid, s in texts.items():
        key = rid.partition("#")[0]
        if key not in PATHS:
            raise DataTextError(f"알 수 없는 ID {rid}")
        want.setdefault(key, {})[rid] = s
    out = {}
    for key, items in want.items():
        raw = files[PATHS[key]]
        obj = _load(key, raw)
        cur = dict(_items(key, obj))
        for rid, s in items.items():
            data = encoder(s)
            if rid in cur and cur[rid] == data:
                continue
            _set(key, obj, rid, data)
        new = obj.to_bytes()
        if new != raw:
            out[PATHS[key]] = new
    return out


def main(ex_dir, out_path):
    files = {p: open(ex_dir + p, "rb").read() for p in PATHS.values()}
    rows = extract_all(files)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(len(rows), "rows ->", out_path)


if __name__ == "__main__":
    main(*sys.argv[1:3])
