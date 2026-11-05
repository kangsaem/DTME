# HANDOFF — DTME (Diving Tour Movie Editor)

다음 대화는 이 문서를 기준으로 이어서 작업한다.

## 1. 현재 상태 — v0.4.2 (2026-11-05)

- 저장소: `kangsaem/DTME` (main). push 하면 GitHub Actions 가 Windows 빌드 → Actions → 최신 "Windows build" → Artifacts `DTME-windows`(약 200MB, 30일)
- Linux 작업 환경에서 엔진·화면(오프스크린) 검증, Actions(Windows)에서 빌드·엔진·exe 실행 점검 통과
- **사용자 PC 실기 테스트 진행 중** — 사용자가 화면을 보며 하나씩 수정 요청하는 단계
- Claude 세션에서는 git 태그 push 가 막혀 있음(Release zip 필요하면 사용자가 GitHub 웹에서 태그/Release 생성)

## 2. 작업 규칙 (사용자 선호)

- 한국어, 간결·객관적, 과장 없이 근거와 한계를 같이
- 구체적인 작업은 **선택지와 추천을 먼저 보여주고 상의 후 결정**, 사용자가 “ㄱㄱ”라고 하면 바로 진행
  - 단, 사용자가 상세 지시를 주며 “내 기준으로 수정해보자”라고 하면 그대로 반영하고 모호한 점만 끝에 질문
- **화면에 설명 문구 넣지 말 것.** 사용자가 지시한 글자만. 단축키는 버튼 툴팁으로만
- 화면은 단순하게. 한국식 색(빨강=상승·매수, 파랑=하락·매도) — 이 앱에서는 렌더 버튼 빨강
- 대화가 길어져 압축되면 “새 대화로 넘어갈까요?” 먼저 묻기

## 3. 사용 환경·원본

- 원본: DJI Osmo Action 4, D-Log M, HEVC Main10 3840×2160, **59.94fps CFR**, GOP 30, AAC 48k 스테레오, DJI 메타/타임코드/썸네일 트랙 포함. 수중 영상(파란 기운 → R↑ B↓ 로 보정)
- 파일명 예: `DJI_20261025100118_0148_D.MP4` → 화면·렌더 이름에 `202610251001`(YYYYMMDDhhmm) 사용
- LUT: 사용자 제공 `DJI_OSMO_Action_4_D-Log_M_to_Rec.709_V1.cube` (33포인트, 내부 표기는 Mavic 3 Pro D-Log M). 저장소에는 넣지 않음(사용자가 luts/ 에 넣음)
- PC: Threadripper PRO 5975WX 32코어 / RAM 256GB / RTX 4090 / Windows. 설치 없이 폴더째 실행

## 4. 현재 화면 사양 (사용자가 정한 것)

상단 바: `새 프로젝트 | 저장하기 · 불러오기 · 실행취소` / 탭 없음 — 한 화면 4열: **소스 | 모니터·타임라인 | 보정 | 렌더**

- **소스**: 파일마다 회색 바 1개, 텍스트는 날짜시간만. 준비 전 진한 회색(프록시 진행만큼 밝아짐) / 준비 후 연한 회색. 우클릭 = 불러오기. 아래 [영상 추가] [제거]
- **모니터**: 소스 클릭 즉시 표시, 전환 시 이전 화면 지우고 “로딩 중…”. 재생 = 프록시, 정지·이동 = 프록시 프레임 즉시 → 350ms 후 원본 기준 보정 화면. 세로 출력이면 잘리는 영역 어둡게
- **소스 바**(모니터 바로 아래, 간격 없음): 현재 클립 전체 길이, 인/아웃 구간을 배속 색 + `x2/x1/x1/2`, 구간 왼쪽 위 삼각형 `E`(기본값) / `C`(클립 보정 있음)
- 재생 줄: 왼쪽 `정지 시 보정 화면` 체크 · 가운데 `◀◀ ◀| ▶/❚❚ |▶ ▶▶` · 오른쪽 검은 창 가는 글씨 시간
- 컷 줄(가운데): `[ 컷인` `컷아웃 ]` `IO 해제` `삭제` | `x2 x1 x1/2` | `스틸` `샘플` | `렌더리스트로`
- 상태줄(짧은 글만)
- 타임라인 머리줄 한 줄: 왼쪽 `타임라인 n초` · 가운데 `▼` · 오른쪽 `확대(슬라이더) 전체 삭제 렌더리스트로`
- **타임라인**: 컷을 결과 길이(배속 반영) 비율로 이어 붙임, 클릭 선택, 드래그 순서 변경, 더블클릭 = 소스 열기, 아래 결과 시간 눈금. 30초 표시 없음(사용자: 상관없음)
- **보정**: 머리줄 `보정 ··· [기본값으로 저장]` / 대상 `기본값`·`현재 클립` / `가로·세로` `오디오` / `보정 전 보기` / LUT · R · B · Hue · 샤픈 · 커브(포인트 5) / `디노이즈 [약▾] ↺ ··· [커브리셋]` 한 줄 / `클립 보정 해제 (기본값으로)` / 오른쪽 아래 샘플 2×3 타일(글자 없음, 클릭 = 모니터에 크게·이동 없음, 더블클릭 = PNG 열기)
- **렌더 열**: 맨 위 설정(명칭 · 인코더 · 비트레이트 · 디코딩 · 저장폴더) → `렌더 리스트` 표(파일명·길이·화면·오디오·상태, 우클릭/Del 삭제·다시 렌더) → 아래 가운데 **작은 빨간 렌더 버튼**(▼ 와 같은 64×28, 그림자)
- 샘플 타일은 보정 패널 폭에 맞춰 크기 변경. 타임라인 머리줄에 ‘확대’ 글자 없음(슬라이더만)
- 소스 바 빨간색 = 오류. 마우스를 올리면 오류 내용, 클릭하면 다시 시도. 오류 기록: `cache/dtme.log`

작업 흐름: 소스 클릭 → I/O(또는 [ ])로 인/아웃, 1/2/3 배속 → ↓(▼) 타임라인 끝에 붙임 / Enter(렌더리스트로) 이 구간만 렌더 리스트로 → 타임라인 `렌더리스트로` = 타임라인 전체를 영상 1개로 → 빨간 렌더

- 스틸(S): 현재 프레임을 4K **16bit PNG**로 즉시 저장(저장폴더). 사용자에게 8bit/16bit 차이 설명함 — 선택 답변 대기
- 샘플(G): 현재 클립 전체(인/아웃 무관)에서 고르게 6장 PNG(cache/samples)
- 렌더 파일명: `명칭_날짜시간.mp4`(첫 컷 소스 기준), 겹치면 `_2`

단축키(물리 키 인식, 한/영 무관): Space 재생 · J/L 2배속 뒤/앞(다시 누르면 정지) · ←/→ 1프레임(Shift 1초) · I/[ · O/] · Esc IO 해제 · 1/2/3 배속 · ↓ 타임라인 · Enter 렌더 리스트 · Del 컷 삭제(렌더 표에 포커스면 항목 삭제) · S 스틸 · G 샘플 · B 보정 전 · Ctrl+Z/S/O

## 5. 사용자에게 확인 대기 중

1. “클립보정해제(기본값으로) 버튼은 …” — 요청 문장이 끊겨 있어 그대로 둠. 어떻게 바꿀지
2. Enter/↓ 역할: 버튼 정의대로 ↓=타임라인, Enter=렌더 리스트로 구현(원문에 Enter 가 두 의미로 나옴)
3. 스틸 PNG 8bit/16bit 선택(현재 16bit)

## 6. 구조

```
app/main.py              진입점(다크 테마, 시작 시 cache/frames 비움, DTME_SELFTEST)
app/dtme/paths.py        exe 위치 기준 bin/ luts/ cache/ settings.json
app/dtme/project.py      데이터(Source: sel_in/sel_out/speed/grade, Segment, RenderItem, Marker, OutputSettings), JSON 저장, short_name
app/dtme/ff.py           FFmpeg: probe, 프록시, 필터 체인, 렌더, export_still, 미리보기, grab_proxy_frame, 선명도
app/dtme/state.py        공유 상태, 비동기 불러오기(분석4/프록시1), 선택 소스 프록시 우선, 실행취소(스냅샷 80)
app/dtme/jobs.py         스레드 풀(ANALYZE 4 / PROXY 1 / PREVIEW 4 / GRAB 2 / RENDER 1)
app/dtme/ui_main.py      상단 바, 탭, 저장·불러오기, 드래그 앤 드롭, 자동 저장(cache/autosave)
app/dtme/ui_edit.py      편집·보정 화면, SourceDelegate(회색 바), 키 입력 필터(스캔코드), 스틸
app/dtme/ui_player.py    Monitor(직접 그리기·크롭 표시) + Player(QMediaPlayer+QVideoSink, 프록시 grab, J/L)
app/dtme/ui_bars.py      SourceBar, SeqTimeline
app/dtme/ui_grade.py     GradePanel, 샘플 6장
app/dtme/ui_render.py    RenderPanel(리스트·렌더), RenderTab(설정), out_dir/unique/file_name
app/dtme/ui_curve.py     커브 편집기(자연 3차 스플라인 = FFmpeg curves 와 동일)
tests/test_core.py       실제 샘플 엔진 점검
tests/test_engine_min.py CI용 합성 4K 점검
tests/test_ui_smoke.py   화면 흐름 점검(오프스크린) + 캡처
.github/workflows/build.yml  Windows 빌드(PyInstaller onedir + BtbN FFmpeg master GPL) → 엔진 점검 → exe 실행 점검 → Artifact
```

## 7. 핵심 기술 결정과 근거

- 위치는 전부 **원본 프레임 번호**. 탐색 `-ss (n-0.5)/fps` → n번 프레임 정확(실측)
- 프록시: 960px, libx264 `-g 1`(전 프레임 키프레임), 기본 LUT 입힘. 한 장 뽑기 ≈0.13초(작업 환경 CPU 2코어)
- 렌더 체인: trim → setpts(배속) → fps 29.97 → 크롭/축소 → hqdn3d → gbrp16 → lut3d → colorchannelmixer(R/B) → curves(m) → huesaturation → cas → BT.709 YUV
- **RGB→YUV 변환 시 BT.709 명시 필수**(`TO_YUV709`). 안 하면 BT.601 로 색 틀어짐. 남은 미리보기↔렌더 차이 평균 ≈2.5/255(4:2:0)
- nlmeans 는 8bit 로 떨어져 사용 안 함 → hqdn3d. hue 대신 huesaturation(RGB 16bit 유지)
- LUT 경로: cache/lut 에 해시 이름으로 복사 후 cwd 지정 → 그래서 **모든 입출력 경로는 절대 경로**(`_abs`)
- 미리보기: 원본 프레임 1280px 10bit ffv1 캐시(락 + 임시파일 rename) → 같은 체인 → PNG
- GPU 디코딩 실패 시 CPU 재시도, NVENC 실패 시 상태에 “인코더를 x264로” 표시
- 모니터는 QVideoWidget 을 쓰지 않음(정지 시 검게 나오던 문제) → QVideoSink 프레임/프록시 grab 을 직접 그림
- 비동기 결과는 id·token·gen 으로 현재 상태와 맞는지 확인 후 반영(실행취소·소스 전환 대비)

## 8. 개발·검증 방법

```
pip install --break-system-packages PySide6==6.12.0 numpy pyflakes
python tests/test_engine_min.py <합성4K.mp4>      # ffmpeg -f lavfi testsrc2 3840x2160 59.94 10bit HEVC 2초
python tests/test_core.py <샘플.MP4> <LUT.cube> <출력폴더>
DTME_NO_AUDIO=1 QT_QPA_PLATFORM=offscreen python tests/test_ui_smoke.py <샘플.MP4> <LUT.cube> <합성4K.mp4> <작업폴더>
DTME_SELFTEST=1 DTME_NO_AUDIO=1 QT_QPA_PLATFORM=offscreen python app/main.py   # exit 0 이면 정상
```
- 작업 환경에는 사운드 장치가 없어 `DTME_NO_AUDIO=1` 필요(없으면 QAudioOutput 에서 segfault)
- 오프스크린이라 실제 영상 재생 표시·속도는 확인 불가 → 사용자 PC 피드백 필요
- 커밋 후 push → Actions 성공 확인(`gh api repos/kangsaem/dtme/actions/runs?per_page=1`)
- 샘플 원본(3.4초)·LUT 은 사용자가 대화에 첨부해야 함(저장소에 없음)

## 9. 미검증 (사용자 PC)

- [ ] 재생·J/L·드래그 체감 속도, QVideoSink 재생이 부드러운지
- [ ] NVENC / CUDA 디코딩 동작과 속도
- [ ] 긴 4K 파일 프록시 생성 시간
- [ ] D-Log M LUT 가 액션4 에 맞는지(샘플로는 정상)

## 10. 다음 할 일 후보

- 사용자 실기 피드백 반영(하나씩)
- 타임라인 컷 가장자리 드래그로 길이 조정
- 결과 미리보기 재생(타임라인 컷을 배속 적용해 이어 재생)
- 보정 프리셋 저장/불러오기

## 11. 변경 이력

- v0.4.2: 렌더리스트로 버튼 2개 = 빨간 버튼 + 굵은 오른쪽 화살표 아이콘(QPainter), ▼·렌더리스트로·전체 삭제 72×28 통일, 렌더 = 영상 추가와 같은 90×30, 스틸 저장 완료 표시
  - 디노이즈·샤픈 개선안 비교 중(F안 추천: hqdn3d 색 위주 시간축 + 색 채널 median + 밝기만 unsharp). 사용자 결정 대기

- v0.4.1: Windows WinError 32(파일 사용 중) 대응 — 프록시·미리보기 이름 바꾸기 재시도, 샘플 PNG 는 메모리에서 읽기, 오류 내용 툴팁·로그, 오류 소스 클릭 시 재시도. 렌더 설정을 렌더 리스트 위로 합치고 탭 제거(한 화면), 렌더 버튼 작게+그림자, ▼ 그림자, ‘확대’ 글자 삭제, 샘플 타일 폭 연동

- v0.4.0: 렌더 리스트 한 화면 배치(빨간 렌더), 렌더 탭 = 설정, 명칭+날짜시간 파일명, 소스 회색 바·날짜시간·우클릭 불러오기, 세로 크롭 표시, 모니터 직접 그리기(QVideoSink), 소스 전환 ‘로딩 중…’, 재생 시 보정 화면 즉시 해제, 샘플 2×3 타일, 디노이즈·커브리셋 한 줄, 설명 문구·30초 표시 삭제
- v0.3.0: 소스별 인/아웃·배속 → ▼ 타임라인 / ▶ 렌더 리스트 방식, 타임라인(드래그·확대·눈금), 정지 시 프록시 프레임 즉시 표시(검은 화면 해결), J/L 2배속, 스틸 즉시 PNG, 샘플 6장 PNG, E/C 표시, 저장·불러오기·실행취소
- v0.2.0: 비동기 불러오기·진행 막대·첫 장면 즉시, 물리 키 단축키, 보정 패널 편집 화면 통합, 캐시 경쟁 수정
- v0.1.0: 최초 구현(FFmpeg 엔진, 편집/보정/출력 탭, Windows 빌드)
