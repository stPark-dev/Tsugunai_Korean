# 그림 글자 목록 (D3: 범위 포함)

형식: PSI = 32B 헤더 + (8bpp + CLUT 256 RGBA, CSM1) 또는 32bpp, SL00 압축일 수 있음 (`tools/psi.py`).
GTM = 32B 헤더 + CLUT 256×16bit(ABGR1555, CSM1) + 8bpp 픽셀 (+0x0C 폭/높이), `tools/gtm.py`. 변환 PNG는 `work/gfx/`, `work/*.GTM.png`.

| ID | 파일 | 내용 | 상태 |
|---|---|---|---|
| G1 | TITLE/TITLEA·B·C.PSI (32bpp) | 타이틀 로고 「つぐない」 붓글씨 + 「tsugunai」 | 미착수 — 로고 디자인 방침 결정 필요 |
| G2 | TITLE/TITLE00–34.PSI (35장, SL00, 512×128 8bpp) | 퀘스트 제목 카드(RECORD.DAT 제목과 같은 문구) | 빌드에 반영(`text/gfx/TITLE.jsonl`, `tools/gfx_card.py`). 0–33 = 검수된 퀘스트 제목과 같아야 빌드 통과, 26(Ｌ－４)은 그림 유지, 34(異国のカクテル, 퀘스트 기록에 없음)는 「이국의 칵테일」. 새 게임 시작의 「시련의 시작」 실행 확인 |
| G3 | FONT/STAFF0–3.PSI (SL00, 512×512 8bpp) | 스태프롤: 직함(일본어)·사람 이름 | 직함 44개 빌드에 반영(`text/gfx/STAFF0·2·3.jsonl`, D14). 이름·회사 이름·영문은 그대로. STAFF1 은 이름뿐이라 변경 없음 |
| G4 | STSWIN00.GTM (512×512) | 상태/메뉴 UI: 耐魔力, 炎·爆·冷·星·雷, ちから·すばやさ·せいしん·ステータス, 防御·アイテム·アミュレット·魔法·攻撃, オプション·セーブ·装備·はずす·すてる·ルゥン設定, 履歴, クエスト, 召喚 | 빌드에 반영(`text/gfx/STSWIN00.jsonl`, `tools/gfx_label.py`). 메뉴·능력치·아뮬렛·퀘스트·옵션 화면 실행 확인. 문구는 D12. 履歴 화면은 미확인 |
| G5 | BTLEFF/SENNTOU0.GTM (512×512) | 전투 UI: 魔法防御, 鉄壁防御, 反撃防御, ＳＰ防御, 回避 | 빌드에 반영(`text/gfx/SENNTOU0.jsonl`, D13). 흰 글자+검은 테두리(배경 0xdd, 테두리 0xde). 화면에 나오는 조건 미확인 — 전투 결과 화면·최종 보스전 가드(○△□) 중에는 안 나옴 |

## 대상 아님 (확인함)

- TITLE/SCE.PSI(Sony 로고), CATTLE0/1(개발사 로고), FONT/GAMEOVER·NOWLOAD(영문), MS_WAKU1(창 틀), ENDPIC01–13·BG_IMG(그림만), BTLEFF/*.PSI(이펙트)
- MOVIE/MV000–010.PSS: 2초 간격 프레임 샘플에서 일본어 없음(`work/movie/*_sheet.png`, MV010 「Fin.」 영문). 샘플 간격보다 짧게 나오는 글자는 배제 못 함.

## 모델 텍스처·얼굴·아이콘 전수 조사 (2026-11-20, 대상 아님)

- 묶음 형식: `[u32 개수][u16 0x20 항목 크기][u16 0x20 정렬]` + 항목 `[u32 오프셋][u32 크기][이름 0x18]`, 파일·항목 모두 SL00 압축일 수 있음.
  MDL·MOL·PSL·ARC·MED·BIN(맵 MAP_BG/MAP_GMK, CHARA, MONSTER, BTL_BG, AMULET, AUTO_MAP, MAGIC, BATTLE)이 이 형식.
- 텍스처 .psi 8,411개 → 중복 제거 3,856장(맵·캐릭터 등 3,734 + 마법·전투 122)(8bpp·32bpp, 일부 16bpp ABGR1555·4bpp 변형 25장) + FACE.BIN 얼굴 gt2 16장(32bpp 128×128)
  + 메모리카드 아이콘 DAD_C·D·N.ICO 텍스처(128×128 RLE ABGR1555)를 모두 PNG로 꺼내(`work/tex`, `work/tex2`, `work/tex_extra`) 눈으로 확인.
  변 길이 32px 미만은 제외. 번호 붙인 시트 `work/texsheet/s000–s076.png`(색인 `index.txt`), `extra.png`, `med_bin.png`.
- 결과: **일본어(가나·한자) 글자 없음.** 글자처럼 보이는 것은 지어낸 문자(룬·간판 te090·te141·두루마리 ta522·책등 te256/te266)와
  알아볼 수 없는 영문 채우기 글(양피지 공지, 책등, 「Romantic Night」 포스터, 묘비, 가격표 tc927, 디버그 표기 tf260 「R-1…L-4」).
  영문은 일본 원판에서도 그대로인 장식이라 대상 아님.
- 텍스처 없는 형식(확인함): BATTLE/*.TPL(배치 표, float 좌표), ASL·ETC·MOC·RDM·DID·DAW(이름 목록 없음, 모델·애니메이션·맵 데이터).
- 남은 한계: 맵 지오메트리 위에 정점 색으로 그린 글자, 실행 중 조합되는 글자는 이 방법으로 못 봄 → 플레이 중 관찰로 보완.
