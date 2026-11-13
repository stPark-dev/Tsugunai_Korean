"""용어집(text/glossary.jsonl) 형식 검사와 원문 근거 확인.

한 줄 = 한 결정. 필드
  id     G0000 형식, 고유
  cat    분류(CATS)
  ja     원문 표기(원문 추출물에 실제로 있어야 함)
  ko     채택 번역. state=unresolved 일 때만 비울 수 있음
  na     북미판 표기(참고, 없으면 "")
  state  draft(초안) / approved(검수 끝) / unresolved(미결)
  note   근거·유래·적용 범위 설명
  scope  (선택) 적용 범위. 같은 ja·cat 을 다르게 옮길 때 구분
표기 원칙은 docs/decisions.md D4·D5.
"""
import json
import re
import sys

CATS = {"char", "role", "place", "monster", "summon", "amulet", "item", "equip",
        "skill", "magic", "key", "quest", "term"}
STATES = {"draft", "approved", "unresolved"}
REQUIRED = ("id", "cat", "ja", "ko", "state")
ID_RE = re.compile(r"G\d{4}$")


class GlossaryError(ValueError):
    pass


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def validate(entries):
    ids, keys = set(), set()
    for e in entries:
        miss = [k for k in REQUIRED if k not in e]
        if miss:
            raise GlossaryError(f"{e.get('id')}: 필드 없음 {miss}")
        if not ID_RE.match(e["id"]) or e["id"] in ids:
            raise GlossaryError(f"잘못되거나 중복된 ID {e['id']}")
        if e["cat"] not in CATS or e["state"] not in STATES:
            raise GlossaryError(f"{e['id']}: 분류/상태 {e['cat']}/{e['state']}")
        if not e["ko"] and e["state"] != "unresolved":
            raise GlossaryError(f"{e['id']}: 번역 없음")
        key = (e["cat"], e["ja"], e.get("scope", ""))
        if key in keys:
            raise GlossaryError(f"{e['id']}: 같은 용어·범위 중복 {key}")
        ids.add(e["id"])
        keys.add(key)


def missing_in_sources(entries, texts):
    blob = "\n".join(texts)
    return [e for e in entries if e["ja"] not in blob]


def main(path, *sources):
    entries = load(path)
    validate(entries)
    texts = [json.loads(l)["src"] for s in sources for l in open(s, encoding="utf-8")]
    miss = missing_in_sources(entries, texts)
    for e in miss:
        print("원문에 없음:", e["id"], e["ja"])
    by = {}
    for e in entries:
        by[e["cat"]] = by.get(e["cat"], 0) + 1
    print(len(entries), "항목", dict(sorted(by.items())))
    return 1 if miss else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
