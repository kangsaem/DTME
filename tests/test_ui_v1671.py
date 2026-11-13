"""v0.16.71: 앞뒤 검은 구간 자동 — 글자를 0초 앞으로 끌면 앞 검은 구간(모두 뒤로), 다시 안쪽으로 끌면 줄어듦,
영상 끝을 넘은 글자 = 뒤 검은 구간. 타임라인 표시 · 모니터 검정 · 렌더 길이·검정.
사용: python tests/test_ui_v1671.py <작업폴더>"""
import os, subprocess, sys, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
import numpy as np
import main as M
from dtme import ff, paths
from dtme.project import Project, Segment, new_text
from dtme.ui_main import MainWindow
WORK = os.path.abspath(sys.argv[1]); os.makedirs(WORK, exist_ok=True)
FF = paths.ffmpeg()
# 엔진: normalize_lead
q = Project()
q.titles = [new_text(-2.0, 0.5, "a"), new_text(3.0, 4.0, "b")]
assert q.normalize_lead() and q.lead == 2.0 and q.titles[0]["t0"] == 0.0 and q.titles[1]["t0"] == 5.0
q.titles[0].update(t0=3.0, t1=5.5)
assert q.normalize_lead() and q.lead == 0.0 and q.titles[0]["t0"] == 1.0 and q.titles[1]["t0"] == 3.0
assert not q.normalize_lead()

v = os.path.join(WORK, "c.mp4")
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x808080:s=640x360:r=30:d=12", "-f", "lavfi", "-i", "sine=d=12",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", v], check=True)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1600, 900); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
    return False


st, e, tl = w.state, w.edit, w.edit.timeline
e.import_files([v]); assert wait(60, lambda: st.project.sources and st.status.get(st.project.sources[0].id) == "준비")
p = st.project
s = p.sources[0]
p.segments = [Segment(s.id, 0, 150), Segment(s.id, 150, 300)]          # 5초 + 5초
ta = new_text(1.0, 3.0, "A"); tb = new_text(9.0, 12.0, "B")           # B = 영상 끝(10초) 넘음 → 뒤 2초
p.titles = [ta, tb]
st.touch("segments"); st.touch("titles"); wait(0.3)
assert tl.pads == (0.0, 10.0, 12.0) and e.tl_len.text() == "12.0초", (tl.pads, e.tl_len.text())
e.set_tl_fit(False); tl.set_zoom(30.0); wait(0.1)


def mouse(kind, pos):
    ev = QMouseEvent(kind, QPointF(pos), QPointF(tl.mapToGlobal(QPoint(int(pos.x()), int(pos.y())))),
                     Qt.LeftButton if kind != QMouseEvent.Type.MouseMove else Qt.NoButton,
                     Qt.LeftButton if kind != QMouseEvent.Type.MouseButtonRelease else Qt.NoButton, Qt.NoModifier)
    app.sendEvent(tl, ev)


def drag(d, dx):
    r = next(r for k, x, r in tl._ov_rects() if x is d)
    a = r.center()
    mouse(QMouseEvent.Type.MouseButtonPress, a)
    for k in range(1, 6):
        mouse(QMouseEvent.Type.MouseMove, QPointF(a.x() + dx * k / 5, a.y()))
    mouse(QMouseEvent.Type.MouseButtonRelease, QPointF(a.x() + dx, a.y()))
    wait(0.2)


nu = len(st._undo)
drag(ta, -90)                                            # 3초 왼쪽 → t0 = −2 → 앞 검은 구간 2초
p = st.project
A = next(x for x in p.titles if x["text"] == "A"); B = next(x for x in p.titles if x["text"] == "B")
assert abs(p.lead - 2.0) < 0.05 and abs(A["t0"]) < 1e-6 and abs(B["t0"] - (9.0 + p.lead)) < 1e-6, (p.lead, A, B)
assert abs(e._tl_cuts[0][1] - p.lead) < 1e-6 and abs(tl.pads[0] - p.lead) < 1e-6
assert len(st._undo) == nu + 1
tl.grab().save(os.path.join(WORK, "lead_tl.png"))
# 모니터: 검은 구간 = 검정
e._on_tl_time(1.0); wait(0.5)
assert e._tl_gap
img = e.player.mon.img if hasattr(e.player.mon, "img") else None
# 검은 구간 재생 = 시간만 흐름
e._key("space"); wait(0.4)
assert e._gap_timer.isActive() and e.tl_time > 1.2
e._key("space"); wait(0.1); assert not e._gap_timer.isActive()
# 렌더: 길이 = 2 + 10 + 2, 앞 1초 = 검정, 6초 = 회색
e.timeline_to_render(); wait(0.2)
it = p.render_items[-1]
assert abs(it.lead - p.lead) < 1e-6
out = os.path.join(WORK, "lead.mp4")
p.output.encoder = "x264"
ff.render_video(p, it.segs, out, None, None, it.orientation, True, extras={"titles": it.titles, "music": it.music, "mix": it.mix, "lead": it.lead})
d = ff.probe(out)
dur = d["frames"] / float(d["fps_num"]) * d["fps_den"]
print("렌더 길이", round(dur, 2), "lead", p.lead)
assert abs(dur - (p.lead + 12.0)) < 0.15, dur


def luma(t):
    r = subprocess.run([FF, "-v", "error", "-ss", f"{t}", "-i", out, "-frames:v", "1", "-vf", "scale=64:36,format=gray", "-f", "rawvideo", "-"],
                       capture_output=True)
    return float(np.frombuffer(r.stdout, np.uint8).mean())


y0, y1, y2 = luma(0.5), luma(p.lead + 4.0), luma(p.lead + 11.5)
print("밝기 앞·가운데·뒤", y0, y1, y2)
assert y0 < 25 and y1 > 90 and y2 < 40, (y0, y1, y2)
# 다시 안쪽으로 끌면 앞 검은 구간 줄어듦
A = next(x for x in st.project.titles if x["text"] == "A")
drag(A, 150)                                             # +5초 → A 5초, B 11+ → 가장 앞 = 5 → 앞 구간 2초 다 줄임
p = st.project
assert p.lead == 0.0 and abs(next(x for x in p.titles if x["text"] == "A")["t0"] - 3.0) < 0.05, (p.lead, p.titles)
w.undo(); wait(0.2)
assert abs(st.project.lead - 2.0) < 0.05
print("OK test_ui_v1671", flush=True); os._exit(0)
