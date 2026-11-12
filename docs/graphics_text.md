# 그림 글자 목록 (D3: 범위 포함)

형식: PSI = 32B 헤더 + (8bpp + CLUT 256 RGBA, CSM1) 또는 32bpp, SL00 압축일 수 있음 (`tools/psi.py`).
GTM = 32B 헤더 + CLUT 256×16bit(ABGR1555, CSM1) + 8bpp 픽셀 (+0x0C 폭/높이). 변환 PNG는 `work/gfx/`, `work/*.GTM.png`.

| ID | 파일 | 내용 | 상태 |
|---|---|---|---|
| G1 | TITLE/TITLEA·B·C.PSI (32bpp) | 타이틀 로고 「つぐない」 붓글씨 + 「tsugunai」 | 미착수 — 로고 디자인 방침 결정 필요 |
| G2 | TITLE/TITLE00–34.PSI (35장, SL00, 512×128 8bpp) | 퀘스트 제목 카드(RECORD.DAT 제목과 같은 문구) | 미착수 |
| G3 | FONT/STAFF0–3.PSI (SL00, 512×512 8bpp) | 스태프롤: 직함(일본어)·사람 이름 | 미착수 — 이름은 원문 유지 여부 결정 필요 |
| G4 | STSWIN00.GTM (512×512) | 상태/메뉴 UI: 耐魔力, 炎·爆·冷·星·雷, ちから·すばやさ·せいしん·ステータス, 防御·アイテム·アミュレット·魔法·攻撃, オプション·セーブ·装備·はずす·すてる·ルーン設定, 履歴, クエスト, 召喚 | 미착수 |
| G5 | BTLEFF/SENNTOU0.GTM (512×512) | 전투 UI: 魔法防御, 鉄壁防御, 反撃防御, ＳＰ防御, 回避 | 미착수 |

## 대상 아님 (확인함)

- TITLE/SCE.PSI(Sony 로고), CATTLE0/1(개발사 로고), FONT/GAMEOVER·NOWLOAD(영문), MS_WAKU1(창 틀), ENDPIC01–13·BG_IMG(그림만), BTLEFF/*.PSI(이펙트)
- MOVIE/MV000–010.PSS: 2초 간격 프레임 샘플에서 일본어 없음(`work/movie/*_sheet.png`, MV010 「Fin.」 영문). 샘플 간격보다 짧게 나오는 글자는 배제 못 함.

## 미확인 (다음 확인 방법)

- 맵 모델(MAP_BG/MAP_GMK *.MDL) 텍스처 속 간판·비석 글자 → 플레이 중 관찰로 목록에 추가
- FACE/FACE.ARC, BATTLE/*.TPL, DAD_*.ICO(메모리카드 아이콘) 형식 미해석
- WALL_6.GTM(512×256): 벽 무늬, 글자 없음(확인함)
