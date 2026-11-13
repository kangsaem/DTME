"""v0.16.76: 실행취소 = 작업 이름 표시 · 자동 편집·전체 삭제는 되돌리기 전에 확인 · [다시 실행] 버튼 · 자동 저장 최근 10개 + [되살리기].
사용: python tests/test_ui_v1676.py <작업폴더>"""
import os, subprocess, sys, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication, QToolBar
import main as M
from dtme import paths, ui_style
from dtme.project import Segment
from dtme.ui_main import MainWindow
WORK = os.path.abspath(sys.argv[1]); os.makedirs(WORK, exist_ok=True)
v = os.path.join(WORK, "c.mp4")
subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=10", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", v], check=True)
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
s = st.project.sources[0]
tb = w.findChild(QToolBar)
names = [a.text() for a in tb.actions() if a.text()]
assert "다시 실행" in names and "되살리기" in names, names
# 자동 편집처럼 큰 작업 → 되돌리기 전 확인
st.checkpoint(label="자동 편집"); st.project.segments = [Segment(s.id, 0, 150), Segment(s.id, 150, 300)]; st.touch("segments"); wait(0.1)
e._key("down"); wait(0.1)                               # 컷 추가
assert st.undo_label() == "컷 추가"
w.undo(); wait(0.1)
assert len(st.project.segments) == 2 and "실행취소: 컷 추가" in e.status.text(), e.status.text()
asked = []
ui_style.confirm = lambda parent, text, btns: (asked.append(text), "cancel")[1]
w.undo(); wait(0.1)
assert asked == ["자동 편집 전으로 돌아갈까요?"] and len(st.project.segments) == 2, "취소 = 안 되돌림"
ui_style.confirm = lambda parent, text, btns: "ok"
w.undo(); wait(0.1)
assert not st.project.segments and "실행취소: 자동 편집" in e.status.text()
w.redo(); wait(0.1)
assert len(st.project.segments) == 2 and "다시 실행: 자동 편집" in e.status.text()
# 전체 삭제도 확인
asked.clear(); ui_style.confirm = lambda parent, text, btns: (asked.append(text), "ok")[1]
e.clear_timeline(); wait(0.1); w.undo(); wait(0.1)
assert asked == ["전체 삭제 전으로 돌아갈까요?"] and len(st.project.segments) == 2
# 자동 저장 = 5분마다 하나씩, 최근 10개
for f in w.autosave_dir().glob("*.dtme.json"):
    f.unlink()
st.dirty = True
w._hist_t = 0.0; w._do_autosave()
src = sorted(w.autosave_dir().glob("*.dtme.json"))[-1]
for k in range(12):                                     # 예전 것 12개(이름 = 시각)
    (w.autosave_dir() / f"20261112_{10 + k:02d}0000.dtme.json").write_bytes(src.read_bytes())
w._hist_t = 0.0; w._do_autosave()                       # 새로 하나 + 정리(최근 10개)
lst = w.autosave_list()
assert len(lst) == w.AUTOSAVE_KEEP and "컷 2" in lst[0][1], (len(lst), [x[1] for x in lst])
# 되살리기 = 고른 것
st.checkpoint(); st.project.segments = []; st.touch("segments"); st.dirty = False
assert w.restore_autosave(lst[0][0]) and len(st.project.segments) == 2
print("OK test_ui_v1676", flush=True); os._exit(0)
