"""PoC1: 첫 대사(M00_25 「ルイ僧官 / 何ということでしょう…」)에 쓰인 글자의 글리프를 한글로 바꿔
폰트 경로가 화면까지 이어지는지 확인한다. 텍스트 바이트는 바꾸지 않는다."""
import sys

from tools import cdimage
from tools.discbuild import build
from tools.font import Font, render_alpha, sjis_code
from tools.sl00 import compress, decompress

SWAP = {"ル": "루", "イ": "이", "僧": "승", "官": "관",
        "何": "무", "と": "슨", "い": "일", "う": "이", "こ": "란", "で": "말", "し": "인", "ょ": "가"}
FONT_PATH = "/DATAIMG/FONT/FONT.BIN"


def main(src, out):
    img = cdimage.Image(src)
    by = {f.path: f for f in img.list_files()}
    font = Font.parse(decompress(img.read_file(by[FONT_PATH])))
    for jp, ko in SWAP.items():
        font.set_glyph_alpha(font.index(sjis_code(jp)), render_alpha(ko, font.width, font.height))
    packed = compress(font.to_bytes())
    rep = build(src, {FONT_PATH: packed}, out)
    print("FONT.BIN", len(packed), "B, 재배치:", rep.relocated)


if __name__ == "__main__":
    main(*sys.argv[1:3])
