"""제품 빌드: 원본 이미지 + 번역·글꼴·훅을 한 번에 넣은 이미지와 매니페스트를 만든다.

  python3 -m tools.build orig/tsugunai.bin build/tsugunai_ko.bin

입력 정책: 개발/PoC(현재 유일). 상태가 untranslated 가 아닌 대사 줄을 모두 넣고, 나머지는 원문 바이트 그대로.
결과물에는 배포 금지 표지(매니페스트 distribution=false)를 단다. 실패(산출물 없음):
  원본 SHA1 불일치, 번역 기계 검사(tools/translation.py), 한글 음절 > 한자 슬롯, 배정 안 된 글자,
  조사 3자 초과, 실행 파일 문자열 용량·참조, 디스크 계획 밖 섹터 변경.
번역문·이름·화면 글자·음절표에 한글에 내준 슬롯의 한자가 있어도 실패(다른 음절로 보이므로).
산출물은 임시 파일로 만든 뒤 모두 성공해야 이름을 바꾼다. 실패하면 이전 산출물도 지워 둔다.
남긴 원문 중 한글에 슬롯을 내준 한자를 쓰는 줄은 매니페스트 stale_kanji 에 기록(개발 정책의 알려진 한계).
  범위는 추출본(text/*_src.jsonl: 대사 전부, 디버그 아닌 실행 파일 문자열, 데이터 파일)뿐이라 하한값이다.
"""
import glob
import pathlib
import hashlib
import json
import os
import sys

from tools import cdimage, name_grid
from tools.discbuild import build
from tools.elf_text import ElfText, layout_from_elf
from tools.font import Font, put_hangul, sjis_code
from tools.hangul import allocate, encode, is_hangul, josa_pairs, josa_table, kanji_slots
from tools.josa_hook import apply as apply_hook, build as build_hook
from tools.scp_text import apply_texts
from tools.sl00 import compress, decompress
from tools.translation import check, load_dir

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEXT = ROOT / "text"

SOURCE_SHA1 = "72f131160b40ff309ebf06ac501bf65971da4da6"      # docs/survey.md, SCPS-11007
ELF = "/SCPS_110.07"
FONT = "/DATAIMG/FONT/FONT.BIN"
# 기본 이름 포인터 표 0x238070 순서 = 이름 변수 {n:01}–{n:07}
NAME_IDS = ("ELF#25d008", "ELF#251aa8", "ELF#251a98", "ELF#251a88", "ELF#251a78",
            "ELF#25d000", "ELF#25cff8")
NAME_JA = ("レイス", "イフェム", "ラフルク", "フィセラ", "アシュゴ", "ナビ", "ミミー")
LABELS = {"ELF#2542c0": "이름 입력", "ELF#2542b0": "한글１", "ELF#2542a0": "한글２",
          "ELF#254290": "영문・숫자", "ELF#254280": "기본 이름", "ELF#25d2c8": "결정",
          "ELF#25d2d0": "뒤로", "ELF#25d2d8": "앞으로"}          # 이름 입력 화면(D9)


class BuildError(RuntimeError):
    pass


def verify_source(path, sha1):
    got = _sha1_file(path)
    if got != sha1:
        raise BuildError(f"지원하지 않는 원본 이미지(SHA1 {got})")


def selected_texts(rows):
    return {r["id"]: r["ko"] for r in rows if r["state"] != "untranslated"}


def default_names(glossary):
    ko = {g["ja"]: g["ko"] for g in glossary if g["cat"] == "char"}
    missing = [ja for ja in NAME_JA if ja not in ko]
    if missing:
        raise BuildError(f"용어집에 기본 이름 없음: {missing}")
    return {rid: ko[ja] for rid, ja in zip(NAME_IDS, NAME_JA)}


def stale_kanji(rows, used_codes, translated):
    """원문 그대로 남는 줄 중 한글에 내준 슬롯의 글자를 쓰는 줄 → {id: 그 글자들}."""
    out = {}
    for r in rows:
        if r["id"] in translated:
            continue
        bad = "".join(dict.fromkeys(c for c in r["src"] if _code(c) in used_codes))
        if bad:
            out[r["id"]] = bad
    return out


def reject_reassigned(strings, used_codes):
    """넣을 문자열(id → 문자열)에 한글에 내준 슬롯의 글자가 있으면 실패."""
    for rid, s in strings.items():
        bad = "".join(dict.fromkeys(c for c in s if not is_hangul(c) and _code(c) in used_codes))
        if bad:
            raise BuildError(f"{rid}: 한글에 내준 한자 슬롯의 글자 {bad!r}")


def publish(out, write_image, make_manifest):
    """이전 산출물을 지우고 임시 파일에 이미지·매니페스트를 쓴 뒤, 모두 성공하면 이름을 바꾼다."""
    man = out + ".manifest.json"
    tmp, mtmp = out + ".tmp", man + ".tmp"
    for p in (out, man, tmp, mtmp):
        if os.path.exists(p):
            os.remove(p)
    try:
        write_image(tmp)
        with open(mtmp, "w", encoding="utf-8") as f:
            json.dump({**make_manifest(), "output_sha1": _sha1_file(tmp)}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, out)
        os.replace(mtmp, man)
    except BaseException:
        for p in (tmp, mtmp):
            if os.path.exists(p):
                os.remove(p)
        raise


def _code(c):
    try:
        return sjis_code(c)
    except UnicodeEncodeError:
        return None


def _jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main(src, out):
    verify_source(src, SOURCE_SHA1)
    scp_src = {r["id"]: r for r in _jsonl(TEXT / "scp_src.jsonl")}
    rows = load_dir(str(TEXT / "ko"))
    if not rows:
        raise BuildError("번역 파일이 없음")
    warns = check(rows, scp_src)
    texts = selected_texts(rows)
    elf_tr = {**default_names(_jsonl(TEXT / "glossary.jsonl")), **LABELS}
    grid = name_grid.load(TEXT / "name_grid.txt")
    pairs = josa_pairs(texts.values())

    img = cdimage.Image(src)
    by = {f.path: f for f in img.list_files()}
    font = Font.parse(decompress(img.read_file(by[FONT])))
    encoded = {**texts, **elf_tr, **{f"grid#{i}": g for i, g in enumerate(grid)}}
    used = {c for s in encoded.values() for c in s if is_hangul(c)}
    alloc = allocate(used, kanji_slots(font.codes))
    slots = set(alloc.cmap.values())
    reject_reassigned(encoded, slots)
    put_hangul(font, alloc.cmap)
    enc = lambda s: encode(s, alloc.cmap, pairs)

    scps = {p: img.read_file(f) for p, f in by.items() if "/SCP/" in p and p.endswith(".SCP")}
    rep = apply_texts(scps, texts, enc)
    elf = img.read_file(by[ELF])
    lay = layout_from_elf(elf)
    elf = bytearray(ElfText.parse(elf, lay, font.codes).apply(elf_tr, enc))
    name_grid.apply(elf, lay.delta, grid, enc)
    apply_hook(elf, lay.delta, build_hook(alloc.lo, alloc.split, josa_table(pairs, alloc.cmap)))
    rep[ELF] = bytes(elf)
    rep[FONT] = compress(font.to_bytes())

    kept = (list(scp_src.values()) + [r for r in _jsonl(TEXT / "elf_src.jsonl") if not r["debug"]]
            + _jsonl(TEXT / "data_src.jsonl"))
    stale = stale_kanji(kept, slots, set(texts) | set(elf_tr))
    report = {}
    publish(out, lambda p: report.setdefault("r", build(src, rep, p)), lambda: {
        "policy": "development", "distribution": False, "source_sha1": SOURCE_SHA1,
        "translated_lines": len(texts), "untranslated_lines": len(rows) - len(texts),
        "width_warnings": len(warns), "hangul_syllables": len(alloc.cmap),
        "kanji_slots": len(kanji_slots(font.codes)), "josa_pairs": len(pairs),
        "changed_files": len(rep), "relocated": report["r"].relocated,
        "stale_kanji": {"count": len(stale), "lines": stale}})
    with open(out + ".manifest.json", encoding="utf-8") as f:
        m = json.load(f)
    print(json.dumps({k: v for k, v in m.items() if k != "stale_kanji"}, ensure_ascii=False))
    print("원문 그대로 남아 한자가 깨지는 줄:", len(stale))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("사용법: python3 -m tools.build <원본.bin> <출력.bin>")
    try:
        main(*sys.argv[1:3])
    except (BuildError, ValueError, RuntimeError) as e:
        sys.exit(f"빌드 실패: {e}")
