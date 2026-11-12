"""SCP 텍스트 추출과 적용.

ID = "<MQ디렉터리>/<파일 이름>#<파일 내 텍스트 순번 3자리>"  예: MQ00/M00_25#001
spk = 해당 대사 앞의 가장 가까운 화자 이름(op 0x38) — 번역 참고용
"""
import json
import posixpath
import sys

from tools.scp import Script
from tools.textcodec import decode_sjis


class ScpTextError(ValueError):
    pass


def _stem(path):
    parts = path.strip("/").split("/")  # DATAIMG/MQ00/SCP/M00_25.SCP
    return f"{parts[1]}/{posixpath.splitext(parts[-1])[0]}"


def extract_all(files: dict):
    rows = []
    for path in sorted(files):
        stem = _stem(path)
        spk = None
        for i, t in enumerate(Script.parse(files[path]).texts()):
            src = decode_sjis(t.text)
            if t.op == 0x38:
                spk = src
            elif t.op == 0x14:
                spk = None
            row = {"id": f"{stem}#{i:03d}", "op": t.op, "src": src}
            if t.op == 0x39 and spk:
                row["spk"] = spk
            rows.append(row)
    return rows


def apply_texts(files: dict, texts: dict, encoder):
    """texts: id → 문자열. 바뀐 파일만 {path: bytes}로 돌려준다."""
    by_stem = {_stem(p): p for p in files}
    want = {}
    for rid, s in texts.items():
        stem, _, idx = rid.partition("#")
        if stem not in by_stem or not idx.isdigit():
            raise ScpTextError(f"알 수 없는 ID {rid}")
        want.setdefault(by_stem[stem], {})[int(idx)] = s
    out = {}
    for path, items in want.items():
        raw = files[path]
        sc = Script.parse(raw)
        recs = sc.texts()
        for idx, s in items.items():
            if idx >= len(recs):
                raise ScpTextError(f"범위 밖 ID {path}#{idx}")
            recs[idx].set_text(encoder(s))
        new = sc.to_bytes()
        if new != raw:
            out[path] = new
    return out


def main(ex_dir, out_path):
    import glob
    import os
    files = {"/" + os.path.relpath(fn, ex_dir): open(fn, "rb").read()
             for fn in glob.glob(os.path.join(ex_dir, "DATAIMG/**/SCP/*.SCP"), recursive=True)}
    rows = extract_all(files)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(len(rows), "rows ->", out_path)


if __name__ == "__main__":
    main(*sys.argv[1:3])
