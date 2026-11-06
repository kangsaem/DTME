"""MOSCO 용 버튼 스타일시트 = design/mosco/buttons.qss (DTME ui_style 값 그대로).
MOSCO 는 버튼이 모두 고정 크기(ui_widgets.btn · Toggle · Seg)라 스타일시트 방식이 안전 → 기존 QSS 의 버튼 줄을 이 파일 내용으로 바꿈.
사용: python design/gen/make_mosco_qss.py"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "app"))
from dtme import ui_style as S  # noqa: E402

ON = 'QPushButton:checked, QPushButton[on="true"], QToolButton:checked, QToolButton[on="true"]'
parts = [
    "/* ---- 버튼(DTME 와 같은 모양: 그림자 없음 · 버튼 안 입체감 · 켜짐 파랑) — design/gen/make_mosco_qss.py 로 만듦 ---- */",
    S.bevel(S.BASE, sel="QPushButton, QToolButton", extra="padding:0 6px;"),
    "QToolButton::menu-indicator { image: none; }",
    S.bevel("#c0392b", "#ffffff", bold=True, sel='QPushButton[red="true"], QPushButton[tone="red"]'),
    S.bevel("#d9822b", "#ffffff", bold=True, sel='QPushButton[tone="orange"]'),
    S.bevel("#c9c9c9", "#111111", bold=True, sel='QPushButton[tone="light"]'),
    S.bevel(S.SEL_BLUE, "#ffffff", bold=True, sel='QPushButton[tone="blue"]'),
    S.bevel("#262626", "#dddddd", sel='QPushButton[tone="overlay"]', alpha=225, extra="font-size:11px; padding:0;"),
    S.bevel("#2b2b2b", "#e0e0e0", bold=True, sel='QPushButton[head="true"]', extra="text-align:left; padding-left:8px;"),
    S.bevel_on(ON),                                    # 켜짐은 맨 뒤(다른 규칙보다 우선)
]
out = os.path.join(HERE, "..", "mosco", "buttons.qss")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(parts) + "\n")
print(out, sum(len(x) for x in parts), "자")
