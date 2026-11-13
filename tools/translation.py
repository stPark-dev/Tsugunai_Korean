"""대사 번역 파일(text/ko/MQxx.jsonl) 기계 검사.

한 줄 = {id, src, ko, state, note?}. id·src 는 text/scp_src.jsonl 과 같아야 한다(보호 필드).
상태: untranslated / in_progress / needs_review / reviewed / needs_human_review / distribution_eligible
  reviewed = 독립 검수 반영 끝(D1·D6), 글리프·런타임 확인 대기
토큰
  {c:xx}  색, {n:xx}  이름 변수 — 원문과 같은 묶음(순서는 자유)이어야 한다
  {j:A/B} 이름 변수 바로 뒤 조사(받침 있을 때 A, 없을 때 B). 번역 전용, 빌드 때 푼다
폭(칸): 토큰을 뺀 글자 1개 = 1칸, {n:xx} = 4칸(최장 기본 이름), {j:..} = 1칸.
  대사 줄(op 57)은 max(25, 원문 폭) 초과면 실패, 22 초과면 경고 (docs/poc.md PoC3).
반각 영숫자·기호(0x21–0x7E)는 화면에 안 그려지므로 금지(전각 사용). 반각 공백은 허용.
"""
import glob
import json
import os
import re
import sys
from collections import Counter

STATES = {"untranslated", "in_progress", "needs_review", "reviewed", "needs_human_review",
          "distribution_eligible"}
TOKEN_RE = re.compile(r"\{[cn]:[0-9a-f]{2}\}|\{j:[^/{}]+/[^/{}]+\}")
LINE_OP, HARD, TARGET, NAME_CELLS = 57, 25, 22, 4


class TranslationError(ValueError):
    pass


def tokens(s):
    return TOKEN_RE.findall(s)


def cells(s):
    n = 0
    for t in tokens(s):
        n += NAME_CELLS if t[1] == "n" else 1 if t[1] == "j" else 0
    return n + len(TOKEN_RE.sub("", s))


def _check_row(r, src):
    rid = r["id"]
    if r.get("state") not in STATES:
        raise TranslationError(f"{rid}: 상태 {r.get('state')}")
    if rid not in src:
        raise TranslationError(f"{rid}: 원문에 없는 ID")
    if r["src"] != src[rid]["src"]:
        raise TranslationError(f"{rid}: 보호 필드 src 가 추출본과 다름")
    ko = r.get("ko", "")
    if r["state"] == "untranslated":
        return None
    if not ko:
        raise TranslationError(f"{rid}: 번역 없음")
    if re.search(r"[\x21-\x7e]", TOKEN_RE.sub("", ko)):
        raise TranslationError(f"{rid}: 반각 영숫자·기호 사용(화면에 안 그려짐)")
    ks = [t for t in tokens(ko) if t[1] != "j"]
    if Counter(ks) != Counter(tokens(r["src"])):
        raise TranslationError(f"{rid}: 토큰 불일치 {tokens(r['src'])} / {ks}")
    for m in re.finditer(r"\{j:", ko):
        if not re.search(r"\{n:[0-9a-f]{2}\}$", ko[:m.start()]):
            raise TranslationError(f"{rid}: 조사 토큰이 이름 변수 뒤에 있지 않음")
    if src[rid]["op"] == LINE_OP:
        w = cells(ko)
        if w > max(HARD, cells(r["src"])):
            raise TranslationError(f"{rid}: 폭 {w}칸 초과")
        if w > TARGET:
            return (rid, f"폭 {w}칸(목표 {TARGET})")
    return None


def check(rows, src):
    """실패는 예외, 경고 목록 반환."""
    seen, warns = set(), []
    for r in rows:
        if r["id"] in seen:
            raise TranslationError(f"{r['id']}: 중복")
        seen.add(r["id"])
        w = _check_row(r, src)
        if w:
            warns.append(w)
    return warns


def glossary_hints(rows, src, glossary):
    """원문에 용어가 있는데 번역에 채택 표기가 없는 줄(검토 후보, 실패 아님)."""
    out = []
    terms = sorted((g for g in glossary if g["ko"]), key=lambda g: -len(g["ja"]))
    for r in rows:
        if r["state"] == "untranslated":
            continue
        s = src[r["id"]]["src"]
        for g in terms:
            if g["ja"] in s and g["ko"] not in r["ko"]:
                out.append((r["id"], f"{g['ja']}→{g['ko']}"))
                s = s.replace(g["ja"], "")
    return out


def load_dir(d):
    rows = []
    for p in sorted(glob.glob(os.path.join(d, "*.jsonl"))):
        with open(p, encoding="utf-8") as f:
            rows += [json.loads(l) for l in f if l.strip()]
    return rows


def main(ko_dir, src_path, glossary_path):
    src = {r["id"]: r for r in map(json.loads, open(src_path, encoding="utf-8"))}
    rows = load_dir(ko_dir)
    warns = check(rows, src)
    gl = [json.loads(l) for l in open(glossary_path, encoding="utf-8")]
    for rid, msg in warns + glossary_hints(rows, src, gl):
        print(rid, msg)
    print(len(rows), "줄", dict(Counter(r["state"] for r in rows)))


if __name__ == "__main__":
    main(*sys.argv[1:4])
