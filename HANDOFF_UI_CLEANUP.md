# HANDOFF — DTME UI 정리 (보조 노트)

> 기준 문서는 저장소 루트 `HANDOFF.md`(DTME 전체 이력·규칙). 이 파일은 **다음 UI 정리 작업**만을 위한 보조 노트다. 상충 시 `HANDOFF.md` 우선, 이 파일은 "무엇을·어디를" 손대면 되는지 길잡이.

## 0. 현재 상태

- 저장소: `kangsaem/DTME` (main). push → GitHub Actions Windows 빌드 → Artifacts `DTME-<버전>-windows`.
- 현재 버전: **v0.16.44** (`app/dtme/__init__.py`).
- Linux(오프스크린)에서 엔진·화면 검증, Actions(Windows)에서 빌드·exe 점검. 사용자 PC 실기 테스트 단계.

## 1. 작업 규칙 (사용자 선호 — HANDOFF.md 와 동일)

- 한국어, 간결·객관적, 과장 없이 **근거와 한계를 같이**.
- 구체적 작업은 **선택지+추천 먼저 상의 → "ㄱㄱ" 때 진행**. 단, 상세 지시를 주면 그대로 반영하고 모호한 점만 끝에 질문.
- **버튼**: 그림자 없음 · 버튼 안 입체감 · 모서리 사각(라운딩 없음). 새 버튼도 `setStyleSheet` 대신 `ui_style.tone()`.
- **팝업**: 제목줄·제목 글자 없는 `ui_render.Popup`(진회색 `#262626`·테두리 `#555`·둥근 6·끌어 이동·오른쪽 아래 [취소][확인]). 이름 입력 = `ui_style.get_text`, 확인 = `ui_style.confirm/ask/notice`.
- **화면에 설명 문구 넣지 말 것.** 지시한 글자만. 단축키는 버튼 툴팁으로만.
- 화면은 단순하게. 한국식 색(빨강=상승·매수, 파랑=하락·매도) — 이 앱에서 **렌더 버튼 = 빨강**.
- 빌드 전 버전 올리고(`__init__.py`), `HANDOFF.md` 변경 이력 최신순 한 줄 추가, 커밋·push.

## 2. UI 파일 지도 (어디를 손대나)

| 파일 | 역할 |
|---|---|
| `ui_launch.py` | 시작 창 (큰 [AUTO] + 작은 [MANUAL]) |
| `ui_auto.py` | AUTO 창 · 보정 탭 프리셋 창 · [샘플] 저장 창 |
| `ui_main.py` | 메인 창 (상단 바 + 편집·보정·렌더 한 화면, 드래그앤드롭) |
| `ui_edit.py` | 편집·보정 화면 레이아웃: **소스 목록** \| 모니터·소스 바·조작·타임라인 \| 보정 \| **렌더 리스트** — `SourceDelegate`(소스 줄 그리기)·`ImageDelegate` 여기 |
| `ui_render.py` | **렌더 리스트** + 렌더 설정 탭, `RenderPanel`·`RenderDelegate`(렌더 줄 바), `Popup`(공통 팝업틀) |
| `ui_bars.py` | 소스 바(모니터 아래) + 타임라인(컷 이어붙이기) |
| `ui_player.py` | 프리뷰 모니터(직접 그림, 재생 프레임 QVideoSink) |
| `ui_grade.py` | 보정 패널(왼쪽 열, 접는 묶음·숫자 직접입력·프리셋) |
| `ui_curve.py` | 마스터 커브 편집기 |
| `ui_titles.py` | 글자 설정 창 · 음악 설정 창 |
| `ui_trans.py` | 화면 전환(컷편집) 고르기 — 그림만, 이름은 툴팁 |
| `ui_style.py` | **버튼·톤·공통 스타일 한 곳** (`tone()`, `get_text`, `confirm/ask/notice`) |
| `stage.py` | **소스별 진행 단계 색**(프록시=파랑·분석=청록·샘플=호박·렌더=빨강), `stage_of()` |

## 3. MOSCO 작업에서 넘어온 결정 (DTME 에 반영할 것)

MOSCO(kangsaem/MOSCO, 얼굴·간판 블러 + 뷰티)는 DTME 의 UI 를 기준으로 통일되어 있다. 최근 MOSCO 세션에서 **두 앱 공통으로 정해진 변경**이 하나 있고, 이는 **DTME 에도 반영하기로 사용자가 명시**했다:

### ★ 렌더 진행 표시를 "렌더 목록 바에만", 소스 목록에서 뺀다
- **현재 DTME 동작**: `stage.STAGE` 에 `"render"`(빨강)가 있어서, `ui_edit.SourceDelegate`(76~88줄 근처, `SG.stage_of(...)` → 줄에 단계 색 채움)가 **소스 목록 줄에 "렌더 NN%"를 빨강으로** 표시한다. 캡처상 소스 줄 오른쪽에 "렌더 33%" 가 뜨는 그 동작.
- **결정(사용자)**: 렌더 진행은 **렌더 목록의 바(`ui_render.RenderDelegate`)에만** 두고, **소스 목록에서는 렌더 단계를 표시하지 않는다**. 소스 줄은 분석(청록)·샘플·프록시까지만.
- **반영 방법(권장)**: `stage_of()`(또는 `SourceDelegate`)에서 **render 단계를 소스 줄 후보에서 제외**. `STAGE["render"]` 자체는 렌더 리스트 쪽에서 쓰므로 지우지 말고, **소스 줄 경로에서만** render 를 건너뛰면 된다. 렌더 리스트 바는 그대로.
- 참고: MOSCO 는 이미 이 방향으로 바뀜(v0.7.37 — 소스목록에서 렌더 진행 제거, 렌더 리스트 비율 바). MOSCO 쪽 구현이 참고가 된다.

> 그 외 MOSCO 가 DTME 에서 가져간 것(렌더 리스트 비율 바, ▼ 네이비 톤, 단계 색 `#24443e`/`#4a2e2c` 등)은 **DTME 가 원본**이라 이미 맞아 있음 — DTME 쪽은 손댈 것 없음.

## 4. UI 정리 후보 / TODO (작업 시작 시 사용자와 확정)

- [x] **(3번) 소스 목록에서 렌더 진행 제거** — v0.16.39(`stage_of(skip=("render",))`, AUTO 창 줄은 유지).
- [x] 버튼 `setStyleSheet` 점검(v0.16.39): 버튼은 모두 빈 값 또는 `ui_style` bevel — 맞음. 도구줄 QToolButton 패딩만 따로.
- [x] 화면 설명 문구: 렌더 설정 저장 폴더 칸 placeholder "렌더할 때 물어봄" — v0.16.41 뺌.
- [x] v0.16.40 제안 7건 + AUTO 창 이름 잘림 + [영상 추가][AUTO][삭제] — v0.16.41 반영(`HANDOFF.md`). ➡·▼ 2개씩은 유지(사용자).
- [x] 프리셋 팝업창 = 바깥을 누르면 닫힘(v0.16.44, 사용자 결정). 누른 곳의 동작은 그대로, 확인 창·우클릭 메뉴가 떠 있는 동안은 안 닫힘.
- [ ] (사용자가 지목할 추가 정리 항목 — 여기에 채워 넣기)

## 5. 설계 동기화 메모

- MOSCO ↔ DTME UI 동기화 문서: DTME `design/AUTO_UI.md`(AUTO 창 동일 UI), `design/BUTTON_UI.md`·`design/button_ref.png`(버튼 기준), `design/mosco/MOSCO_BUTTONS.md`(MOSCO 버튼 목록·계획 — MOSCO 원본은 DTME 에서 안 건드림).
- 두 앱의 **색 체계·소스 줄 구조는 같다**(MOSCO `PROG` == DTME `stage.STAGE`). 한쪽을 바꾸면 다른 쪽도 같은 기준으로 맞출지 확인.

---
*작성 기준: DTME v0.16.38 / MOSCO v0.7.52 (2026-11-10). 이 노트는 UI 정리용 보조 문서이며, 전체 맥락은 DTME `HANDOFF.md`를 따른다.*
