"""v0.16.91 렌더 작업 창(A안): [렌더] → 편집 창 숨김 · 작업 창(항목 줄·단계·전체 막대) → 끝 = 편집 창 + 항상 위 완료 창.
사용: python tests/test_ui_renderwin.py <작업폴더>"""
import os, subprocess, sys, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
import main as M  # noqa: E402
from dtme import paths, ui_render  # noqa: E402
from dtme.project import Segment  # noqa: E402
from dtme.ui_main import MainWindow  # noqa: E402
W = os.path.abspath(sys.argv[1]); os.makedirs(W, exist_ok=True)
v = os.path.join(W, "DJI_20261027104000_0001_D.MP4")
subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=8",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", v], check=True)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1400, 850); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
    return False


st, e = w.state, w.edit
e.import_files([v]); assert wait(60, lambda: st.project.sources and st.status.get(st.project.sources[0].id) == "준비")
p = st.project
p.output.folder = os.path.join(W, "out"); p.output.encoder = "x264"; p.output.gpu_decode = False
s = p.sources[0]
p.segments = [Segment(s.id, 0, 120), Segment(s.id, 120, 240)]
st.touch("segments"); wait(0.2)
e.timeline_to_render(); e.timeline_to_render()
ui_render.ask_quality = lambda *a, **k: True
rp = e.render_panel
rp._ask_folder = lambda: True
seen = {}
rp.press(); wait(0.3)
rw = w._rwin
print("작업 창:", rw is not None, "편집 창 보임:", w.isVisible(), "줄", len(rw.rows) if rw else 0)
assert rw is not None and rw.isVisible() and not w.isVisible() and len(rw.rows) == 2
assert wait(10, lambda: any(r.text != "대기" for r in rw.rows.values()))
seen["texts"] = set()


def watch():
    for r in rw.rows.values():
        seen["texts"].add(r.text.split(" ")[0])
    return not rp.running
assert wait(400, watch)
wait(0.5)
print("단계 글자:", sorted(seen["texts"]), "| 편집 창 보임:", w.isVisible(), "| 완료 창:", getattr(w, "_done_dlg", None) is not None)
assert w.isVisible() and w._rwin is None
assert {"인코딩", "완료"} <= seen["texts"] or "완료" in seen["texts"]
dd = w._done_dlg
assert dd is not None and bool(dd.windowFlags() & Qt.WindowStaysOnTopHint)
# 취소: 다시 렌더 → 작업 창 [취소] → 편집 창
for it in p.render_items:
    it.done = ""
rp.status.clear()
rp.press(); wait(0.5)
rw = w._rwin
assert rw is not None and not w.isVisible()
rw.b_cancel.click()
assert wait(60, lambda: not rp.running)
wait(0.5)
assert w.isVisible() and w._rwin is None
print("OK test_ui_renderwin", flush=True); os._exit(0)
