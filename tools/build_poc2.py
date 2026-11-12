"""PoC2: 첫 장면 스크립트(M00_25)의 모든 텍스트를 늘려 레코드 재배치(컨테이너 길이·점프·헤더)를
게임이 받아들이는지, 대사 창 폭이 어떻게 반응하는지 확인한다. 폰트는 원본."""
import sys

from tools import cdimage
from tools.discbuild import build
from tools.scp import Script

PATH = "/DATAIMG/MQ00/SCP/M00_25.SCP"
LONG = "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ１２３４５６７８９０"


def main(src, out):
    img = cdimage.Image(src)
    by = {f.path: f for f in img.list_files()}
    raw = img.read_file(by[PATH])
    s = Script.parse(raw)
    for t in s.texts():
        txt = t.text.decode("cp932")
        if t.op == 0x38:
            txt += "テスト"
        elif txt == "しかし……":
            txt = LONG
        else:
            txt += "ＡＢＣ"
        t.set_text(txt.encode("cp932"))
    new = s.to_bytes()
    rep = build(src, {PATH: new}, out)
    print(PATH, len(raw), "->", len(new), "재배치:", rep.relocated)


if __name__ == "__main__":
    main(*sys.argv[1:3])
