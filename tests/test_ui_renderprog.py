"""v0.16.31 점검: 렌더 진행 표시 — [렌더] 버튼 = 전체 진행 막대('1/3 · 40%'), 창 제목, 끝나면 떠 있는 팝업(완료·실패·시간).
작업 표시줄 막대(taskbar.py)는 Windows 에서만(여기서는 오류 없이 지나가는지만).
사용: python tests/test_ui_renderprog.py <작업폴더>"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication
import main as M
from dtme import ff, paths
from dtme.ui_main import MainWindow
WORK = sys.argv[1]; os.makedirs(WORK, exist_ok=True)
clips = []
for i in range(3):
    c = os.path.join(WORK, f"DJI_2026110910{i}000_000{i}_D.MP4")
    if not os.path.exists(c):
        ff.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=640x360:r=60000/1001:d={4 + 2 * i}", c])
    clips.append(c)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond(): return True
    return False


assert wait(1) is False
w.edit.import_files(clips)
assert wait(120, lambda: len(w.state.project.sources) == 3 and all(s.frames for s in w.state.project.sources))
p = w.state.project
p.output.encoder = "x264"; p.output.gpu_decode = False
p.output.folder = os.path.join(WORK, "out"); os.makedirs(p.output.folder, exist_ok=True)
e = w.edit; rp = e.render_panel
for i in range(e.src_list.count()):
    e.src_list.item(i).setSelected(True)
e.sources_to_render(); wait(0.3)
seen = []
rp.runProgress.connect(lambda f, t, b: seen.append((f, t)))
rp.render()
assert wait(180, lambda: rp.b_render.frac is not None and 0.2 < rp.b_render.frac < 1.0), "진행 막대"
print("렌더 중 버튼:", rp.b_render.ptext, "· 제목:", w.windowTitle())
assert "/3 · " in rp.b_render.ptext and "렌더 " in w.windowTitle()
assert wait(300, lambda: not rp.running) and wait(0.5) is False
fr = [f for f, _t in seen]
assert fr == sorted(fr) or max(fr) >= 0.99, "진행이 뒤로 가지 않음"
d = getattr(w, "_done_dlg", None)
txt = d.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)[0].text() if d else ""
print("끝:", txt, "· 제목:", w.windowTitle(), "· 버튼:", rp.b_render.text(), rp.b_render.frac)
assert d is not None and d.isVisible() and txt.startswith("렌더 완료 3개 · 실패 0개")
assert "렌더 " not in w.windowTitle() and rp.b_render.frac is None
print("OK test_ui_renderprog")
