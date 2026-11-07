"""v0.16.14 풀 오토: 시작 창 AUTO [보정+렌더] → 분석 끝난 영상부터 렌더(동시 렌더 2), 숨은 메인 창 모니터 작업 없음, 끝나면 종료.
사용: python tests/test_auto_pipeline.py <4K테스트.mp4> <작업폴더>"""
import os, shutil, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
SAMPLE, WORK = sys.argv[1:3]
shutil.rmtree(WORK, ignore_errors=True); os.makedirs(WORK)
app = QApplication(sys.argv)
import main as M; M.dark(app)
from dtme import ff, jobs
jobs.RENDER_N = 2; jobs.RENDER_POOL.setMaxThreadCount(2)          # 동시 렌더 2 로 점검
calls = {"prefetch_range": 0, "render_preview": 0}
for n in calls:
    o = getattr(ff, n)
    setattr(ff, n, lambda *a, _o=o, _n=n, **k: (calls.__setitem__(_n, calls[_n] + 1), _o(*a, **k))[1])
from dtme.ui_main import MainWindow
from dtme.ui_launch import Launcher
vids = []
for i in range(3):
    v = os.path.join(WORK, f"clip{i}_{int(time.time())}.mp4"); shutil.copy(SAMPLE, v); vids.append(v)
out = os.path.join(WORK, "out"); os.makedirs(out)
w = MainWindow(); L = Launcher(w); L.show()
quits = []
L._quit = lambda: (quits.append(time.time()), L.hide())
w.edit._ask_folder = lambda title="": out
log = {"first_render": None, "analysis_done": None, "max_active": 0}
def watch():
    rp = w.edit.render_panel
    log["max_active"] = max(log["max_active"], len(rp.active))
    if rp.active and log["first_render"] is None:
        log["first_render"] = time.time()
    d = w.edit._auto_dlg
    if d is not None and log["analysis_done"] is None and d.rows and all(r.result for r in d.rows if r.checked):
        log["analysis_done"] = time.time()
t = QTimer(); t.timeout.connect(watch); t.start(20)
def press():
    d = w.edit._auto_dlg
    o = w.state.project.output
    o.encoder, o.gpu_decode = "x264", False           # 이 환경 = GPU 없음
    d.b_start.click()
QTimer.singleShot(400, press)
L.run_auto(vids)
t0 = time.time()
while not quits and time.time() - t0 < 600:
    app.processEvents(); time.sleep(0.02)
outs = sorted(os.listdir(out))
print("결과:", outs, "종료:", bool(quits), "상태:", list(w.edit.render_panel.status.values()))
print("첫 렌더 시작 → 모든 분석 끝: %.2f초 먼저" % (log["analysis_done"] - log["first_render"]) if log["first_render"] and log["analysis_done"] else log)
print("동시 렌더 최대:", log["max_active"], "숨은 모니터 작업:", calls, "프록시 상태:", set(w.state.status.values()))
assert len(outs) == 3 and quits
assert log["first_render"] < log["analysis_done"], "분석 끝난 영상부터 렌더"
assert log["max_active"] == 2
assert calls == {"prefetch_range": 0, "render_preview": 0}
assert set(w.state.status.values()) <= {"읽음", "준비"}
print("AUTO PIPELINE OK")
os._exit(0)
