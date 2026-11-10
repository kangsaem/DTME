"""v0.16.34 화면 점검: 사각형 레이어(맨 아래·[확인] 후 남음·모서리 크기) · 전환 구간 끝 끌기(길이·실행취소) · 전환 이름.
사용: python tests/test_ui_v1634.py"""
import os, subprocess, sys, tempfile, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import main as M
from dtme import paths
from dtme.project import TRANSITIONS
from dtme.ui_main import MainWindow
from dtme.ui_titles import RectDialog
mp4 = os.path.join(tempfile.mkdtemp(), "v1634.mp4")
subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", mp4], check=True)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1800, 1000); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond():
            return True


st, e = w.state, w.edit
e.import_files([mp4]); wait(60, lambda: st.project.sources and st.status.get(st.project.sources[0].id) == "준비")
src = st.project.sources[0]
for a, b in ((0, 60), (60, 120), (120, 180)):
    src.sel_in, src.sel_out = a, b; e.send_to_timeline()
wait(0.3)
# 1) 사각형: 글자 뒤에 만들어도 맨 아래(목록 맨 앞), [확인] 해도 남음
e.add_text(); wait(0.2); e._dlg.text.setPlainText("ABC"); e._dlg.accept(); wait(0.2)
e.add_rect(); wait(0.3)
dlg = e._dlg
assert isinstance(dlg, RectDialog)
assert st.project.titles[0]["kind"] == "rect" and st.project.titles[1]["kind"] == "text"
dlg._set("opacity", 0.8); dlg.accept(); wait(0.2)
rc = st.project.titles[0]
assert rc["kind"] == "rect" and abs(rc["opacity"] - 0.8) < 1e-6 and rc["t0"] == 0.0
print("사각형:", {k: rc[k] for k in ("cx", "cy", "w", "h", "opacity")})
# 2) 전환 끝 끌기
segs = st.project.segments
segs[1].trans = {"type": "wipeleft", "dur": 1.0}; st.touch("segments"); wait(0.3)
e.zoom.setValue(120); wait(0.3)
tl = e.timeline
r = dict(tl._trans_rects())[segs[1].id]
y = int(r.center().y())
x0 = int(r.left())
QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x0, y)); wait(0.05)
QTest.mouseMove(tl, QPoint(int(x0 - 0.5 * tl.pps), y)); wait(0.05)
QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(x0 - 0.5 * tl.pps), y)); wait(0.2)
d = st.project.segments[1].trans["dur"]
print("전환 길이 끌기:", d)
assert abs(d - 1.5) < 0.11, d
w.undo(); wait(0.3)
assert abs(st.project.segments[1].trans["dur"] - 1.0) < 1e-6
# 3) 이름
TN = dict(TRANSITIONS)
assert TN["wipeleft"] == "우 → 좌" and TN["wiperight"] == "좌 → 우"
print("UI V1634 OK")
os._exit(0)
