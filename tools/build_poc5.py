"""PoC5: 이름 뒤 조사 훅(D8)을 실제 게임에서 확인한다.

- MQ00 번역 전체(text/ko/MQ00.jsonl)를 넣고, 쓰인 한글 음절을 한자 슬롯에 받침 있는 것부터 배정·렌더링.
- 실행 파일: 조사 훅(tools/josa_hook.py) + 주인공 기본 이름(기본 「레온」, 셋째 인수로 바꿈. 예: 레이스).
- 확인할 줄: M00_21#026 「{n:01}{j:이었/였}던가．」
    기본 이름 레온 → 「레온이었던가．」, 가나로 이름을 넣으면(한글 아님) → 「…였던가．」
"""
import glob
import json
import sys

from tools import cdimage
from tools.discbuild import build
from tools.elf_text import ElfText, layout_from_elf
from tools.font import Font, render_alpha
from tools.hangul import allocate, encode, is_hangul, josa_pairs, josa_table, kanji_slots
from tools.josa_hook import apply as apply_hook, build as build_hook
from tools.scp_text import apply_texts
from tools.sl00 import compress, decompress

ELF = "/SCPS_110.07"
FONT = "/DATAIMG/FONT/FONT.BIN"
HERO = {"ELF#25d008": "레온"}          # 이름 표 0x238070[0] 이 가리키는 기본 이름(용량 3자)


def _rows(path):
    return [json.loads(l) for l in open(path, encoding="utf-8")]


def main(src, out, hero="레온"):
    HERO["ELF#25d008"] = hero
    img = cdimage.Image(src)
    by = {f.path: f for f in img.list_files()}
    mq00 = [r for r in _rows("text/ko/MQ00.jsonl") if r["state"] != "untranslated"]
    every = [r["ko"] for p in sorted(glob.glob("text/ko/*.jsonl")) for r in _rows(p)
             if r["state"] != "untranslated"]
    pairs = josa_pairs(every)
    used = {c for r in mq00 for c in r["ko"] if is_hangul(c)}
    used |= {c for s in HERO.values() for c in s} | {c for p in pairs for x in p for c in x}

    font = Font.parse(decompress(img.read_file(by[FONT])))
    a = allocate(used, kanji_slots(font.codes))
    for ch, code in a.cmap.items():
        font.set_glyph_alpha(font.index(code), render_alpha(ch, font.width, font.height))
    enc = lambda s: encode(s, a.cmap, pairs)

    scps = {p: img.read_file(f) for p, f in by.items() if p.startswith("/DATAIMG/MQ00/SCP/")}
    rep = apply_texts(scps, {r["id"]: r["ko"] for r in mq00}, enc)

    elf = img.read_file(by[ELF])
    lay = layout_from_elf(elf)
    et = ElfText.parse(elf, lay, font.codes)
    elf = bytearray(et.apply(HERO, enc))
    apply_hook(elf, lay.delta, build_hook(a.lo, a.split, josa_table(pairs, a.cmap)))

    rep[ELF] = bytes(elf)
    rep[FONT] = compress(font.to_bytes())
    r = build(src, rep, out)
    print("한글", len(a.cmap), "음절 / 받침 범위", hex(a.lo), hex(a.split), "/ 조사 쌍", len(pairs))
    print("바뀐 파일", len(rep), "재배치:", r.relocated)


if __name__ == "__main__":
    main(*sys.argv[1:4])
