"""대사 번역 작업 묶음(배치) 생성·검사·병합.

같은 원문은 한 번만 번역한다(처음 나온 곳이 TODO, 나머지는 같은 번역을 받음).
이미 번역된 원문(다른 퀘스트 포함)은 known 으로 보여 주기만 한다.
배치 파일 한 줄: id <TAB> op <TAB> 화자 <TAB> 원문 <TAB> TODO 또는 "=기존 번역"
번역 결과(TSV) 한 줄: id <TAB> 번역  (TODO 줄만)

  python -m tools.batch make  MQ21 <출력 폴더> <배치당 TODO 수> [묶음 이름]
      (MQ01,MQ02,... 처럼 여러 퀘스트를 한 묶음으로: 같은 원문은 묶음 전체에서 한 번만)
  python -m tools.batch check <배치 파일> <번역 TSV>
  python -m tools.batch merge MQ21 <배치 폴더> [묶음 이름]  → text/ko/MQ21.jsonl (묶음이면 퀘스트별 파일)
  python -m tools.batch fix   MQ21 <검수 TSV>...    (id <TAB> 번역 <TAB> 이유, fixcheck = 검사만,
                                                   !id = 그 줄만)
"""
import glob
import json
import os
import sys

from tools.translation import TranslationError, check

SRC_PATH = "text/scp_src.jsonl"
KO_DIR = "text/ko"
SPLIT_OPS = (20, 56)            # 배치를 끊어도 되는 줄(장소명·화자 이름)


class BatchError(ValueError):
    pass


def make_batches(rows, known, size, skip=()):
    batches, cur, n, seen, speaker = [], [], 0, set(), ""
    for r in rows:
        if r["id"].startswith(skip):
            continue
        if r["op"] in SPLIT_OPS and n >= size:
            batches.append(cur)
            cur, n = [], 0
        speaker = r["src"] if r["op"] == 56 else "" if r["op"] == 20 else speaker
        todo = r["src"] not in known and r["src"] not in seen
        seen.add(r["src"])
        n += todo
        cur.append({**r, "speaker": speaker if r["op"] != 56 else "", "todo": todo,
                    "known": known.get(r["src"], "")})
    if cur:
        batches.append(cur)
    return batches


def render(batch):
    return "".join(f"{r['id']}\t{r['op']}\t{r['speaker']}\t{r['src']}\t"
                   f"{'TODO' if r['todo'] else '=' + r['known']}\n" for r in batch)


def parse_tsv(text, batch):
    todo = {r["id"]: r["src"] for r in batch if r["todo"]}
    out = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        rid, sep, ko = line.partition("\t")
        if not sep or rid not in todo:
            raise BatchError(f"TODO 가 아닌 줄 또는 형식 오류: {line[:40]}")
        out[todo[rid]] = ko
    return out


def _row(r, ko, state):
    return {"id": r["id"], "src": r["src"], "ko": ko, "state": state}


def row_errors(src2ko, rows, src):
    errs = []
    for r in rows:
        if r["src"] in src2ko:
            try:
                check([_row(r, src2ko[r["src"]], "needs_review")], src)
            except TranslationError as e:
                errs.append((r["id"], str(e)))
    return errs


def expand(rows, src2ko, skip=(), state="needs_review"):
    out = []
    for r in rows:
        if r["id"].startswith(skip):
            out.append({**_row(r, "", "untranslated"), "note": "디버그 스크립트(플레이어에게 안 보임)"})
        elif r["src"] in src2ko:
            out.append(_row(r, src2ko[r["src"]], state))
        else:
            out.append(_row(r, "", "untranslated"))
    return out


def rows_errors(rows, src):
    """줄마다 자기 번역으로 검사(줄 단위 덮어쓰기 뒤에도 쓸 수 있음)."""
    errs = []
    for r in rows:
        try:
            check([r], src)
        except TranslationError as e:
            errs.append((r["id"], str(e)))
    return errs


def apply_fixes(rows, text):
    """검수 결과(id <TAB> 번역 <TAB> 이유)를 적용. 같은 원문의 모든 줄에 퍼뜨린다.
    id 앞에 '!' 를 붙이면 그 줄만 고친다(화자에 따라 같은 원문을 다르게 옮길 때)."""
    by = {r["id"]: r for r in rows}
    fix, one = {}, {}
    for line in text.splitlines():
        if not line.strip():
            continue
        rid, ko = (line.split("\t") + [""])[:2]
        only = rid.startswith("!")
        r = by.get(rid.lstrip("!"))
        if r is None or r["state"] == "untranslated" or not ko:
            raise BatchError(f"적용할 수 없는 검수 줄: {line[:40]}")
        if only:
            one[r["id"]] = ko
        else:
            fix[r["src"]] = ko
    out = [{**r, "ko": fix[r["src"]]} if r["src"] in fix and r["state"] != "untranslated" else r
           for r in rows]
    return [{**r, "ko": one[r["id"]]} if r["id"] in one else r for r in out]


def _load_src():
    return [json.loads(l) for l in open(SRC_PATH, encoding="utf-8")]


def _known(exclude=""):
    k, ex = {}, {q + ".jsonl" for q in exclude.split(",")}
    for p in sorted(glob.glob(os.path.join(KO_DIR, "*.jsonl"))):
        if os.path.basename(p) in ex:
            continue
        for r in map(json.loads, open(p, encoding="utf-8")):
            if r["state"] != "untranslated":
                k.setdefault(r["src"], r["ko"])
    return k


def _quest(rows, q):
    return [r for r in rows if r["id"].startswith(q + "/")]


def _skip(q):
    return (f"{q}/M{q[2:]}_99",)


def group_rows(rows, spec):
    """'MQ01,MQ02' → 그 퀘스트들의 줄을 적은 순서대로."""
    return [r for q in spec.split(",") for r in _quest(rows, q)]


def group_skips(spec):
    return tuple(s for q in spec.split(",") for s in _skip(q))


def _read_batch(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        rid, op, sp, s, tail = line.rstrip("\n").split("\t")
        rows.append({"id": rid, "op": int(op), "speaker": sp, "src": s, "todo": tail == "TODO"})
    return rows


def main(cmd, *a):
    rows = _load_src()
    if cmd == "make":
        q, out, size = a[0], a[1], int(a[2])
        name = a[3] if len(a) > 3 else q
        os.makedirs(out, exist_ok=True)
        bs = make_batches(group_rows(rows, q), _known(q), size, group_skips(q))
        for i, b in enumerate(bs):
            open(os.path.join(out, f"{name}_b{i:02d}.tsv"), "w", encoding="utf-8").write(render(b))
            print(f"{name}_b{i:02d}", len(b), "줄", sum(r["todo"] for r in b), "TODO")
    elif cmd == "check":
        b = _read_batch(a[0])
        got = parse_tsv(open(a[1], encoding="utf-8").read(), b)
        src = {r["id"]: r for r in rows}
        miss = [r["id"] for r in b if r["todo"] and r["src"] not in got]
        for e in row_errors(got, [r for r in b if r["todo"]], src):
            print("오류", *e)
        print("빠진 TODO", len(miss), miss[:10])
    elif cmd == "merge":
        spec, d = a[0], a[1]
        name = a[2] if len(a) > 2 else spec
        src2ko = _known(spec)
        for bp in sorted(glob.glob(os.path.join(d, f"{name}_b??.tsv"))):
            kp = bp[:-4] + ".ko.tsv"
            src2ko.update(parse_tsv(open(kp, encoding="utf-8").read(), _read_batch(bp)))
        for q in spec.split(","):
            out = expand(_quest(rows, q), src2ko, _skip(q))
            check(out, {r["id"]: r for r in rows})
            with open(os.path.join(KO_DIR, q + ".jsonl"), "w", encoding="utf-8") as f:
                f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in out)
            print(q, len(out), "줄", sum(r["state"] != "untranslated" for r in out), "번역")
    elif cmd in ("fix", "fixcheck"):
        q = a[0]                                   # 묶음(MQ01,MQ02)이면 같은 원문을 묶음 전체에서 고침
        qs = q.split(",")
        out = [json.loads(l) for x in qs for l in open(os.path.join(KO_DIR, x + ".jsonl"), encoding="utf-8")]
        for fp in a[1:]:
            out = apply_fixes(out, open(fp, encoding="utf-8").read())
        errs = rows_errors(out, {r["id"]: r for r in rows})
        for e in errs:
            print("오류", *e)
        if cmd == "fix" and not errs:
            for x in qs:
                with open(os.path.join(KO_DIR, x + ".jsonl"), "w", encoding="utf-8") as f:
                    f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in out
                                 if r["id"].startswith(x + "/"))
        print(q, "검수", "적용" if cmd == "fix" and not errs else "검사만", len(a) - 1, "파일, 오류", len(errs))


if __name__ == "__main__":
    main(*sys.argv[1:])
