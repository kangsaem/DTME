"""v0.16.40: 슬라이더를 끄는 동안 모니터 보정 화면이 따라감(한 번에 1개, 마지막 값으로 끝남) · 묵은 요청은 ffmpeg 를 안 띄움.
사용: python tests/test_ui_live.py"""
import os, subprocess, sys, tempfile, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication
import main as M
from dtme import ff, paths
from dtme.ui_main import MainWindow
d = tempfile.mkdtemp(); v = os.path.join(d, "k0.mp4")
subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", v], check=True)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1700, 950); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond():
            return True


st, e, gp = w.state, w.edit, w.edit.grade
e.import_files([v]); wait(60, lambda: len(st.project.sources) == 1 and st.status.get(st.project.sources[0].id) == "준비")
s = st.project.sources[0]; e._select_source(s.id); wait(1.5)
e.player.seek(30); wait(2.5, lambda: e.player.overlay_frame == 30)
assert e.player.overlay_frame == 30, e.player.overlay_frame

made = []
orig = ff._render_preview
ff._render_preview = lambda c, g: (made.append(round(float((g or {}).get("r_gain", 0)), 3)), orig(c, g))[1]
shown = []
osi = e.player.show_image
e.player.show_image = lambda im: (shown.append(1), osi(im))[1]
# 1) 끄는 동안(0.25초 안 멈춤) 화면이 바뀜 = 예전엔 멈춘 뒤에만
t0 = time.time(); k = 0
while time.time() - t0 < 2.0:
    k += 1
    gp._set("r_gain", 1.10 + 0.005 * k, slider=True); wait(0.03)
last = round(1.10 + 0.005 * k, 3)
live_shown = len(shown)
assert live_shown >= 1, "끄는 동안 화면이 한 번도 안 바뀜"
assert len(made) < k, (len(made), k)                     # 값마다 만들지 않음(한 번에 1개)
wait(4, lambda: not e._live_busy and not gp._debounce.isActive()); wait(1.0)
assert made[-1] == last, (made[-3:], last)               # 마지막 값으로 끝남
assert made.count(last) == 1, made[-4:]                  # v0.16.54: 손을 뗀 뒤 같은 값으로 한 번 더 만들지 않음
assert not e._live_busy and not e._live_pending
print(f"끄는 동안: 값 {k}번 → 만든 화면 {len(made)} · 끄는 중 표시 {live_shown}")
# 2) 묵은 요청 = 안 만듦
made.clear()
for i in range(8):
    gp._set("b_gain", 1.0 + 0.01 * i); 
wait(4, lambda: False)
assert len(made) <= 5, made                              # 8번 요청 중 풀(4)에 바로 들어간 것 말고는 건너뜀
# 2-1) v0.16.54: 같은 화면을 만드는 중에 또 요청(손을 뗀 직후) = 새로 안 만들고 그 결과를 표시
slow = ff._render_preview
ff._render_preview = lambda c, g: (time.sleep(0.8), slow(c, g))[1]
gp._write("r_gain", 1.777); made.clear(); shown.clear()
e._live_busy = True
assert e.request_preview(live=True) is True
wait(0.2)
assert e.request_preview() is True                       # 멈춘 뒤 요청(같은 값)
wait(6, lambda: not e._live_busy and shown); wait(1.2)
assert made == [1.777], made                             # 예전 = 2번 만들고 먼저 것은 버림
assert len(shown) == 1 and not e._live_busy and not e._pv_flight, (shown, e._live_busy)
ff._render_preview = slow
print("같은 화면 겹친 요청: 1번만 만듦")
# 3) 실행취소 = 끌기 1번
print("OK test_ui_live")
os._exit(0)
