"""PoC4: 데이터 파일 7종과 실행 파일 문자열을 바꿔 다음을 확인한다.
  1. 커진 데이터 파일(레코드 재배치)을 게임이 읽는가 — 아이템·소지품·마법·퀘스트 기록 앞에 「＊」
  2. 실행 파일 문자열 제자리 수정과 재배치(참조 수정)가 표시되는가
  3. 무기 필살기·소환수 이름이 데이터 파일과 실행 파일 중 어느 쪽에서 오는가
     데이터 파일 쪽 = 「デ」로 시작, 실행 파일 쪽 = 「実１」(첫 표)·「実２」(둘째 표)
폰트는 원본(일본어 표지만 사용)."""
import json
import sys

from tools import cdimage
from tools.data_text import PATHS, apply_texts, extract_all
from tools.discbuild import build
from tools.elf_text import ElfText, layout_from_elf
from tools.font import Font
from tools.sl00 import decompress
from tools.textcodec import encode_sjis

ELF = "/SCPS_110.07"
FONT = "/DATAIMG/FONT/FONT.BIN"


def data_texts(rows):
    t = {}
    for r in rows:
        key, field = r["id"].split("#")[0], r["id"].rsplit(".", 1)[1]
        if key == "WEAPON" and field == "skill":
            t[r["id"]] = "デ" + r["src"]
        elif key == "AMULET" and field == "summon":
            t[r["id"]] = "デ" + r["src"][:6]          # 0번 레코드는 고정 용량 15바이트
        elif key == "EST":
            t[r["id"]] = ("敵" + r["src"])[:15]
        elif key in ("ITEM", "INVENT", "MAGIC", "RECORD"):
            t[r["id"]] = "＊" + r["src"]
    return t


def elf_texts(rows):
    t = {}
    for r in rows:
        va = int(r["id"][4:], 16)
        if 0x256500 <= va <= 0x256570:
            t[r["id"]] = "実１" + r["src"][:3]
        elif 0x2569C0 <= va <= 0x256A30:
            t[r["id"]] = "実２" + r["src"][:3]
        elif 0x256E08 <= va <= 0x257008:
            t[r["id"]] = "実" + r["src"][:5]
    t["ELF#250290"] = "　ＰＯＣ４スロット１のカードを"            # 제자리
    t["ELF#2502c0"] = "　ＰＯＣ４移動チェックしています"  # 재배치
    t["ELF#2503b8"] = "\u3000ＰＯＣ４スロット１のカードに"              # 제자리(계속 표시되는 줄)
    t["ELF#2503e8"] = "\u3000ＰＯＣ４「つぐない」のデータなし"              # 제자리
    t["ELF#250418"] = "\u3000ＰＵＳＨ\u3000ＡＮＹ\u3000ＢＵＴＴＯＮ\u3000ＰＯＣ４移動"  # 재배치(용량 39 초과)
    t["ELF#249fd0"] = "レイア"                                        # 기본 이름 후보 1
    t["ELF#24c880"] = "レイカ"                                        # 기본 이름 후보 2
    t["ELF#25d008"] = "レイタ"                                        # 기본 이름 후보 3(이름 표)
    t["ELF#25cff8"] = "ミミ１"                                        # 이름 표 첫 칸
    t["ELF#2565c0"] = "たたかうＰＯＣ４移動"                          # 재배치(전투 명령)
    t["ELF#2509a0"] = "オプション４"                                   # 제자리
    return t


def main(src, out):
    img = cdimage.Image(src)
    by = {f.path: f for f in img.list_files()}
    files = {p: img.read_file(by[p]) for p in PATHS.values()}
    rep = apply_texts(files, data_texts(extract_all(files)), encode_sjis)
    elf = img.read_file(by[ELF])
    codes = Font.parse(decompress(img.read_file(by[FONT]))).codes
    et = ElfText.parse(elf, layout_from_elf(elf), codes)
    rep[ELF] = et.apply(elf_texts(et.rows()), encode_sjis)
    for p, b in sorted(rep.items()):
        old = files.get(p, elf)
        print(p, len(old), "->", len(b))
    r = build(src, rep, out)
    print("재배치:", r.relocated)
    json.dump({"elf": elf_texts(et.rows())}, open(out + ".texts.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:3])
