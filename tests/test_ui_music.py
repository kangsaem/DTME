"""v0.16.64 음악 화면: 넣으면 분석 → 음악 줄 파형·박자 · 이어 붙이면 겹침(크로스페이드) · 마디 첫 박 ↔ 컷 경계 자석 · [음악 자동] · 설정 창 '곡 사이 겹침'.
사용: python tests/test_ui_music.py <작업폴더>"""
import os, subprocess, sys, time  # noqa: E401
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import main as M
from dtme import paths, ui_style
from dtme.ui_main import MainWindow

W = Path(sys.argv[1]); W.mkdir(parents=True, exist_ok=True)
os.environ["DTME_FFMPEG"] = paths.ffmpeg()
if not (W / "kpop_124.mp3").exists():
    subprocess.run([sys.executable, str(Path(__file__).with_name("music_synth.py")), str(W), "short"], check=True)
clips = []
for i, d in enumerate((6, 6, 6)):
    c = W / f"DJI_202611121{i}0000_000{i}_D.MP4"
    if not c.exists():
        subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=640x360:r=30:d={d}", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(c)], check=True)
    clips.append(str(c))
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
e.import_files(clips + [str(W / "newage_66.mp3"), str(W / "kpop_124.mp3"), str(W / "ballad_72.mp3")])
assert wait(120, lambda: len(p.sources) == 3 and all(st.status.get(s.id) == "준비" for s in p.sources) and len(p.audios) == 3)
assert wait(60, lambda: len(e.music_info) == 3), "넣으면 분석"
assert e.b_mauto.isVisible() and "BPM" in e.mus_list.item(1).toolTip(), e.mus_list.item(1).toolTip()
for s in p.sources:                                         # 타임라인: 6초 × 3
    e._select_source(s.id); wait(0.3); e.to_timeline() if hasattr(e, "to_timeline") else None
if len(p.segments) < 3:
    from dtme.project import Segment
    st.checkpoint()
    p.segments = [Segment(s.id, 0, s.frames, 1.0) for s in p.sources]
    st.touch("segments")
wait(0.5)
# 1) 이어 붙이기 = 곡 사이 겹침 2초
e.mus_list.setCurrentRow(0); e._on_mus_clicked(e.mus_list.item(0)); wait(0.2)
e._on_mus_clicked(e.mus_list.item(2)); wait(0.2)
m1, m2 = p.music
assert abs((m1["t0"] + m1["len"]) - m2["t0"] - 2.0) < 1e-6, (m1, m2)
# 2) 화면: 파형·박자·X
tl = e.timeline
e.set_tl_fit(False); tl.set_zoom(40); wait(0.3)
assert tl.music_info and tl.ML == 30
tl.grab().save(str(W / "timeline_music.png"))
# 3) 자석: 곡을 컷 경계 근처로 끌면 마디 첫 박이 컷 경계(6초)에 붙음
inf = e.music_info[m1["path"]]
bar = next(b for b in inf["bars"] if b > 1.0)
want_t0 = 6.0 - (bar - m1["off"])
_k, _d, rr = next(x for x in tl._ov_rects() if x[1] is m1)
y = int(rr.center().y()); x0 = int(rr.center().x())
dx = int(round((want_t0 + 3 / tl.pps - m1["t0"]) * tl.pps))           # 3px 어긋나게
QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x0, y)); wait(0.05)
QTest.mouseMove(tl, QPoint(x0 + dx, y)); wait(0.05)
QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x0 + dx, y)); wait(0.1)
print("마디 첫 박 자석:", round(m1["t0"], 3), "목표", round(want_t0, 3))
assert abs(m1["t0"] - want_t0) < 1e-6, (m1["t0"], want_t0)
# 4) 설정 창 '곡 사이 겹침'
from dtme.ui_titles import MusicDialog
dlg = MusicDialog(p.mix, w); dlg.show(); wait(0.1)
assert "xfade" in dlg.labels and dlg.labels["xfade"][0].text() == "2.0초"
dlg.reject()
# 5) [음악 자동]: 18초 영상 → 곡 고르고 길이 맞춤(바꾸기 확인 = 바꾸기)
ui_style.confirm = lambda *a, **k: "ok"
e.b_mauto.click()
assert wait(120, lambda: e.b_mauto.isEnabled() and "음악 자동" in e.status.text()), e.status.text()
print("음악 자동:", e.status.text(), [(Path(x["path"]).stem, x["t0"], x["len"]) for x in p.music])
total = max(st_ + ln for _g, st_, ln in e._tl_cuts)
assert p.music and abs(p.music[-1]["t0"] + p.music[-1]["len"] - total) < 1e-3
st.undo(); wait(0.2)
assert len(st.project.music) == 2, "실행취소 1번"
print("OK test_ui_music"); os._exit(0)
