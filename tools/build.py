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
from tools import data_text, ui_layout, ui_text
from tools.gfx_label import apply_labels
from tools import gfx_card
from tools.gfx_title import apply_title
from tools.psi import Psi
from tools.gtm import Gtm

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEXT = ROOT / "text"
TITLE_PNG = ROOT / "assets" / "title_ko.png"   # G1 타이틀 그림(원본 그림 파생, 커밋 안 함, SHA1 은 gfx_title.TITLE_SHA1)

SOURCE_SHA1 = "72f131160b40ff309ebf06ac501bf65971da4da6"      # docs/survey.md, SCPS-11007
ELF = "/SCPS_110.07"
FONT = "/DATAIMG/FONT/FONT.BIN"
GFX = {"/DATAIMG/STSWIN00.GTM": TEXT / "gfx" / "STSWIN00.jsonl",              # 그림 글자 라벨(D3, G4)
       "/DATAIMG/BTLEFF/SENNTOU0.GTM": TEXT / "gfx" / "SENNTOU0.jsonl",       # G5 전투
       **{f"/DATAIMG/FONT/STAFF{n}.PSI": TEXT / "gfx" / f"STAFF{n}.jsonl" for n in (0, 2, 3)}}  # G3 스태프롤 직함
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


def apply_gfx(read):
    """read(경로) → 원본 바이트. 라벨 행으로 다시 그린 시트만 {경로: 바이트}."""
    out = {}
    for path, rows_path in GFX.items():
        raw = read(path)
        if path.endswith(".PSI"):            # 스태프롤: SL00 압축 8bpp PSI
            p = Psi.parse(decompress(raw))
            if p.bpp != 8:
                raise BuildError(f"{path}: 8bpp PSI 만 라벨을 다시 그릴 수 있음")
            g = Psi(p.header, p.width, p.height, p.bpp, p.clut, bytearray(p.pixels))
            apply_labels(g, _jsonl(rows_path))
            new = compress(bytes(g.to_bytes()))
            changed = bytes(g.pixels) != p.pixels
        else:
            g = Gtm.parse(raw)
            apply_labels(g, _jsonl(rows_path))
            new = g.to_bytes()
            changed = new != raw
        if changed:
            out[path] = new
    return out


def apply_cards(read, data_rows):
    """퀘스트 제목 카드(G2). 번역된 카드만 {경로: SL00 압축 바이트}."""
    rows = _jsonl(TEXT / "gfx" / "TITLE.jsonl")
    gfx_card.check_titles(rows, data_rows)
    gfx_card.check_fonts()
    out = {}
    for r in rows:
        if r["state"] == "untranslated":
            continue
        p = Psi.parse(decompress(read(r["path"])))
        out[r["path"]] = compress(gfx_card.compose(p, r["ko"]).to_bytes())
    return out


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


WRAP_CELLS, WRAP_LINES = 10, 9       # 퀘스트 설명 칸: 10칸마다 자동 줄바꿈, 원문 최장 90자 = 9줄(docs/build.md)


def _words(rid, s):
    """반각 공백으로 단어를 나눈다. 【】 안 공백은 나누지 않되(용어가 두 줄로 갈리지 않게),
    묶음이 한 줄(10칸)을 넘으면 그 안 공백에서 나눈다. 괄호 짝·앞뒤·연속 공백이 틀리면 실패."""
    if s != s.strip(" ") or "  " in s:
        raise BuildError(f"{rid}: 앞뒤 또는 연속 반각 공백")
    words, cur, depth = [], "", 0
    for c in s:
        depth += (c == "【") - (c == "】")
        if depth not in (0, 1):
            raise BuildError(f"{rid}: 【】 짝이 맞지 않음")
        if c == " " and depth == 0:
            words.append(cur)
            cur = ""
        else:
            cur += "　" if c == " " else c
    if depth:
        raise BuildError(f"{rid}: 【】 짝이 맞지 않음")
    words.append(cur)
    return [p for w in words for p in (w.split("　") if len(w) > WRAP_CELLS else [w])]


def _wrap(rid, s):
    """단어가 줄 끝에서 잘리지 않게 줄 끝을 전각 공백으로 채운다(10칸 배수로 — 10칸보다 긴 단어 뒤도 어긋나지 않게)."""
    lines, cur = [], ""
    for w in _words(rid, s):
        cand = f"{cur}　{w}" if cur else w
        if len(cand) <= WRAP_CELLS or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    out = "".join(l.ljust(-(-len(l) // WRAP_CELLS) * WRAP_CELLS, "　") for l in lines[:-1]) + lines[-1]
    n = -(-len(out) // WRAP_CELLS)
    if n > WRAP_LINES:
        raise BuildError(f"{rid}: 퀘스트 설명이 {n}줄(최대 {WRAP_LINES}줄)")
    return out


def data_layout(texts):
    """퀘스트 설명(RECORD#…desc)은 게임이 2바이트 10칸 단위로 자동 줄바꿈 → 넣을 때만 공백을 전각으로 바꾸고 줄 끝을 채움.
    반각 공백(1바이트)은 글자를 반으로 가르므로 남기지 않는다. 번역 파일은 그대로."""
    return {rid: _wrap(rid, s) if rid.startswith("RECORD#") and rid.endswith(".desc") else s
            for rid, s in texts.items()}


def encode_ui(s, enc):
    """실행 파일 문자열: 서식 토큰(%d %s %c …)은 바이트 그대로, 나머지는 enc 로."""
    out, pos = bytearray(), 0
    for m in ui_text.FMT_RE.finditer(s):
        out += enc(s[pos:m.start()]) + m.group().encode("ascii")
        pos = m.end()
    return bytes(out + enc(s[pos:]))


def merge_writers(ui, fixed, reserved):
    """실행 파일 번역(ui)과 다른 단계의 문자열(fixed: 기본 이름·화면 글자, reserved: 음절표)이 겹치면 실패."""
    both = sorted((set(ui) & set(fixed)) | (set(ui) & set(reserved)) | (set(fixed) & set(reserved)))
    if both:
        raise BuildError(f"한 문자열을 두 단계가 씀: {both}")
    return {**ui, **fixed}


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
    elf_src, data_src = _jsonl(TEXT / "elf_src.jsonl"), _jsonl(TEXT / "data_src.jsonl")
    ui_rows = {k: _jsonl(TEXT / "ko_ui" / f"{k}.jsonl") for k in ("ELF", "DATA")}
    ui_text.check(ui_rows["ELF"], elf_src)
    ui_text.check(ui_rows["DATA"], data_src)
    data_tr = data_layout(selected_texts(ui_rows["DATA"]))
    grid = name_grid.load(TEXT / "name_grid.txt")
    pairs = josa_pairs(texts.values())

    img = cdimage.Image(src)
    by = {f.path: f for f in img.list_files()}
    font = Font.parse(decompress(img.read_file(by[FONT])))
    elf = img.read_file(by[ELF])
    lay = layout_from_elf(elf)
    elf_tr = merge_writers(selected_texts(ui_rows["ELF"]),
                           {**default_names(_jsonl(TEXT / "glossary.jsonl")), **LABELS},
                           name_grid.targets(elf, lay.delta))
    encoded = {**texts, **elf_tr, **data_tr, **{f"grid#{i}": g for i, g in enumerate(grid)}}
    used = {c for s in encoded.values() for c in s if is_hangul(c)}
    alloc = allocate(used, kanji_slots(font.codes))
    slots = set(alloc.cmap.values())
    reject_reassigned(encoded, slots)
    put_hangul(font, alloc.cmap)
    enc = lambda s: encode(s, alloc.cmap, pairs)

    scps = {p: img.read_file(f) for p, f in by.items() if "/SCP/" in p and p.endswith(".SCP")}
    rep = apply_texts(scps, texts, enc)
    data_files = {p: img.read_file(by[p]) for p in data_text.PATHS.values()}
    rep.update(data_text.apply_texts(data_files, data_tr, enc))
    elf = bytearray(ElfText.parse(elf, lay, font.codes).apply(elf_tr, lambda s: encode_ui(s, enc)))
    name_grid.apply(elf, lay.delta, grid, enc)
    ui_layout.apply(elf, lay.delta, {r["id"]: r["src"] for r in elf_src}, elf_tr)
    apply_hook(elf, lay.delta, build_hook(alloc.lo, alloc.split, josa_table(pairs, alloc.cmap)))
    rep[ELF] = bytes(elf)
    rep[FONT] = compress(font.to_bytes())
    rep.update(apply_gfx(lambda p: img.read_file(by[p])))
    rep.update(apply_cards(lambda p: img.read_file(by[p]), ui_rows["DATA"]))
    rep.update(apply_title(lambda p: img.read_file(by[p]), str(TITLE_PNG)))

    kept = list(scp_src.values()) + [r for r in elf_src if not r["debug"]] + data_src
    stale = stale_kanji(kept, slots, set(texts) | set(elf_tr) | set(data_tr))
    report = {}
    publish(out, lambda p: report.setdefault("r", build(src, rep, p)), lambda: {
        "policy": "development", "distribution": False, "source_sha1": SOURCE_SHA1,
        "translated_lines": len(texts), "untranslated_lines": len(rows) - len(texts),
        "elf_strings": len(elf_tr), "data_strings": len(data_tr),
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
