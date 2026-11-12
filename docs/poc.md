# PoC 기록

환경: PCSX2 v2.8.2 (flatpak, `--filesystem` 프로젝트 폴더 허용), BIOS scph39001, `tools/run.sh`(Xvfb :99) + `tools/xinput.py`.
원본 부팅: 타이틀까지 약 35초(-fastboot). Return → l(○) → 약 45초 뒤 첫 대사(M00_25 `ルイ僧官 / 何ということでしょう…`).

## PoC1 — 폰트 표시 경로 (2026-11-12, 통과)

- 질문: FONT.BIN 글리프를 바꾸면 대사 창·화자 이름에 그대로 나오는가? FILEZ/ISO 갱신으로 옮긴 파일을 게임이 읽는가?
- 빌드: `python -m tools.build_poc1 orig/tsugunai.bin build/poc1.bin`
  글자 12개 글리프를 Noto Sans CJK KR Medium 20px로 교체 → SL00 재압축 284,518 B(원래 279,869 B) → 섹터 수 초과로 디스크 끝 재배치.
- 관찰: 첫 대사 창에 `루이승관 / 『무슨일이란슨말인가이…』` 표시(`work/shots/poc1_a.png`).
- 결론:
  - FONT.BIN 헤더 CLUT 알파 해석과 4bpp(상위 니블=왼쪽) 해석이 맞음.
  - 대사 본문과 화자 이름(op 0x38)이 같은 폰트를 씀.
  - 파일 재배치(FILEZ.DAT + ISO 디렉터리 + 볼륨 크기 갱신)를 게임이 그대로 따름.
  - `『』`는 텍스트에 없는데 화면에 나옴 → 엔진이 붙이는 것으로 추정(번역문에 넣지 않음, 추가 확인 필요).
- 아직 아님: 텍스트 길이 변경(PoC2), 메뉴·전투 등 다른 소비자의 폰트 경로.
