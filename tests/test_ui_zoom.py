"""모니터 확대 보기 점검. 사용: python tests/test_ui_zoom.py <샘플.MP4> <작업폴더>"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QPoint, QPointF, Qt, QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import main as M
from dtme.ui_main import MainWindow
SAMPLE, WORK = sys.argv[1:3]; os.makedirs(WORK, exist_ok=True)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show(); w.activateWindow()
def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond(): return True
st, e = w.state, w.edit
mon = e.player.mon
e.import_files([SAMPLE]); wait(40, lambda: st.project.sources and st.status.get(st.project.sources[0].id) == "준비")
e.player.seek(100); wait(4)
print("맞춤:", mon.b_zl.text(), round(mon.percent()))
mon.zoom_by(1.2, QPointF(mon.width() * 0.75, mon.height() * 0.5)); print("휠 1번:", mon.b_zl.text())
mon.set_percent(100); print("100% →", mon.b_zl.text(), "보이는 영역", [round(v, 3) for v in mon.visible_norm()])
assert mon.b_zl.text() == "100%"
wait(12, lambda: mon.patch is not None); print("고화질 영역:", None if mon.patch is None else (mon.patch.width(), mon.patch.height()))
assert mon.patch is not None
w.grab().save(os.path.join(WORK, "shot_zoom100.png"))
# 가운데 버튼 끌기 = 이동
c0 = list(mon.center)
QTest.mousePress(mon, Qt.MiddleButton, Qt.NoModifier, QPoint(400, 200)); QTest.mouseMove(mon, QPoint(300, 200))
QTest.mouseRelease(mon, Qt.MiddleButton, Qt.NoModifier, QPoint(300, 200)); wait(0.2)
print("가운데 끌기 이동:", [round(v, 3) for v in c0], "→", [round(v, 3) for v in mon.center]); assert mon.center[0] > c0[0]
# Space 누른 채 끌기 → 재생 안 함
playing = []; e.player.playingChanged.connect(lambda v: playing.append(v))
app.sendEvent(e.player, QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier, " ")); wait(0.05)
c1 = list(mon.center)
QTest.mousePress(mon, Qt.LeftButton, Qt.NoModifier, QPoint(400, 200)); QTest.mouseMove(mon, QPoint(420, 260))
QTest.mouseRelease(mon, Qt.LeftButton, Qt.NoModifier, QPoint(420, 260)); wait(0.1)
app.sendEvent(e.player, QKeyEvent(QEvent.KeyRelease, Qt.Key_Space, Qt.NoModifier, " ")); wait(0.3)
print("Space 끌기:", [round(v, 3) for v in mon.center] != [round(v, 3) for v in c1], "재생 신호", playing); assert not playing
# Space 만 = 재생
app.sendEvent(e.player, QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier, " ")); wait(0.05)
app.sendEvent(e.player, QKeyEvent(QEvent.KeyRelease, Qt.Key_Space, Qt.NoModifier, " ")); wait(0.5)
print("Space 탭 → 재생 신호", playing); assert playing and playing[0] is True
e.player.pause(); wait(0.5)
mon.set_percent(400); print("400% →", mon.b_zl.text())
QTest.mouseDClick(mon, Qt.LeftButton, Qt.NoModifier, QPoint(300, 300)); wait(0.2); print("더블클릭 →", mon.b_zl.text()); assert mon.zoom == 1.0
print("UI ZOOM OK")
