"""v0.16.78: 타임라인 맞춤(전체가 화면 폭에, 직접 확대하면 꺼짐, [맞춤]) · 음악·사진 = 목록 먼저, 길이·크기는 뒤에서.
사용: python tests/test_ui_v1678.py <작업폴더>"""
import os, subprocess, sys, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication
import main as M
from dtme import paths
from dtme.project import Segment
from dtme.ui_main import MainWindow
W = os.path.abspath(sys.argv[1]); os.makedirs(W, exist_ok=True)
FF = paths.ffmpeg()
v = os.path.join(W, "c.mp4")
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=60", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", v], check=True)
songs = []
for i in range(3):
    f = os.path.join(W, f"s{i}.mp3")
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f={300 + 100 * i}:d={20 + 5 * i}", f], check=True)
    songs.append(f)
pics = []
for i in range(3):
    f = os.path.join(W, f"p{i}.png")
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=400x300", "-frames:v", "1", f], check=True)
    pics.append(f)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1500, 850); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
    return False


st, e = w.state, w.edit
e.import_files([v]); assert wait(60, lambda: st.project.sources and st.status.get(st.project.sources[0].id) == "준비")
# 1) 음악·사진 = 목록 먼저(바로), 길이·크기는 뒤에서
t0 = time.time()
st.import_files(songs + pics)
dt = time.time() - t0
p = st.project
print("넣는 데", round(dt, 3), "초")
assert len(p.audios) == 3 and len(p.images) == 3
assert all(a["dur"] == 0 for a in p.audios) and all(st.img_status.get(a["id"]) == "읽는 중" for a in p.audios)
assert all(st.img_status.get(m.id) == "읽는 중" for m in p.images)
# 읽기 전에 넣은 곡 = 임시 길이 → 읽히면 실제 길이
e.add_music_at(p.audios[0]["id"], 0.0, snap=False)
assert st.project.music[0].get("_pending")
assert wait(30, lambda: all(a["dur"] > 0 for a in st.project.audios) and all(st.project.image(m.id).width for m in st.project.images))
m0 = st.project.music[0]
assert abs(m0["len"] - 20.0) < 0.3 and "_pending" not in m0, m0
assert all(not st.img_status.get(m.id) for m in st.project.images)
# 2) 타임라인 맞춤
s = st.project.sources[0]
tl = e.timeline
st.project.segments = [Segment(s.id, 0, 1800)]                   # 60초
st.touch("segments"); wait(0.3)
vw = e.tl_scroll.viewport().width()
assert e._tl_fit and tl.total() * tl.pps <= vw, (tl.total(), tl.pps, vw)
for k in range(4):                                                # 컷을 더 넣어도 = 전체가 보임
    e._key("down"); wait(0.2)
assert tl.total() * tl.pps <= vw and e.zoom.value() <= 5, (tl.pps, e.zoom.value())
e.zoom.setValue(60); wait(0.1)                                    # 직접 확대 = 맞춤 끔
assert not e._tl_fit and tl.pps == 60
e._key("down"); wait(0.2)
assert tl.pps == 60
e.b_fit.click(); wait(0.2)
assert e._tl_fit and tl.total() * tl.pps <= vw
print("OK test_ui_v1678", flush=True); os._exit(0)
