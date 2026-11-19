"""실행 파일·데이터 파일 번역 파일(text/ko_ui/ELF.jsonl, text/ko_ui/DATA.jsonl) 기계 검사.

한 줄 = {id, src, ko, state, note?}. id·src 는 text/elf_src.jsonl·text/data_src.jsonl 과 같아야 한다.
상태는 대사와 같음(tools/translation.py STATES). untranslated = 원문 바이트 그대로.
검사
  서식 토큰(%d %s %c …)은 원문과 같은 순서·개수.
  반각 문자는 서식 토큰과 반각 공백만(반각 영숫자는 대사 경로에서 안 그려짐, 같은 글꼴).
  한글 음절 또는 전각 Shift-JIS 만.
  폭(칸 = 서식 토큰을 뺀 글자 수): 실행 파일 = 그 문자열의 원래 폭 이하(자리가 원래 길이에 맞춰 있음),
    데이터 = 같은 필드(ITEM.name 등)에서 가장 긴 원문 폭 이하(화면이 가장 긴 원문을 담아야 하므로).
    예외(WIDENED): 그리는 곳이 글자 폭만큼 늘어나는 필드는 근거와 함께 따로 정한 폭.
  바이트 용량(실행 파일 제자리·재배치, 몬스터 이름 15바이트 등)은 적용 도구가 빌드 때 막는다.
"""
import json
import re
import sys

from tools.hangul import is_hangul, sjis_bytes
from tools.translation import STATES

FMT_RE = re.compile(r"%[-0-9]*[a-z]")

# 필드 → 폭. AUTOMAP.name(자동 생성 던전 이름)은 「%s 나갑니까？」 창(창 오른쪽 끝 = 글 끝까지 늘림, 0x1b3bcc)과
# 세이브 장소에 쓰인다. 원문 3칸 대신 용어집 이름(붉은 문 등 4칸)까지. 바이트 칸(0x20)은 datafile 이 막음.
WIDENED = {"AUTOMAP.name": 4}


class UiTextError(ValueError):
    pass


def field_of(rid):
    if rid.startswith("ELF#"):
        return rid
    key, _, rest = rid.partition("#")
    return f"{key}.{rest.rpartition('.')[2]}"


def cells(s):
    return len(FMT_RE.sub("", s))


def limits(src_rows):
    by_field = {}
    for r in src_rows:
        f = field_of(r["id"])
        by_field[f] = max(by_field.get(f, WIDENED.get(f, 0)), cells(r["src"]))
    return {r["id"]: by_field[field_of(r["id"])] for r in src_rows}


def _check_row(r, src, lim):
    rid = r["id"]
    if rid not in src:
        raise UiTextError(f"{rid}: 원문에 없는 ID")
    if r["src"] != src[rid]:
        raise UiTextError(f"{rid}: 보호 필드 src 가 추출본과 다름")
    if r.get("state") not in STATES:
        raise UiTextError(f"{rid}: 상태 {r.get('state')}")
    if r["state"] == "untranslated":
        return
    ko = r.get("ko", "")
    if not ko:
        raise UiTextError(f"{rid}: 번역 없음")
    if FMT_RE.findall(ko) != FMT_RE.findall(r["src"]):
        raise UiTextError(f"{rid}: 서식 토큰 불일치")
    rest = FMT_RE.sub("", ko)
    if re.search(r"[\x21-\x7e]", rest):
        raise UiTextError(f"{rid}: 반각 영숫자·기호")
    bad = sorted({c for c in rest if not (is_hangul(c) or sjis_bytes(c))})
    if bad:
        raise UiTextError(f"{rid}: 인코딩할 수 없는 글자 {''.join(bad)!r}")
    if cells(ko) > lim[rid]:
        raise UiTextError(f"{rid}: 폭 {cells(ko)}칸 > {lim[rid]}칸")


def check(rows, src_rows):
    src = {r["id"]: r["src"] for r in src_rows}
    lim = limits(src_rows)
    seen = set()
    for r in rows:
        if r["id"] in seen:
            raise UiTextError(f"{r['id']}: 중복")
        seen.add(r["id"])
        _check_row(r, src, lim)


def from_glossary(src_rows, glossary):
    """원문이 용어집 표제어와 똑같은 줄은 그 번역으로, 나머지는 untranslated 로 채운 초기 행."""
    gl = {}
    for g in glossary:
        gl.setdefault(g["ja"], g)
    out = []
    for r in src_rows:
        g = gl.get(r["src"])
        if g and g["ko"]:
            out.append({"id": r["id"], "src": r["src"], "ko": g["ko"], "state": "reviewed",
                        "note": f"용어집 {g['id']}"})
        else:
            out.append({"id": r["id"], "src": r["src"], "ko": "", "state": "untranslated"})
    return out


def _jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def main(ko_path, src_path):
    rows, src = _jsonl(ko_path), _jsonl(src_path)
    check(rows, src)
    done = sum(r["state"] != "untranslated" for r in rows)
    print(f"{ko_path}: {len(rows)}줄, 번역 {done}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
