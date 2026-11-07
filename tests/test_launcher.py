"""v0.16.8 시작 창: AUTO → (파일) → AUTO 창만 → [취소]=시작 창 / [보정만]=메인 창. 사용: test_launcher.py 영상.mp4"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen"); os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import main as M
from dtme.ui_main import MainWindow
from dtme.ui_launch import Launcher, collect_videos

app = QApplication(sys.argv); M.dark(app)
vid = sys.argv[1]
assert collect_videos([os.path.dirname(os.path.abspath(vid))]), "폴더 → 영상"
w = MainWindow(); L = Launcher(w); L.show()
log = []

def act(what):
    def f():
        d = w.edit._auto_dlg
        log.append((what, L.isVisible(), w.isVisible(), d.isVisible()))
        t = time.time()
        while d.pending() and time.time() - t < 240:
            app.processEvents(); time.sleep(0.05)
        (d.cancel if what == "cancel" else (lambda: d._go("each")))()
    return f

QTimer.singleShot(500, act("cancel"))
L.run_auto([vid])
assert log[0] == ("cancel", False, False, True), log      # AUTO 창만 보임
assert L.isVisible() and not w.isVisible(), "취소 → 시작 창"
QTimer.singleShot(500, act("each"))
L.run_auto([vid])
assert w.isVisible() and not L.isVisible(), "보정만 → 메인 창"
assert len(w.state.project.sources) == 1, "새 작업(소스 1개)"
print("launcher OK")
os._exit(0)
