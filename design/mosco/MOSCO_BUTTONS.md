# MOSCO 버튼 목록 · DTME 모양으로 바꾸는 계획 (기준: MOSCO `f13b7d1` v0.5.6)

> **적용 완료: MOSCO v0.6.1 (`516d854`, 2026-11-06, DTME 대화)** — 아래 계획대로 + 나란히 비교로 찾은 것(렌더 설정 창 어두운 창 · 글꼴/슬라이더/콤보 Qt 기본 · AUTO [a|b] 높이 30·최소 폭 100 · 시간 표시 잘림). 기록 = MOSCO HANDOFF 섹션 A-5. 5번 질문 3개는 사용자 답 '다 DTME 기준'(키 ▾ 파랑 · 날짜시간 숨김 · AUTO 글자 간격 삭제)

**MOSCO 원본은 건드리지 않았습니다**(2026-11-06, 사용자: 다른 대화에서 MOSCO 작업 중). DTME 작업 공간에 읽기 전용 사본을 받아 목록을 만들고, 파일을 고치지 않은 채 **실행 중에만** 버튼 모양을 입혀 시안을 찍었습니다.
나중에 MOSCO 대화에서 이 문서대로 적용합니다. 그때 MOSCO 가 `f13b7d1` 보다 바뀌었으면 **줄 번호 대신 함수·글자로 찾고**, 6번 grep 으로 목록을 다시 확인하세요.

- 공통 기준: `design/BUTTON_UI.md` · 견본 `design/button_ref.png`
- 붙여 넣을 스타일시트: `design/mosco/buttons.qss` (DTME `ui_style.py` 값으로 생성 — `python design/gen/make_mosco_qss.py`)
- 시안: `design/mosco/mosco_buttons_before_after.png`(전체) · `design/mosco/mosco_buttons_zoom.png`(확대)

## 1. MOSCO 는 DTME 와 구조가 다름 → 방법도 다름

| | DTME | MOSCO |
|---|---|---|
| 버튼 크기 | 글자에 맞춰 늘고 줆(Fusion 계산) | **모두 고정**(`ui_widgets.btn(size/w)` · `Toggle(w)` · `Seg(h)` · `_b(w,h)`) |
| 입체감 | QProxyStyle(`BevelStyle`) | 창 전체 스타일시트(`ui_widgets.QSS`, 2색 그라데이션) |
| → MOSCO 에 맞는 방법 | | **스타일시트 그대로 두고 버튼 줄만 `buttons.qss` 로 교체**(고정 크기라 DTME 에서 겪은 '80px 최소 폭' 문제 없음). BevelStyle 은 쓰지 않아도 됨 |

## 2. 버튼 목록 (지금 → 바꿀 모양)

| # | 위치(파일 · 함수) | 버튼 | 지금 | 바꿀 모양 |
|---|---|---|---|---|
| 1 | `ui_main` 툴바 | 새 프로젝트 · 저장하기 · 불러오기 · 실행취소 (QToolButton) | 평면(투명), 마우스 올릴 때만 #333 | 기본 입체감 늘 보임 |
| 2 | `ui_main` 저장 확인 창(`confirm_save`) | 취소 · 저장 안 함 · **저장**(빨강) | 2색 그라데이션 + 아래 그림자 | 기본 / 빨강(red) 입체감, 그림자 없음 |
| 3 | `ui_main` 재생 줄 | I◀ ◀◀ ◀\| **▶/❚❚**(88×32) \|▶ ▶▶ ▶I · 분석 | 2색 + 그림자 | 기본 입체감 |
| 4 | `ui_main` 재생 줄 끝 | **➜ 렌더 목록으로**(88×32, 아이콘) | 빨강 2색(테두리 없음) + 그림자 | red |
| 5 | `ui_main` 오른쪽 위 | **AUTO**(88×32) | 빨강 + **자기 스타일시트**(letter-spacing 1px) + 그림자 | red(자기 스타일시트 지움 — letter-spacing 이 꼭 필요하면 `QPushButton[red="true"]#auto` 처럼 따로) |
| 6 | `ui_main` 소스 아래 | 영상 추가 ▾(메뉴) · 삭제 | 2색 + 그림자 | 기본 |
| 7 | `ui_side` 렌더 | ⚙(40×32) · **렌더**(88×32 빨강) | 2색 / 빨강 + 그림자 | 기본 / red |
| 8 | `ui_side.RenderSettings` 창 | 찾기… · **확인** · 취소 | 기본 + 그림자(확인도 회색) | 기본 · **확인 = 파랑(blue)** — DTME 렌더 설정 창과 같게 |
| 9 | `ui_panel` 머리 | 리셋 · 기본값 · 기본값으로 저장(112) · ⊞(28) · 저장…(56) | 2색 + 그림자 | 기본 |
| 10 | `ui_panel` | [뷰티 \| 블러] · [보정 \| 원본 \| 반반] · [블러 \| 모자이크] (`Seg`) | **이어 붙은 직각 평면** #2a2a2a, 켜짐 파랑 평면 | 떨어진 둥근 버튼(간격 5) 각각 입체감, 켜짐 파랑 입체감 |
| 11 | `ui_panel` | 타원 · ID · 몸으로 머리 찾기 · 눈·입 제외 · 타원 추가 · 삭제 · 합치기 (`Toggle`) | **켜짐 = 노랑**(#5a4a1a · #f2c94c) + 그림자 | 켜짐 = **파랑** |
| 12 | `ui_panel` | 피부색 찍기(88) — `set_on` · 자동 | 켜짐 노랑 + 그림자 | 켜짐 파랑 |
| 13 | `ui_panel` | 키 ▾ · 끄기 ▾ (QToolButton 54×26, 메뉴) | 2색, 키 켜짐 노랑 | 기본, 켜짐 파랑 (아래 질문 1) |
| 14 | `ui_panel` | 키 삭제(58) · 값 초기화(76) | 2색 + 그림자 | 기본 |
| 15 | `ui_widgets.Section` | ▾ 뷰티 · ▾ 타원 · ▾ 타원 편집 … (묶음 머리) | 평면 #2b2b2b, 자기 스타일시트 | 머리 입체감(`head` 속성, 왼쪽 정렬) |
| 16 | `ui_panel.PresetGridPopup` | [뷰티\|블러] · [약\|중\|강] · 프리셋 버튼들(104) · 취소(64) · **적용**(84 빨강) | Seg 직각 · 2색 + 그림자 | Seg 둥근 입체감 · 기본 · red |
| 17 | `ui_auto.AutoDialog` | [기존 보정 유지\|무시] · [키프레임 유지\|자동] · [뷰티\|블러] · [약\|중\|강] · [422 HQ\|422\|LT] (`_seg`) | **테두리 상자 + 그림자** 안에 투명 버튼, 켜짐 파랑 2색 | 떨어진 둥근 버튼(간격 5) 입체감, 켜짐 파랑 — DTME AUTO 창과 같게 |
| 18 | `ui_auto.AutoDialog` 아래 | 취소(88×32) · **샘플**(주황) · **보정만**(밝은 회색, 96) · **보정+렌더**(빨강, 110) (`_b(style=…)`) | 2색(테두리 없음) + 그림자 | 기본 / orange / light / red |
| 19 | `ui_auto.SampleDialog` | 선택… · [1280\|1920\|2560\|4K] · [PNG 8bit\|PNG 16bit\|JPG] · 날짜시간 · 번호 · 취소 · **샘플**(주황) | `_seg` 상자 · 토글은 자기 스타일시트(켜짐 파랑 2색 / 꺼짐 #3a3a3a) | Seg 둥근 입체감 · 토글 켜짐 파랑(`on` 속성) · orange (아래 질문 2) |
| 20 | `ui_monitor` 오른쪽 아래 | − · 맞춤 ▾ · + (22 높이) | 반투명 평면 rgba(20,20,20,200) | 반투명 입체감(`tone="overlay"`) |
| — | (안 쓰임) | `ui_auto.AUTO_ON` / `AUTO_OFF`(노란 점선 [자동]) | 정의만 있고 쓰는 곳 없음 | 지워도 됨 |

그림자: `ui_widgets.add_shadow()` 를 `btn()`(기본 `shadow=True`) · `Toggle` · `ui_auto._b` · `ui_auto._seg`(상자)가 부름 → **전부 없앰**.

## 3. 바꾸는 순서 (MOSCO 대화에서)

1. `ui_widgets.py`
   - `QSS` 안의 버튼 줄(`QPushButton, QToolButton { … }` ~ `QToolButton::menu-indicator`)을 **`design/mosco/buttons.qss` 내용으로 교체**. 나머지(QComboBox · QSlider · QLineEdit …)는 그대로
   - `add_shadow()` → 아무것도 안 하게(`return w`) 하거나, 부르는 곳 4곳(`btn` · `Toggle` · `ui_auto._b` · `ui_auto._seg`)에서 뺌
   - `Toggle` 설명 '켜짐 = 노란색' → 파랑(QSS 의 `[on="true"]` 가 파랑이 됨, 코드는 그대로)
   - `Seg`: `lay.setSpacing(0)` → `5`, `b.setProperty("seg", True)` 는 둬도 됨(buttons.qss 에 seg 규칙 없음 = 기본 입체감)
   - `Section.head.setStyleSheet(…)` → 지우고 `self.head.setProperty("head", True)`
2. `ui_main.py`
   - 툴바 스타일시트의 `QToolButton{…background:transparent;border:none}` · `QToolButton:hover{…}` 를 빼고 `QToolButton{padding:4px 12px}` 만
   - `b_auto.setStyleSheet(…)` 지움(빨강은 `red=True` 로 이미 됨)
3. `ui_auto.py`
   - `_b(style=…)`: `setStyleSheet("QPushButton{%s…}" % style)` 대신 `b.setProperty("tone", style)` + `style().unpolish/polish`, 부르는 곳은 `style="orange"` · `"light"` · `"red"`. 상수 `RED/ORANGE/GREY/ON/AUTO_ON/AUTO_OFF` 정리
   - `_seg`: 상자(`box.setStyleSheet` · `add_shadow(box)`) 없애고 `hb.setSpacing(5)`, 버튼의 자기 스타일시트(`transparent` · `:checked` 2색) 지움 → buttons.qss 기본 + 켜짐 파랑
   - `SampleDialog._toggle`: 켜짐/꺼짐 스타일시트 대신 `b.setCheckable(True)` + `setChecked(on)`(또는 `set_on(b, on)`)
4. `ui_side.py`: `RenderSettings` 의 [확인] → `b.setProperty("tone", "blue")`
5. `ui_monitor.py`: − · 맞춤 · + 의 `setStyleSheet(st)` 대신 `b.setProperty("tone", "overlay")`
6. 확인: 바꾸기 전·후 버튼 (글자, 폭, 높이) 비교 — MOSCO 는 고정 크기라 **모두 같아야 함**(Seg 는 간격 5 만큼 버튼 폭이 조금 줆). 그림을 `design/mosco/mosco_buttons_before_after.png` 시안과 비교

## 4. 시안에서 확인한 것 · 한계

- 시안은 MOSCO 파일을 고치지 않고 실행 중에만 입힘: 버튼 줄 QSS 교체 · 그림자 끔 · 툴바 · 묶음 머리 · 모니터 버튼 · `Seg` 간격 5. **AUTO 창 · 샘플 창 · 프리셋 격자 · 렌더 설정 창은 시안에 없음**(클립이 있어야 열림) — 적용 후 따로 확인
- 시안의 [뷰티 \| 블러] 가 흐린 파랑인 건 클립이 없어 꺼짐(비활성) 상태라서
- MOSCO QSS 의 기존 말: '윈도우에서 네이티브 + 그림자 조합이 불안정' → 그림자를 없애므로 이 문제도 같이 사라짐(Windows 에서 다시 확인)

## 5. 정할 것 (사용자에게 물어볼 것)

1. **키 ▾**(키프레임 모드) 켜짐: 켜짐 규칙대로 **파랑**(추천) / DTME ◆ 처럼 키 표시 노랑 유지
2. 샘플 창 **날짜시간** 토글: DTME 는 v0.16.5 에서 뺌 → MOSCO 도 뺄지
3. **AUTO** 글자 간격(letter-spacing 1px): DTME 는 없음 → 맞춰 뺄지(추천)

## 6. 다시 목록 만들기(MOSCO 가 바뀌었을 때)

```bash
grep -rn "QPushButton(\|QToolButton(\|btn(\|Toggle(\|Seg(\|_seg(\|_b(\|setStyleSheet(\|add_shadow\|set_on(" app/mosco/*.py
```
