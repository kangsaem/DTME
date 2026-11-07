"""v0.16.9 시작 창: AUTO → (파일) → AUTO 창만 → [취소]=프로그램 종료 / [보정+편집]=메인 창. 사용: test_launcher.py 영상.mp4"""
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
quits = []
L._quit = lambda: (quits.append(1), L.hide())

def act(what):
    def f():
        d = w.edit._auto_dlg
        log.append((what, L.isVisible(), w.isVisible(), d.isVisible()))
        assert not d.jobs and not w.state.work, "AUTO 창 열기만 = 작업 없음"
        t = time.time()
        while time.time() - t < 3:
            app.processEvents(); time.sleep(0.05)
        sts = [w.state.status.get(s.id) for s in w.state.project.sources]
        log.append(("status", sts, dict(w.state._proxy_jobs)))
        (d.cancel if what == "cancel" else (lambda: d._go("each")))()
    return f

QTimer.singleShot(500, act("cancel"))
L.run_auto([vid])
assert log[0] == ("cancel", False, False, True), log      # AUTO 창만 보임
print("AUTO 창 상태:", log[1][1], "프록시 작업", len(log[1][2]))
assert log[1][1] == ["읽음"] and not log[1][2], "시작 창 AUTO = 프록시 미룸"
assert quits and not w.isVisible(), "취소 → 프로그램 종료"
QTimer.singleShot(500, act("each"))
L.run_auto([vid])
assert w.isVisible() and not L.isVisible(), "보정+편집 → 메인 창"
sid = w.state.project.sources[0].id
print("보정+편집 뒤 프록시:", w.state.status.get(sid)); assert w.state.status.get(sid) != "읽음" and not w.state.defer_proxy
t = time.time()
while w.state.status.get(sid) != "준비" and time.time() - t < 240:
    app.processEvents(); time.sleep(0.05)
assert w.state.status.get(sid) == "준비"
assert len(w.state.project.sources) == 1, "새 작업(소스 1개)"
print("launcher OK")
os._exit(0)
