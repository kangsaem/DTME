"""v0.16.33 점검: 시작 창 [보정+렌더] 끝 = 완료 팝업 → [확인]이면 종료(실패 있으면 남김), 렌더 중 시작 창 제목·막대 = 전체 진행.
사용: python tests/test_launch_done.py"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication, QLabel
import main as M
from dtme.ui_main import MainWindow
from dtme.ui_launch import Launcher
app = QApplication(sys.argv); M.dark(app)
mw = MainWindow()
la = Launcher(mw); la.show()
quits = []
la._quit = lambda: quits.append(1)
rp = mw.edit.render_panel


def spin(n=20):
    for _ in range(n):
        app.processEvents(); time.sleep(0.01)


la.rendering = True
rp.runProgress.emit(0.42, "3/35 · 42%", False); spin()
print("제목:", la.windowTitle(), "· 막대:", la.bar.value())
assert "렌더 3/35 · 42%" in la.windowTitle() and la.bar.value() == 42
rp.runFinished.emit(35, 0, 1752.0, "/tmp"); spin()
d = la._done_dlg
txt = d.findChildren(QLabel)[0].text()
print("팝업:", txt, d.isVisible(), "· 종료 전:", quits)
assert d.isVisible() and txt == "렌더 완료 35개 · 실패 0개 · 29분 12초" and not quits
d.b_ok.click(); spin()
assert quits == [1], "확인 = 종료"
# 실패 있음 = 남김
la.rendering = True
rp.runFinished.emit(33, 2, 100.0, "/tmp"); spin()
la._done_dlg.b_ok.click(); spin()
assert quits == [1], "실패 있으면 종료 안 함"
assert "실패 2개" in la.msg.text()
print("OK test_launch_done")
