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
        assert not w.state.work and "분석" not in d.state_lab.text(), "AUTO 창 열기만 = 표시 없음(분석은 뒤에서 미리)"
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
from dtme import ff as _ff
_pre = {"n": 0, "hidden": 0}
_orig_pf = _ff.prefetch_range
def _pf(*a, **k):
    _pre["n"] += 1
    if not w.isVisible():
        _pre["hidden"] += 1
    return _orig_pf(*a, **k)
_ff.prefetch_range = _pf
QTimer.singleShot(500, act("each"))
L.run_auto([vid])
assert w.isVisible() and not L.isVisible(), "보정+편집 → 메인 창"
sid = w.state.project.sources[0].id
t = time.time()
while _pre["n"] == 0 and time.time() - t < 30:
    app.processEvents(); time.sleep(0.05)
print("편집 첫 장면 미리 준비(원본 구간 캐시):", _pre)
assert _pre["hidden"] >= 1, "[보정+편집] 누른 뒤 숨어 있을 때 미리 준비"
st0 = w.state.status.get(sid)
print("편집 화면 넘어갈 때 프록시:", st0, "(기다리지 않음)")
assert st0 != "읽음" and not w.state.defer_proxy, "버튼 때 프록시 시작"
t = time.time()
while w.state.status.get(sid) != "준비" and time.time() - t < 240:
    app.processEvents(); time.sleep(0.05)
assert w.state.status.get(sid) == "준비"
import subprocess, json
info = json.loads(subprocess.run([__import__("dtme.paths", fromlist=["x"]).ffprobe(), "-v", "error", "-select_streams", "v:0",
                                  "-show_entries", "stream=width", "-of", "json", w.state.project.sources[0].proxy],
                                 capture_output=True).stdout)
print("프록시 폭:", info["streams"][0]["width"]); assert info["streams"][0]["width"] == 640
assert len(w.state.project.sources) == 1, "새 작업(소스 1개)"
print("launcher OK")

os._exit(0)
