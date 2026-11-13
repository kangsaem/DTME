"""v0.16.74: 자동 편집·AUTO 작업 중 = 편집 창 숨김, 작업 창만 작업 표시줄(주인 없는 창 · [−]), 끝·취소 = 편집 창 원래대로.
사용: python tests/test_ui_v1674.py <작업폴더>"""
import os, subprocess, sys, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication
import main as M
from dtme import paths, ui_style
from dtme.ui_main import MainWindow
WORK = os.path.abspath(sys.argv[1]); os.makedirs(WORK, exist_ok=True)
vids = []
for i in range(2):
    v = os.path.join(WORK, f"k{i}.mp4")
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=12", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", v], check=True)
    vids.append(v)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1500, 850); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
    return False


st, e = w.state, w.edit
e.import_files(vids); assert wait(90, lambda: len(st.project.sources) == 2 and all(st.status.get(s.id) == "준비" for s in st.project.sources))
for s in st.project.sources:
    s.auto = {"preset": "shallow", "by": "user"}
ui_style.confirm = lambda *a, **k: "ok"
from dtme.ui_autoedit import AutoEditDialog
# 1) 자동 편집: 시작 = 편집 창 숨김, 자동 편집 창 = 주인 없는 창 + [−] / 끝 = 편집 창 다시
dlg = AutoEditDialog(st, {s.id for s in st.project.sources}, e); dlg.show(); wait(0.2)
dlg.length.setValue(1)
assert not dlg.b_min.isVisible()
e.run_autoedit(dlg, dlg.settings()); wait(0.2)
hidden = not w.isVisible()
print("작업 중: 편집 창 숨김", hidden, "· 주인 없음", dlg.parent() is None, "· [−]", dlg.b_min.isVisible())
assert hidden and dlg.parent() is None and dlg.b_min.isVisible() and dlg.isVisible()
dlg.b_min.click(); wait(0.1)                       # 내리기
assert wait(120, lambda: w.isVisible()), "끝나면 편집 창"
assert not dlg.isVisible() and st.project.segments
# 2) 자동 편집 [취소] = 편집 창 다시
dlg2 = AutoEditDialog(st, {s.id for s in st.project.sources}, e); dlg2.show(); wait(0.2)
e.run_autoedit(dlg2, dlg2.settings()); wait(0.2)
assert not w.isVisible()
dlg2._cancel(); wait(0.3)
assert w.isVisible() and not dlg2.isVisible()
# 3) AUTO 창: [보정+편집] 누른 뒤 분석 기다림 = 편집 창 숨김 / 작업 중 [취소] = 편집 창 + AUTO 창 남음
for s in st.project.sources:
    s.auto = {}
ad = e.make_auto_dialog(); ad.show(); wait(0.2)
for r in ad.rows:
    r.result, r.prog = None, 0.0
ad.mode = "each"
e._auto_start(ad); wait(0.1)
print("AUTO 분석 기다림: 편집 창 숨김", not w.isVisible(), "· AUTO 창", ad.isVisible(), ad.parent() is None)
if ad.busy:
    assert not w.isVisible() and ad.isVisible() and ad.parent() is None
    ad.cancel(); wait(0.3)
    assert w.isVisible() and ad.isVisible() and not ad.busy
ad.reject()
print("OK test_ui_v1674", flush=True); os._exit(0)
