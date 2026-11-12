"""PoC3: 대사 줄 폭 상한 측정. M00_25 앞 페이지들에 전각 25/26/27자 줄과 반각 문자 줄을 넣는다."""
import sys

from tools import cdimage
from tools.discbuild import build
from tools.scp import Script

PATH = "/DATAIMG/MQ00/SCP/M00_25.SCP"
D = "１２３４５６７８９０"
LINES = {
    1: D * 2 + D[:5],                  # 25
    3: D * 2 + D[:6],                  # 26
    4: "ABCDEFGHIJ0123456789abcdefghij",  # 반각 30
    6: D * 2 + D[:7],                  # 27
    7: "Ａ Ａ　Ａ" + "|" + "AAAA" + "|",   # 반각/전각 공백, 반각 4 = 전각 2?
}


def main(src, out):
    img = cdimage.Image(src)
    by = {f.path: f for f in img.list_files()}
    s = Script.parse(img.read_file(by[PATH]))
    t = s.texts()
    for i, txt in LINES.items():
        assert t[i].op == 0x39
        t[i].set_text(txt.encode("cp932"))
    build(src, {PATH: s.to_bytes()}, out)


if __name__ == "__main__":
    main(*sys.argv[1:3])
