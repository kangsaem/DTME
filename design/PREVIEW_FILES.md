# 카메라 프리뷰 파일(LRF·LRV) 활용 계획

작성 2026-11-08 · 상태: **1·2단계 구현 v0.16.19(실물 LRF 미확인 — 첫 실사용 로그로 확인)**, 3단계 이후 계획 · 관련: HANDOFF.md "10. 다음 할 일 후보"

액션캠은 녹화할 때 원본 옆에 작은 프리뷰 영상을 같이 만든다. DTME가 원본 4K를 디코딩하는 작업 가운데 일부를 이 파일로 바꾸면, 프록시·분석·미리보기가 빨라질 수 있다.
아래 사양은 웹 조사 결과이고 **사용자 카메라 파일로 확인하지 않았다**. 그래서 0단계(점검)부터 한다.

---

## 1. 조사 결과

### 1-1. 카메라별 프리뷰 파일

| 제조사·모델 | 프리뷰 | 원본과 짝 짓기 | 보고된 사양 | 공식 용도 |
|---|---|---|---|---|
| DJI Osmo Action 3·4·5 Pro·6, Action 2, Pocket 2·3 | `.LRF` | 확장자만 다름: `DJI_..._D.MP4` ↔ `DJI_..._D.LRF` | MP4 컨테이너, H.264 High, 1280×720(4:3 영상은 960×720 보고), 29.97fps, 영상 ≈6.5–8Mbps, AAC 스테레오, MJPEG 썸네일 내장, bt709 태그(Pocket 3 ffprobe 예시). **타임코드 메타가 원본과 같음**(Pocket 3 예시 `timecode 08:13:27;02`, Premiere 사용자 = 'Media start' 로 짝 맞춤). DJI 포럼 답변: LRF 는 일반적으로 30fps 로 낮아짐. 드론 Air 3 = LRF 가 원본보다 1프레임 짧은 경우가 절반(정리 스크립트 있음), Mini 4 Pro = 1280×720 ≈19Mbps 실측 보고 | DJI 지원 문서: Mimo "Trim Download"·재생·미리보기용. LRF를 지우면 카메라에서 그 영상을 재생할 수 없음 |
| GoPro HERO5~13, MAX | `.LRV` + `.THM` (Labs 설정 시 `Proxies/…_Proxy.MP4` 또는 `Proxy/….MP4`) | 앞글자: `GX01xxxx.MP4`/`GH01xxxx.MP4` ↔ `GL01xxxx.LRV`, `.THM` = 같은 이름 | 240p~480p 보고(모델마다 다름), HERO11 이후는 LRV도 HEVC, ≈4Mbps, GPS·IMU 데이터 포함(본 MP4 의 GPMF = 자이로 ≈400Hz·가속 ≈200Hz·GPS ≈18Hz). THM = 160×120 JPEG. **고프레임 일부 모드는 LRV 를 안 만든다**는 보고(HERO8 포럼), HERO13 고해상도 모드에서 LRV·THM 이 안 생겼다는 사용자 글도 있음(미확인) | 앱·카메라 화면 미리보기. HERO12·13 매뉴얼: 카메라에서는 숨김 |
| Insta360 Ace·Ace Pro·Ace Pro 2 | `.lrv` | 날짜·시각·번호가 같고 앞 글자와 `_00`/`_01`만 다름: `VID_20240801_154541_00_012.mp4` ↔ `LRV_20240801_154541_01_012.lrv` (`PRO_VID` ↔ `PRO_LRV`) | Ace Pro 4K60 → LRV 30fps(사용자 보고, Resolve 프록시 연결 안 됨). 해상도는 공개 자료 없음. 같은 회사 X4(360) LRV 실측 = H.264 High 1664×832, 29.97fps, 영상 ≈8.6Mbps, yuvj420p(PC 범위) BT.709, AAC 48kHz → Ace 계열도 H.264 30p·수 Mbps일 가능성(추정). Gyroflow 가 LRV 안의 자이로 데이터를 읽음 | 공식 매뉴얼: Video·FreeFrame·Loop Recording 모드에서 MP4(본 파일) + LRV(미리보기) 2개 생성. LRV를 지우면 카메라 앨범에서 미리보기 안 됨. Studio 문서: 빠른 둘러보기, **AI 인식·장면 분석**, 프록시 |
| Insta360 GO 3·GO 3S·GO Ultra | `.lrv` | 위와 같은 규칙(추정) | — | 공식 매뉴얼: Video·FreeFrame·Loop 모드 = MP4 + 미리보기·재생용 LRV(실시간 생성), 사진 모드는 LRV 없음 |
| Insta360 X 시리즈(360) | `.lrv` | `VID_…_00_….insv` ↔ `LRV_…_01/11_….lrv` | — | 같음. 360이라 DTME 대상 아님 |

### 1-2. 확인되지 않은 것 (DTME에 중요)

0. **프레임 수 공통 경향**: DJI·Insta360 모두 60p 원본 → 프리뷰 30p 보고가 있음. 2단계 '프레임 복제로 맞춤'이 기본이 되어야 함
1. **D-Log M으로 찍었을 때 LRF 색** — DJI 매뉴얼: Color Recovery 는 '라이브뷰' 미리보기용. Action 5 Pro 해설: Color Recovery 를 켜도 갤러리(=LRF 재생)는 흐리게 보임 → **Log 일 가능성이 더 큼**(추정)(Insta360 Ace Pro 2 I-Log 도 같은 문제. I-Log 는 H.264 고정·100fps 이상 불가): Log(흐린 화면)인지 Rec.709(보통 화면)인지 모름.
   - "항상 Rec.709 8bit"라는 글이 있으나 출처가 약하다.
   - Action 5 Pro 해설에 "Color Recovery를 켜도 갤러리 재생은 흐리게 보인다"는 내용이 있다. 갤러리 재생 = LRF이므로 Log일 가능성이 있다.
   - **반드시 실물로 확인해야 한다.**
2. **프레임 수**: 4K60·4K120 원본도 LRF는 30fps라는 보고가 여럿 있다(Resolve 프록시 연결 실패 사례). "원본과 같다"는 반대 보고도 1건 있다. 모델과 펌웨어마다 다를 수 있다.
3. **시작 시각·길이 차이**(DJI 드론 Air 3 = 절반 확률로 1프레임 짧음 보고 → 1단계 허용 오차 1프레임 필요): LRF가 원본과 같은 순간에 시작하고 끝나는지(프레임 단위 일치) 모름.
4. **GOP 길이(키프레임 간격)**: 한 장 뽑기·구간 캐시 속도를 정한다. 모름.
5. **특수 모드**: 슬로모(4K120·1080p240), 하이퍼랩스, 세로 촬영, 4GB 넘어 나뉜 파일에도 LRF가 각각 생기는지 모름.
6. **카드에서 복사할 때**: 사용자가 MP4만 복사하면 LRF가 없다. 지금 작업 흐름에서 LRF가 PC로 같이 오는지 확인해야 한다.

---

### 1-3. 추가 조사(2026-11-08, 실물 파일 없음)
- Pocket 3 LRF 에는 타임코드 트랙(`tmcd`)과 `DJI meta` 데이터 트랙이 따로 있음 → 원본과 시각 맞추기에 쓸 수 있음.
- DJI R&D 직원(포럼): LRF 는 녹화와 동시에 만들어지는 저해상도 파일, Mimo 'Trim Download' 용.
- DJI 360 카메라(Osmo 360)용 공개 프로그램들(OpenOSV·rOsmo360·Spatial Film)이 **재생은 LRF, 멈추면·렌더는 원본**으로 이미 쓰고 있음 — DTME 계획과 같은 구조. OpenOSV: '같은 순간'의 LRF 를 재생에 사용.
- rOsmo360: DJI 는 D-Log M 영상에도 색 태그를 보통 BT.709 로 붙인다 → **태그로는 LRF 가 Log 인지 알 수 없음** → 화면 비교로 판정해야 함.
- 결론: **실물 파일이 없어도 만들 수 있게** 설계한다. 1단계에서 영상마다 자동 판정(길이·비율·색 비교) → 맞으면 LRF 사용, 아니면 원본. 사용자의 첫 실사용이 곧 시험이고, 판정 결과·속도는 `cache/dtme.log` 에 남긴다.

## 2. DTME 작업별 대체 가능성

| 작업 | 지금 입력 | 프리뷰로 바꾸면 | 판단 |
|---|---|---|---|
| **프록시 만들기** | 원본 4K HEVC 10bit 전체 디코딩 → 640px all-intra H.264 | LRF(720p H.264 8bit) 디코딩 → 같은 640px all-intra | **가장 효과 큼**. 디코딩할 픽셀이 약 9배 적고 코덱도 가벼움 → 수 배 빨라질 것으로 **추정**(미측정) |
| **AUTO 분석**(샘플 20장, 320px) | 원본에서 장마다 위치 찾기·4K 디코딩(이 환경 장당 ≈0.7초) | LRF에서 뽑기 | 빨라짐. 다만 8bit·압축·카메라 처리 차이로 **인식 프리셋과 값이 달라질 수 있음** → 비교 시험 후 결정 |
| 소스·AUTO 줄 썸네일 | 없음 | DJI LRF 내장 썸네일 / GoPro THM | 즉시 생김. 단, 새 UI라 화면 시안 상의 필요 |
| 전환 미리보기·[미리보기 렌더](540p) | 원본 | LRF | 빨라짐. 미리보기 화질 수준이면 충분 |
| 멈춘 화면 보정·샘플 PNG·스틸·**렌더** | 원본 | **바꾸지 않음** | 화질이 목적이라 원본 유지 |
| (나중) 폰·모바일 | — | 폰이 LRF로 고르고 PC가 원본 렌더 | 모바일 상의(A안)와 연결 |

---

## 3. 단계별 계획

### 0단계 — 점검 도구 (DTME 동작은 그대로) — **사용자 파일이 없으므로 보류.** 같은 검사를 1단계 자동 판정에 넣고 로그로 대신함
- `tools/preview_check.py <카드 또는 폴더>`(또는 exe에 넣은 점검 명령)로 아래를 `preview_report.txt`에 기록한다.
  - **짝 찾기**: 1-1 규칙으로 원본 ↔ 프리뷰
  - **ffprobe 비교**: 해상도, fps, 프레임 수, 길이, 코덱, 비트레이트, 오디오, 시작 시각
  - **GOP**: 키프레임 간격, 프리뷰 한 장 뽑기 시간(ms)
  - **길이 차이**: 프레임 단위
  - **색 판정**: 가운데 프레임으로 `원본+클립 LUT`를 `프리뷰` / `프리뷰+LUT` 와 비교(평균 색차) → `log` / `709` / `모름`
  - **시점 맞춤**: 원본 프레임 몇 장의 작은 그림과 프리뷰 같은 시각 그림의 차이 → 어긋난 프레임 수
  - **속도**: 원본 → 프록시 vs 프리뷰 → 프록시 시간을 짧은 구간으로 실측
- **사용자에게 요청할 시험 촬영**(각 10~20초, MP4 + LRF 그대로):
  ① D-Log M 4K60 ② 일반 4K30 ③ 4:3 ④ 4K120(슬로모) ⑤ 세로 ⑥ 긴 녹화(파일 나뉨) ⑦ 하이퍼랩스. 가능하면 Action 4·5 Pro 모두.
- 결과로 1-2의 1~5를 확정하고 2단계 방식을 정한다.

### v0.16.19 구현 내용 (1·2단계)
- `ff.find_preview(path)`: DJI 같은 이름 `.LRF/.LRV`, GoPro `GX·GH01xxxx → GL01xxxx.LRV`, Insta360 `(PRO_)VID_…_0n_k → (PRO_)LRV_…_01/11/00_k.lrv`. 같은 폴더, 대소문자 무시. **없으면 그냥 원본**(로그도 안 남김)
- `ff.check_preview(src, lut)`: 프록시 만들 때마다(프록시 작업 안) 판정. 디코딩 · 길이 차 ≤ 프리뷰 1프레임 + 원본 1프레임 · 가로세로 비 차 ≤ 2% · 색 = 가운데 프레임 64×36 비교(원본 + 요청 LUT ↔ 프리뷰 그대로 / 프리뷰 + 같은 LUT, 화소 차 중앙값 ≤ 10 이고 다른 쪽의 60% 이하) → `raw`(프리뷰가 이미 그 화면) / `lut`(프리뷰가 Log)
- `make_proxy`: 판정 통과 → 프리뷰로 프록시(`setpts → fps=원본 → tpad 복제 → trim=원본 프레임 수 → 640 → (lut)`), 만든 뒤 프레임 수가 원본과 1 넘게 다르면 버리고 원본 방식. 프록시 이름은 예전과 같음(로그로 구분). 소리 = 프리뷰 소리
- 로그(`cache/dtme.log`): `프록시: 이름 프리뷰(LRF, 29.97fps, 색 lut, 차 0.7) 판정 n초 + 만들기 n초 (영상 n초)` / `프리뷰 안 씀 → 원본: 이름: 이유` / `프리뷰 실패 → 원본`
- 끄기: `ff.PREVIEW_USE = False`. UI 변화 없음
- 시험: `tests/test_preview.py`(합성: Log/709 프리뷰·길이 다름·다른 장면·없음·이름 규칙, CI 포함). **실물 DJI LRF 로는 미확인**
- 한계: 판정용 원본 4K 프레임 1장 디코딩(≈0.7초)이 프록시마다 더해짐. 60p 원본 + 30p LRF = 재생이 30p 처럼(복제), 멈춘 화면·렌더는 원본. 가운데 1장만 비교라 시점 1~2프레임 어긋남은 못 잡음(재생용이라 영향 작음)

### 1단계 — 짝 찾기·저장
- `ff.find_preview(path) -> 경로 | None`: 1-1 규칙. 대소문자 무시, 같은 폴더.
- `Source.preview = {"path", "w", "h", "fps", "frames", "color": log|709|?, "ok": bool, "why": ""}`. 불러올 때 ffprobe 한 번 더(빠름).
- **쓸 수 있는 조건**(`ok`):
  - 길이 차 ≤ 1프레임 시간
  - 가로세로 비 같음
  - 디코딩 됨
  - 색 판정 `log` 또는 `709`
- 불러오기에서 LRF·LRV·THM이 영상으로 들어가지 않게 한다. 지금 확장자 필터가 `.mp4/.mov`라 이미 안 들어간다.
- UI 변화 없음. 소스 줄 툴팁에 `프리뷰 사용`/`프리뷰 없음: 이유` 정도만 둔다(상의).

### 2단계 — 프리뷰로 프록시 만들기 (추천 방식)
- `make_proxy` 입력을 `preview.ok`면 프리뷰로 바꾼다.
- 필터:
  - `fps=원본 fps`: 30p LRF를 60p로 만들 때 프레임을 복제한다. **프록시 프레임 수 = 원본 프레임 수**가 되어 다른 코드를 바꿀 필요가 없다.
  - `scale=640`
  - 색: `log`면 클립 LUT, `709`면 LUT 없음. 이때 **보정 전 화면이 LUT 화면과 다를 수 있어** 0단계 결과로 판단한다.
  - `-g 1` 그대로
- 실패하면 원본 방식으로 자동 전환하고 `cache/dtme.log`에 남긴다.
  - 예: `프록시(LRF) 3.1초 (영상 60초)` / `LRF 실패 → 원본`
- 이름: 프록시 파일 이름에 `|src=lrf`를 넣어 원본 기반 프록시와 구분한다.
- **한계**:
  - 60p·120p 원본은 재생이 30p처럼 보인다(복제 프레임). 탐색 위치는 정확하다.
  - 720p라 640 프록시 화질은 비슷하다.
- **다른 안**: LRF를 그대로 프록시로 쓰기(변환 0초).
  - 긴 GOP라 한 장 뽑기·구간 캐시가 느리다.
  - fps가 다르면 프레임 번호 ↔ 시간 변환을 플레이어·프레임 캐시·타임라인 전부에서 고쳐야 한다(큰 작업).
  - log면 표시할 때마다 LUT가 필요하다.
  - → 2단계 결과를 보고 필요할 때만.

### 3단계 — AUTO 분석에 프리뷰 사용 (선택, 시험 후)
- `auto.grab_small` 입력을 프리뷰로 하는 옵션(`auto.use_preview`)을 둔다.
- **비교 시험**(`tests/test_preview_auto.py`, 사용자 영상): 같은 영상을 원본·프리뷰로 각각 분석해 아래를 비교한다.
  - 인식 프리셋
  - 보정값 차이(빨강·파랑 게인, 색조, 채도 등)
  - ◆ 위치
- 기준(예): 프리셋 같음 + 게인 차 ≤ 0.03 + 색조 차 ≤ 1° → 기본 켬. 아니면 끔 또는 보정식 조정.
- [보정+렌더]의 렌더는 원본 그대로.

### 4단계 — 미리보기류 입력
- 전환 미리보기(P1)와 [미리보기 렌더]의 입력을 프리뷰로 한다.
- 크롭·리프레임·렌즈 보정 좌표가 비율 기준인지 점검한다. 픽셀 기준이면 해상도 비율로 변환한다.

### 5단계 — 썸네일 (UI 상의 필요)
- DJI LRF 내장 MJPEG, GoPro THM → 소스 목록·AUTO 줄 왼쪽 작은 그림. 화면 시안을 먼저 보여 준다.

### 6단계 — 카드 가져오기 도우미 (선택)
- 카드 폴더를 고르면 MP4 + 프리뷰를 함께 복사한다.
- **프리뷰만 먼저 복사해 바로 편집을 시작하고, 원본은 뒤에서 복사**한다. 카드 → PC 복사 시간 동안 작업할 수 있다.
- 렌더·멈춘 화면 보정은 원본 복사가 끝나야 된다(그 영상 줄에 '원본 복사 중' 단계 색).

### 7단계 — 모바일 (나중, 모바일 A안과 연결)
- 폰 웹 화면에서 LRF로 클립을 고르고 구간을 자르면 PC가 원본으로 AUTO 렌더 → 폰 갤러리.

---

## 4. 추천 순서
1(자동 판정 + 로그) → 2(LRF 프록시, 실패 시 원본) → (PC 실사용 로그 확인) → 3 → 4 → 5 → 6 → 7. 0단계는 파일이 생기면
- 0~2단계만으로 **프록시 시간**이 가장 크게 줄어든다(추정). 3단계는 비교 시험 결과에 따라.
- 0단계 결과 전에는 2~4단계 구현 방식을 확정하지 않는다.

## 5. 위험·한계
- 프리뷰 사양이 모델·펌웨어·모드마다 다를 수 있다 → 파일마다 검사하고(1단계 `ok`) 안 맞으면 원본으로 자동 전환한다.
- 프리뷰가 Rec.709로 구워져 있으면 보정 전 화면(LUT만)과 색이 조금 다를 수 있다(재생용으로만 씀).
- 분석을 프리뷰로 바꾸면 인식 결과가 달라질 수 있다 → 3단계 시험 전에는 켜지 않는다.
- GoPro·Insta360는 DTME 보정·LUT 체계(D-Log M 중심) 자체가 아직 맞춰져 있지 않다. 짝 찾기와 프록시만 우선 지원한다.

## 6. 출처
- DJI 지원: "About '.LRF' Files Generated After Recording Using Osmo Action/Osmo Pocket Product"
- DJI 포럼: "Do we need all these LRF Files", "LRF Files with Matching FPS", "How to use LRF files and Batch rename for Proxy use"
- Blackmagic 포럼: "Using DJI .LRF Files as Proxies in Davinci Resolve"
- file-converter-online.com: LRF ffprobe 예시(Pocket 3)
- cosci.de: DJI LRF 960×720(4:3)
- havecamerawilltravel.com: GoPro LRV·THM, HERO13 비트레이트
- gopro/labs GitHub Discussion #1171: HERO13 LRV = HEVC, GPS·IMU 포함
- Insta360 온라인 매뉴얼: X 시리즈 파일 형식, Studio 가져오기 오류(LRV = 미리보기·AI 인식·장면 분석), Ace 시리즈 파일 분실(VID_…_00_ ↔ LRV_…_01_), GO 시리즈 파일 형식(MP4 + LRV)
- Kdenlive 매뉴얼: 카메라 프록시 프로필(GoPro GL/GX, Insta360 Ace Pro LRV/VID)
- Blackmagic 포럼 "Questions About Proxy Media": Ace Pro 60fps → LRV 30fps
- note.com(naru_jpn) "Insta360 の画像・動画ファイルのフォーマットを調べる": X4 LRV ffprobe
- DJI 포럼 "LRF Files with Matching FPS"(답변: 일반적으로 30fps 로 낮아짐)
- GitHub wuyuanyi135/dji_proxy_timecode_match(Air 3 LRF 1프레임 짧음)
- terasor.com "What Is an LRF File?"(Mini 4 Pro LRF 1280×720 ≈19Mbps 실측)
- file-converter-online.com LRF(타임코드 메타, 960×720 또는 1280×720·30fps)
- DJI Osmo Action 5 Pro 사용자 매뉴얼 v1.0(Color Recovery = 라이브뷰 미리보기)
- GoPro 커뮤니티 ".LRV files needed for higher fps"(HERO8 고프레임 모드 LRV 없음), goproforums HERO13 Quik 미리보기 글(LRV·THM 안 생김 보고)
- GitHub HackPartners/gopro-utils(GPMF: 자이로 ≈400Hz, 가속 ≈200Hz, GPS ≈18Hz)
- DJI 포럼 "LRF Files - Why?"(DJI R&D 직원 답변)
- GitHub Kemerd/OpenOSV 0.4.2 릴리스(재생 = LRF, 렌더 = 원본), dogsled69wallet/rOsmo360(D-Log M 도 BT.709 태그), spatial.film Resolve 가이드(Proxy = LRF)
- Gyroflow 문서: Insta360 Ace·Ace Pro·GO 시리즈, GoPro HERO5+ — .lrv/.LRV 프록시 안의 자이로 데이터 지원
- GoPro Labs "Proxy File Support": HERO10~13·MISSION 에서 LRV 대신 `Proxies/GX…_Proxy.MP4`(Premiere) 또는 `Proxy/GX….MP4`(DaVinci) 로 만들게 할 수 있음(그러면 LRV 없음)
- Insta360 매뉴얼: Ace Pro 2 I-Log(H.264 고정, 8K·100fps 이상 불가), 회색 화면 = I-Log
