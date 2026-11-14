"""v0.16.91 Ctrl+A(목록·타임라인) · 전부 고른 채 컷 끌기 = 전체 밀기 · 자동 편집 창 Ctrl+A.
사용: python tests/test_ui_selectall.py <작업폴더>"""
import os, subprocess, sys, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
import main as M  # noqa: E402
from dtme import paths  # noqa: E402
from dtme.project import Segment, new_text  # noqa: E402
from dtme.ui_main import MainWindow  # noqa: E402
W = os.path.abspath(sys.argv[1]); os.makedirs(W, exist_ok=True)
vs = []
for i in range(2):
    v = os.path.join(W, f"DJI_2026102710{i}000_000{i}_D.MP4")
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=6", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", v], check=True)
    vs.append(v)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1400, 850); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
    return False


st, e = w.state, w.edit
e.import_files(vs); assert wait(60, lambda: len(st.project.sources) == 2 and all(st.status.get(s.id) == "준비" for s in st.project.sources))
p = st.project
p.segments = [Segment(s.id, 0, 150) for s in p.sources]
p.titles = [new_text(1.0, 3.0, "가"), new_text(6.0, 8.0, "나")]
st.touch("segments"); st.touch("titles"); wait(0.3)
e.set_mode("timeline"); wait(0.3)
# 소스 목록 Ctrl+A
e._set_target("src")
e.select_all(); wait(0.1)
assert len(e.src_list.selectedItems()) == 2
# 타임라인 Ctrl+A
e._set_target("cut")
e.select_all(); wait(0.2)
tl = e.timeline
assert tl.all_cuts and tl.ov_multi == {t["id"] for t in p.titles}
# 전부 고른 채 컷 끌기 → 2초 뒤로
r = tl._rects()[1]
x0, y = int(r.center().x()), int(r.center().y())
dx = int(round(2.0 * tl.pps))
QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x0, y)); wait(0.05)
QTest.mouseMove(tl, QPoint(x0 + dx // 2, y)); wait(0.05)
QTest.mouseMove(tl, QPoint(x0 + dx, y)); wait(0.05)
QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x0 + dx, y)); wait(0.3)
p = st.project
print("앞 검은 구간:", p.lead, "글자:", [(t["t0"], t["t1"]) for t in p.titles])
assert abs(p.lead - 2.0) < 0.1 and abs(p.titles[0]["t0"] - (1.0 + p.lead)) < 1e-3
# 왼쪽으로 많이 = 0 까지만
e._shift_all(-10.0); wait(0.2)
assert st.project.lead == 0.0 and abs(st.project.titles[0]["t0"] - 1.0) < 1e-3
w.undo(); wait(0.3)
assert abs(st.project.lead - 2.0) < 0.1
# 빈 곳 클릭 = 전부 고름 풀림
QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, QPoint(tl.width() - 5, tl.height() - 5)); wait(0.1)
assert not tl.all_cuts
# 자동 편집 창 Ctrl+A
from dtme.ui_autoedit import AutoEditDialog  # noqa: E402
d = AutoEditDialog(st, set(), w)
assert d.chosen() == []
d.check_all()
assert len(d.chosen()) == 2
print("OK test_ui_selectall", flush=True); os._exit(0)
