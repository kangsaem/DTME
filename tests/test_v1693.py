"""v0.16.93: 세로 수심 그래프(수면 = 1/2 · 최대 수심 = 아래 1/10 위) · 소나 첫 그림 분홍 점 · 기간 '~'.
사용: python tests/test_v1693.py"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter  # noqa: E402
app = QGuiApplication(sys.argv)
from dtme import autoedit, dive_draw as D  # noqa: E402

# 세로: 수면 960 · 최대 수심 1728 (1080×1920)
k, top, gh = D.geo(1080, 1920)
assert abs(top - 960) < 1e-6 and abs(top + gh - 1728) < 1e-6, (top, gh)
dive = {"id": "x", "start": 0.0, "max": 20.0, "pts": [(0, 0.0), (300, 20.0), (600, 0.0)]}
_px, py = D._xy(dive, 1080, 1920)
assert abs(py(0) - 960) < 1e-6 and abs(py(20) - 1728) < 1e-6
# 가로: 예전 그대로(수면 270k · 아래 73k)
k, top, gh = D.geo(1920, 1080)
assert abs(top - 270) < 1e-6 and abs(top + gh - (1080 - 73)) < 1e-6
k, top, gh = D.geo(3840, 2160)
assert abs(top - 540) < 1e-6 and abs(top + gh - (2160 - 146)) < 1e-6

# 소나 첫 그림만 분홍
nfr = int(D.PULSE_SEC * D.PULSE_FPS)
assert D.is_flash(0.0) and D.is_flash(3.0) and D.is_flash(1 / nfr) and not D.is_flash(0.5)      # v0.16.96 분홍 = 1초
assert [D.is_flash(j / nfr) for j in range(nfr)].count(True) == D.PULSE_FPS


def center(phase):
    im = QImage(120, 120, QImage.Format_ARGB32_Premultiplied)
    im.fill(Qt.transparent)
    p = QPainter(im)
    D.paint_glow(p, 60, 60, 1.0, phase)
    D.paint_flash(p, 60, 60, 1.0, phase)
    p.end()
    return QColor.fromRgba(im.pixel(60, 60))


c0, c1 = center(0.0), center(0.5)
assert c0.name().lower() == D.DOT_FLASH.lower(), c0.name()
assert c1.alpha() == 0, c1.name()          # 첫 그림 뒤 = 깜빡임 그림에 점 없음(그래프의 빨간 점이 보임)

# 기간 물결
from datetime import datetime  # noqa: E402
a = datetime(2026, 10, 27, 9).timestamp()
s = autoedit.period_text(a, a + 6 * 86400)
assert "~" in s and "–" not in s, s
print("기간:", s)
print("OK test_v1693", flush=True)
os._exit(0)                # 끝날 때 Qt 정리에서 가끔 비정상 종료(Windows CI) → 바로 끝냄
