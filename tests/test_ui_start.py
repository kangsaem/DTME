"""v0.16.52 점검: 시작 창 = MOSCO 틀(테두리 없는 400×560 · 그림 400×400 · ✕ 26×26 · 세로 글자 · [AUTO] 160×48 + [편집] 160×32 · 끌어 옮김).
사용: python tests/test_ui_start.py [캡처.png]"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import main as M
from dtme import __version__, paths
from dtme.ui_main import MainWindow
from dtme.ui_launch import Launcher
app = QApplication(sys.argv); M.dark(app)
mw = MainWindow()
la = Launcher(mw); la.show(); app.processEvents()
assert paths.asset("start.png").exists() and paths.asset("dtme.ico").exists(), "assets 없음"
assert la.windowFlags() & Qt.FramelessWindowHint, "제목 표시줄 없음"
assert (la.width(), la.height()) == (400, 560)
assert (la.img.width(), la.img.height()) == (400, 400) and not la.img.pixmap().isNull()
g = la.b_close.geometry()
assert (g.x(), g.y(), g.width(), g.height()) == (364, 10, 26, 26), g
assert la.title.text() == "DTME" and la.title.font().pixelSize() == 42 and la.title.font().bold()
assert la.ver.text() == f"v{__version__}" and la.ver.font().pixelSize() == 13
assert la.title.parentWidget().pos() == QPoint(18, 12)
s = la.side.geometry()
assert s.right() + 1 == 400 - 14 and s.bottom() + 1 == 400 - 14, s           # 오른쪽·아래 끝에서 14px
assert la.side.text == "Diving Tour Movie Editor" and la.side.font().pixelSize() == 14
assert (la.b_auto.width(), la.b_auto.height()) == (160, 48) and la.b_auto.text() == "AUTO"
assert (la.b_manual.width(), la.b_manual.height()) == (160, 32) and la.b_manual.text() == "편집"
assert la.b_manual.y() - (la.b_auto.y() + la.b_auto.height()) == 12, "버튼 간격 12"
assert la.b_auto.y() >= 400 and not la.bar.isVisible() and not la.msg.isVisible() and not la.b_folder.isVisible()
# 빈 곳을 끌어 옮김(글자 위도 통과)
p0 = la.pos()
QTest.mousePress(la, Qt.LeftButton, Qt.NoModifier, QPoint(60, 40))
QTest.mouseMove(la, QPoint(100, 70)); app.processEvents()
QTest.mouseRelease(la, Qt.LeftButton, Qt.NoModifier, QPoint(100, 70))
print("이동:", p0, "→", la.pos())
assert la._drag is None
if len(sys.argv) > 1:
    la.grab().save(sys.argv[1])
# ✕ = 닫기(렌더 중 아님 → 바로 닫힘)
la.b_close.click(); app.processEvents()
assert not la.isVisible(), "✕ = 종료"
print("OK test_ui_start")
