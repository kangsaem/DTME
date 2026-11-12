"""v0.16.66 화면: 타임라인에 올리면 컷마다 원본 소리 판단 → 스피커 표시 · 말풍선 · 컷 우클릭(자동/키움/키우지 않음, 실행취소) · 음악 설정 창 2줄.
사용: python tests/test_ui_loud.py <작업폴더>(test_loud.py 가 만든 클립 사용)"""
import os, sys, time  # noqa: E401
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication
import main as M
from dtme.project import Segment
from dtme.ui_main import MainWindow
from dtme.ui_titles import MusicDialog

W = Path(sys.argv[1])
names = ["land_talk", "underwater", "surface_quiet", "red_breath"]
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond():
            return True
    return False


st, e = w.state, w.edit
p = st.project
e.import_files([str(W / f"{n}.mp4") for n in names])
assert wait(120, lambda: len(p.sources) == 4 and all(st.status.get(s.id) == "준비" for s in p.sources))
by = {Path(s.path).stem: s for s in p.sources}
st.checkpoint()
p.segments = [Segment(by[n].id, 0, by[n].frames, 1.0) for n in names]
st.touch("segments")
assert wait(60, lambda: all(g.loud is not None for g in st.project.segments)), [g.loud for g in st.project.segments]
got = [(g.loud, g.why) for g in st.project.segments]
print("판단:", got)
assert got == [(True, "말소리"), (False, "호흡기"), (True, "수면 위"), (False, "호흡기")]
tl = e.timeline
assert [tl.loud[g.id][0] for g in st.project.segments] == [True, False, True, False]
x1 = tl._rects()[1].center().x()
assert "안 키움(호흡기)" in tl.tooltip_at(x1), tl.tooltip_at(x1)
tl.set_zoom(60); wait(0.3)
tl.grab().save(str(W / "timeline_loud.png"))
# 컷 우클릭 → 키움(직접)
g1 = st.project.segments[1]
e.set_cut_aud(g1.id, "up"); wait(0.1)
g1 = st.project.segments[1]
assert g1.aud == "up" and tl.loud[g1.id] == (True, "up", "호흡기")
st.undo(); wait(0.2)
assert st.project.segments[1].aud == "auto", "실행취소"
dlg = MusicDialog(p.mix, w); dlg.show(); wait(0.1)
assert dlg.labels["up_orig"][0].text() == "100%" and dlg.labels["up_music"][0].text() == "30%"
dlg.grab().save(str(W / "music_dialog.png")); dlg.reject()
print("OK test_ui_loud"); os._exit(0)
