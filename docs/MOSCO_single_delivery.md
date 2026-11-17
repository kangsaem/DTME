# MOSCO → DTME — 하나만 실행 `single.py` 전달 (MOSCO v0.7.99, 2026-11-17)

DTME 답변(질문 1~4 + 사용자 확정)대로 MOSCO 에 먼저 넣었습니다. 첨부 `single.py`·`test_single.py` 를 그대로 복사해 쓰면 됩니다.

## 파일
- `single.py` — 앱 전용 import 없음(PySide6 QtCore·QtNetwork 만). 앱 이름만 인자.
  - `acquire(app_name, retry_s=8.0, step_s=0.3, skip=False) -> bool` — False 면 이 실행 종료(기존 창이 앞으로 옴)
  - `serve(app_name, on_show, parent=None)` — 첫 실행이 듣기. `on_show()` = 앱이 정하는 '보이는 창 맨 앞으로'
  - `owner() -> bool` — False = 잠금 없이 실행 중(답 없는 옛 프로세스가 잠금을 쥐고 있음) → **DTME 는 시작 정리(cache/frames 삭제) 건너뛸 것**
  - `release()` — 종료 직전(안 불러도 죽으면 자동 해제)
  - 예외: 환경 변수 `<앱이름 대문자>_MULTI=1` 또는 `skip=True`(빌드 점검)
- `test_single.py` — 실제 프로세스로 시험(경로 `APP`·`from mosco import single` 두 줄만 DTME 에 맞게). CI 에서 성공 표식 `SINGLE OK` 로 판정.

## DTME 에서 넣는 순서 (MOSCO main.py 기준)
```python
app = QApplication(sys.argv)
from <패키지> import single                 # 무거운 import 전에
if not single.acquire("DTME", skip=bool(os.environ.get("DTME_SELFTEST"))):
    hard_exit(0)
single.serve("DTME", on_show, app)
if single.owner():
    시작 정리(cache/frames 삭제)            # DTME 추가분
from <패키지>.ui_main import MainWindow    # 무거운 import 는 이 뒤로
...
# 종료 직전: single.release()
```
on_show 예(MOSCO): `QApplication.activeModalWidget()` 또는 보이는 최상위 창 → 최소화면 `showNormal()` → bring_front.

## 확인 결과
- **윈도우 CI(Actions)에서 4개 시험 통과**: 기본 · 동시 실행 3번(잠금 하나만) · **강제 종료(TerminateProcess) 뒤 다시 실행 = owner True**(setStaleLockTime(0) + 죽은 프로세스 자동 해제 확인 — DTME 요청 항목) · 멈춘 프로세스(잠금만 쥠) → 재시도 뒤 그냥 실행(owner False).
- MOSCO 앱 실제 동시 실행 3번(리눅스) → 매번 하나만 남음.
- 실제 윈도우 PC 더블클릭은 아직 사용자 확인 전.

## 남은 DTME 몫
- '보이는 창 0개 6초 → 종료' 안전장치(MOSCO `main._watch_windows` 참고: 1.5초마다 보이는 창 확인, 4번 연속 없으면 `app.quit()`).
