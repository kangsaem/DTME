# 버튼 모양 기준서 (DTME v0.16.6)

다른 프로그램(MOSCO 등)의 버튼을 **DTME 와 완전히 같은 느낌**으로 바꿀 때 쓰는 기준서입니다.
MOSCO 원본은 이 문서를 만들 때 건드리지 않았습니다(사용자 2026-11-06: 다른 대화에서 작업 중). 나중에 MOSCO 대화에서 이 문서 + 파일 2개를 가져가 적용합니다.

- 견본 그림: `design/button_ref.png` (색 종류 × 상태, DTME 실제 그리기 코드로 그림) · 다시 그리기 `python design/gen/make_buttons.py`
- 가져갈 코드: `app/dtme/ui_style.py` (PySide6 만 씀, DTME 다른 모듈에 기대지 않음 → 그대로 복사 가능)
- **MOSCO 버튼 목록 · 적용 계획 · 시안: `design/mosco/MOSCO_BUTTONS.md`** (MOSCO 는 버튼이 모두 고정 크기 → 4번 대신 스타일시트 판 `design/mosco/buttons.qss` 로 교체하는 쪽이 간단)

표시: **[공통]** = 두 프로그램이 똑같이 맞출 것 / **[DTME]** = DTME 에서 어디에 썼는지(MOSCO 는 자기 버튼으로 바꿈)

## 1. 규칙 [공통]

| 항목 | 값 |
|---|---|
| 그림자 | **버튼 아래 그림자 없음**(QGraphicsDropShadowEffect · box-shadow 바깥쪽 전부 삭제) |
| 입체감 | **모든 버튼 안에**: 위 → 아래 밝음 → 어두움 그라데이션, 위 테두리 밝게 · 아래 테두리 어둡게 · 옆 테두리 중간 |
| 모서리 | 둥근 3px (이어 붙은 버튼도 각각 3px — 직각 없음) |
| 켜짐(토글·선택) | 바탕 `#2f4f78` 에 같은 입체감, 테두리 `#4a8fe0`(위만 +30 밝게), 글자 흰색. **노란 켜짐 없음**(◆ 키 표시는 '켜짐'이 아니라 키 표시라 노랑 유지) |
| 마우스 올림 | 조금 밝게 |
| 눌림 | 그라데이션·위아래 테두리 뒤집음(안으로 들어간 느낌) |
| 꺼짐(비활성) | 바탕을 `#3a3a3a` 쪽으로 55% 섞음, 글자를 `#8a8a8a` 쪽으로 60% 섞음 → 색 있는 버튼도 확실히 꺼져 보이게 |
| 크기 | 바꾸지 않음(모양만). 일반 28 높이 · 주요 88×32 등 기존 크기 그대로 |

## 2. 숫자 [공통]

`bg` = 버튼 바탕색, `lt` = 위쪽 하이라이트 = **22**(밝은 버튼: R+G+B > 450 이면 **10**). `shade(c, d)` = R·G·B 각각 d 더하기(0~255 자름).

| 상태 | 그라데이션 (세로, 위 → 아래) 4점 |
|---|---|
| 보통 | 0.00 `shade(bg, lt)` · 0.48 `shade(bg, lt/3)` · 0.52 `bg` · 1.00 `shade(bg, −16)` |
| 마우스 | 위 `lt+10`, 아래 `−6` (나머지 같은 식) |
| 눌림 | 위 `−18`, 아래 `lt/2` |
| 꺼짐 | 바탕 = `dim(bg)` 로 바꾼 뒤 위 `0`, 아래 `−24` |

| 테두리 1px | 보통·마우스 | 눌림 |
|---|---|---|
| 위 | `shade(bg, lt+14)` | `shade(bg, −42)` |
| 아래 | `shade(bg, −42)` | `shade(bg, lt)` |
| 옆 | `shade(bg, −28)` | `shade(bg, −28)` |

켜짐 = 위 식을 `bg = #2f4f78` 로 + 테두리 전체 `#4a8fe0`, 위 테두리 `shade(#4a8fe0, 30)`. 반투명 버튼(화면 위에 얹는 것)은 같은 식에 투명도 225/255.

## 3. 색 종류 [공통 값 · DTME 쓰임]

| 이름(tone) | 바탕 | 글자 | 굵게 | [DTME] 쓰는 곳 | MOSCO 에서 해당하는 버튼(적용 때 채우기) |
|---|---|---|---|---|---|
| (기본) | `#383838` | `#e6e6e6` | | 이름 없는 버튼 전부(리셋·기본값·컷 줄·영상 추가…), 맨 위 줄(새 프로젝트·저장하기·불러오기·실행취소) | |
| red | `#c0392b` | `#ffffff` | ● | 실행: AUTO · 렌더 · ➜ 렌더리스트로 2개 · 보정+렌더 | |
| orange | `#d9822b` | `#ffffff` | ● | 샘플(AUTO 창 · 샘플 창) | |
| light | `#c9c9c9` | `#111111` | ● | 실행(렌더 없음): 보정만 | |
| blue | `#2f4f78` | `#ffffff` | ● | 확인(렌더 설정 창) | |
| navy | `#2f3b4d` | `#e6e6e6` | | ▼ 타임라인으로(글자 15px) | |
| cut | `#3a3a26` | `#e6e6e6` | | [ 컷인 · 컷아웃 ] | |
| key_on | `#5a4a1a` | `#f2c94c` | | ◆ 이 프레임에 키 있음(키만 있고 이 프레임 아님 = 기본 바탕 + 글자 `#f2c94c`, 키 없음 = 글자 `#777777`) | |
| overlay | `#262626` (투명도 225) | `#dddddd` | | 모니터 위: [소스\|타임라인] · [−][맞춤][+] · [명암][색 균형] (글자 11px) | |
| 색 칩 | 그 색 그대로 | — | | 글자 색 고르기 칩(고른 칩 = 테두리 `#4a8fe0`) | |
| 왼쪽 정렬 | `#2b2b2b`(묶음 머리, 굵게) · `#383838`(프리셋) | `#e0e0e0` | | ▾ 색 / ▾ 디테일 … 접는 묶음 머리, [프리셋: 이름 ▾] | |

## 4. 구현 방법 — Qt(PySide6/PyQt) [공통]

**핵심: 앱 전체 스타일시트로 하지 말 것.** Qt 기본(Fusion)은 글자 있는 버튼에 최소 폭 80px 을 주는데, 스타일시트가 걸리면 이 규칙이 사라져 버튼이 글자 크기만큼 좁아짐. `min-width` 로 되돌리면 이번엔 고정 크기 버튼(22px ◆ · 24px −/+ · 34px ⚙)까지 80px 로 커짐(DTME 에서 실제로 겪음). → **Fusion 을 그대로 두고 '바탕 그리기'만 바꾸는 QProxyStyle** 로 함. 크기 계산이 예전과 100% 같음.

1. `ui_style.py` 를 MOSCO 패키지에 복사(파일 맨 위 설명만 MOSCO 로 고침).
2. 앱 시작: `app.setStyle(ui_style.BevelStyle())` — 기존 `app.setStyle("Fusion")` 자리. 팔레트(어두운 색)는 그대로.
3. 그림자 삭제: `QGraphicsDropShadowEffect` · `setGraphicsEffect` 를 버튼에서 모두 뺌.
4. 버튼 스타일시트 바꾸기: 버튼에 `setStyleSheet("QPushButton{background:…}")` 처럼 **바탕·테두리를 정하는 스타일시트가 있으면 입체감이 안 그려짐**(그 버튼은 스타일시트가 그림). 전부 지우고
   - 색 있는 버튼 → `ui_style.tone(b, "red")` 등 3장의 이름
   - 글자 색만 → `ui_style.tone(b, fg="#f2c94c")`
   - 임의 색 칩 → `ui_style.tone(b, color="#ff8800", sel=고른것)`
   - 켜짐 파랑 스타일시트(`:checked{background:#2f4f78…}`) → **지움**(BevelStyle 이 켜짐을 파랑으로 그림)
   - 직각(`border-radius:0`)만 있던 이어 붙은 버튼 → 지우고 `setMinimumWidth(40)`(Fusion 80px 최소 폭이 다시 생겨 넓어지는 것 막기)
   - 글자 크기·굵기만 있던 것 → `setFont`(스타일시트 대신)
   - 왼쪽 정렬이 꼭 필요한 버튼만 → `setStyleSheet(ui_style.bevel(바탕, 글자, extra="text-align:left; padding:0 8px;"))` (크기가 고정이거나 늘어나는 버튼에만)
5. 툴바(QToolButton): `btn.setAutoRaise(False)` + `btn.setProperty("bevel", True)` → 늘 입체감.
6. 확인: 바꾸기 전·후에 **보이는 버튼 전부의 (글자, 폭, 높이)** 를 찍어 비교(아래 스크립트). DTME 는 57개 중 의도한 것만 바뀜.

```python
# 전·후 버튼 크기 비교(오프스크린). before 는 app.setStyle("Fusion") 로, after 는 BevelStyle 로 각각 실행해 json 저장 후 비교
from PySide6.QtWidgets import QPushButton
rows = {f"{b.text()}@{b.mapTo(w, b.rect().topLeft()).toTuple()}": (b.width(), b.height())
        for b in w.findChildren(QPushButton) if b.isVisible()}
```

7. 그림 비교: 같은 크기 창을 캡처해 `design/button_ref.png` 와 나란히(색·입체감·켜짐 파랑·꺼짐).

## 5. 웹(HTML/CSS)일 때 [공통 — MOSCO 가 웹 화면이면]

같은 값의 CSS(바탕 `--bg` 만 바꿔 씀). 바깥 그림자 없음, 안쪽 입체감은 그라데이션 + 위·아래 테두리.

```css
.btn{--bg:#383838; --fg:#e6e6e6; color:var(--fg); border-radius:3px; border:1px solid color-mix(in srgb,var(--bg),#000 22%);
  border-top-color:color-mix(in srgb,var(--bg),#fff 14%); border-bottom-color:color-mix(in srgb,var(--bg),#000 30%);
  background:linear-gradient(to bottom, color-mix(in srgb,var(--bg),#fff 9%) 0%, color-mix(in srgb,var(--bg),#fff 3%) 48%,
    var(--bg) 52%, color-mix(in srgb,var(--bg),#000 12%) 100%); box-shadow:none;}
.btn:hover{background:linear-gradient(to bottom, color-mix(in srgb,var(--bg),#fff 13%), var(--bg) 52%, color-mix(in srgb,var(--bg),#000 5%));}
.btn:active{background:linear-gradient(to bottom, color-mix(in srgb,var(--bg),#000 14%), var(--bg) 52%, color-mix(in srgb,var(--bg),#fff 4%));
  border-top-color:color-mix(in srgb,var(--bg),#000 30%); border-bottom-color:color-mix(in srgb,var(--bg),#fff 9%);}
.btn.on,.btn[aria-pressed=true]{--bg:#2f4f78; --fg:#fff; border-color:#4a8fe0; border-top-color:#68adff;}
.btn:disabled{--bg:color-mix(in srgb,var(--bg0,#383838),#3a3a3a 55%); color:color-mix(in srgb,var(--fg),#8a8a8a 60%);}
.btn.red{--bg:#c0392b; --fg:#fff; font-weight:700} .btn.orange{--bg:#d9822b; --fg:#fff; font-weight:700}
.btn.light{--bg:#c9c9c9; --fg:#111; font-weight:700} .btn.blue{--bg:#2f4f78; --fg:#fff; font-weight:700}
```
(웹은 % 로 근사 — Qt 의 `shade(+22)` ≈ 흰색 9% 섞기. 견본 그림과 나란히 놓고 맞출 것)

## 6. 목록 만들기 [MOSCO — 이미 만듦: design/mosco/MOSCO_BUTTONS.md]

MOSCO 대화에서 원본을 열 수 있을 때, 바꾸기 전에 아래로 버튼 목록을 만들고 3번 표 오른쪽 칸을 채운 뒤 사용자에게 보여 주고 시작.

```bash
grep -rn "QPushButton(\|QToolButton\|setStyleSheet(\|QGraphicsDropShadowEffect\|setGraphicsEffect\|:checked" <MOSCO 소스 폴더>
```

| 목록에 적을 것 | 예 |
|---|---|
| 버튼 이름(글자) · 위치(창·줄) | `렌더` · 오른쪽 아래 |
| 지금 모양 | 빨강 평면 + 그림자 / 켜짐 노랑 / 기본 |
| 크기 | 88×32 고정 / 높이 28 폭 가변 |
| 바꿀 이름(tone) | red / (기본) / overlay … |
| 스타일시트로 남길 것 | 왼쪽 정렬만 |

[DTME] 통일 전 목록(참고): 빨강·주황·밝은 회색·남색 평면 + 아래 그림자 / 확인 파랑 평면 / 켜짐 파랑 스타일시트 3벌 + 노랑 1개 / 모니터 위 반투명 3벌 / 묶음 머리 평면 / 이어 붙은 직각 / 맨 위 줄 평면(마우스 올릴 때만 테두리) / 배속 켜짐이 Fusion 기본(눈에 안 띔). → 모두 위 규칙으로. 크기 변화는 컷 줄 [ 컷인 · 컷아웃 ] 56 → 다른 버튼과 같은 폭뿐.
