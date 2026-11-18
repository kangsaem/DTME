"""v0.17.2 화면: 자동 창 B안(두 줄 다 펼침 · 1400×720 · 끈 단계 = 설정 흐림) · 길이 = 직접 지정 + '곡 길이에 맞춤' 체크(칸 숫자 = 곡 길이) ·
곡이 영상보다 길면 곡을 늦게(마디 단위로) 시작 → 곡 끝 = 영상 끝(사용자 11/18: 곡 끝 15초 잘림).
사용: python tests/test_ui_v1720.py <작업폴더>"""
import os, subprocess, sys, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication  # noqa: E402
import main as M  # noqa: E402
from dtme import autoedit, ff, music, paths, ui_style  # noqa: E402
from dtme.project import Project, cut_spans, get_setting, set_setting  # noqa: E402
WORK = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "v1720_test"); os.makedirs(WORK, exist_ok=True)
vids = []
for n in ("DJI_20251020094016_0010_D.MP4", "DJI_20251020101500_0011_D.MP4", "DJI_20251020111000_0012_D.MP4"):
    v = os.path.join(WORK, n)
    if not os.path.exists(v):
        subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=20", "-f", "lavfi", "-i",
                        "sine=d=20", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", v], check=True)
    vids.append(v)
song = os.path.join(WORK, "long song.wav")
if not os.path.exists(song):                       # 120 BPM 딸깍 90초(영상 60초보다 김)
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='0.4*sin(2*PI*110*t)*lt(mod(t,0.5),0.08)+0.1*sin(2*PI*330*t)':d=90:s=22050", song], check=True)
from dtme.ui_main import MainWindow  # noqa: E402
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1500, 850)


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
    return False


st, e = w.state, w.edit
ui_style.confirm = lambda *a, **k: "ok"
st.set_project(Project()); st.defer_proxy = True
set_setting("autowin", {"len_mode": "song", "len_sec": 120})       # 예전(v0.17.1) 기억 = 곡에 맞춤 → 이제는 안 따름
d = e.make_auto_window(from_edit=False); d.show(); wait(0.3)

# ---------------------------------------------------------------- 1) B안: 두 줄 다 펼침
assert (d.width(), d.height()) == (1400, 720), (d.width(), d.height())
assert all(d.stages[k].body.isVisible() for k in d.stages)
xs = {k: d.stages[k].mapTo(d, d.stages[k].rect().topLeft()) for k in d.stages}
assert xs["grade"].x() == xs["edit"].x() < xs["music"].x() == xs["render"].x(), xs          # 왼쪽 보정·편집 · 오른쪽 음악·렌더
assert xs["grade"].y() < xs["edit"].y() and xs["music"].y() < xs["render"].y()
assert d.stages["edit"].geometry().bottom() < d.height() - 40, "스크롤 없이 들어감"
d.add_paths(vids + [song])
assert wait(60, lambda: len(st.project.sources) == 3 and all(s.frames for s in st.project.sources))
assert wait(30, lambda: any(float(a.get("dur") or 0) not in (0.0, 600.0) for a in st.project.audios if not a.get("builtin")))
wait(0.6); d._sync()
d.stages["render"].set_on(False); d._sync()
assert not d.stages["render"].body.isEnabled() and d.stages["edit"].body.isEnabled()       # 끈 단계 = 설정 흐림
d.stages["edit"].set_on(False); d._sync()
assert not d.stages["music"].body.isEnabled(), "편집 끔 = 음악 못 켬 → 설정도 흐림"
d.stages["edit"].set_on(True); d._sync()
assert d.stages["music"].body.isEnabled()
# 머리 줄 아무 데나 누름 = 켬/끔
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
QTest.mouseClick(d.stages["render"].head, Qt.LeftButton, Qt.NoModifier, QPoint(200, 10)); wait(0.1)
assert d.stages["render"].on
QTest.mouseClick(d.stages["render"].head, Qt.LeftButton, Qt.NoModifier, QPoint(200, 10)); wait(0.1)
assert not d.stages["render"].on
d.grab().save(os.path.join(WORK, "autowin_b.png"))

# ---------------------------------------------------------------- 2) 길이: 기억된 '곡에 맞춤'은 안 따름 · 체크 = 칸 숫자가 곡 길이
lb = d.length
assert lb.mode() == "manual" and not lb.song.isChecked() and lb.edit.text() == "2:00" and lb.song.isEnabled()
lb.song.setChecked(True); d._sync()
sg = d.song_seconds()
print("곡 길이에 맞춤: 칸", lb.edit.text(), "· 곡", round(sg, 1), "· 요약", d.sum.text())
assert lb.mode() == "song" and not lb.edit.isEnabled()
from dtme.ui_autowin import mmss  # noqa: E402
assert lb.edit.text() == mmss(sg + autoedit.END_SEC) and d.sum.text().endswith(f"→ {mmss(sg + autoedit.END_SEC)}(곡)")
lb.song.setChecked(False); d._sync()
assert lb.edit.text() == "2:00" and lb.edit.isEnabled()                                       # 끄면 원래 숫자
lb.song.setChecked(True); d._sync()

# ---------------------------------------------------------------- 3) 곡(90초) > 영상(60초) = 곡을 늦게 시작 → 곡 끝 = 영상 끝
for k, on in (("grade", False), ("edit", True), ("music", True), ("render", False)):
    d.stages[k].set_on(on)
d._sync()
d.b_start.click()
assert wait(600, lambda: d.outcome == "edit"), (d._step, d.state_lab.text())
p = st.project
vend = max(t + ln for _c, t, ln in cut_spans(p))
m = p.music[0]
inf = music.get(song)
print("영상 끝", round(vend, 2), "· 음악", [(round(x["t0"], 2), round(x["off"], 2), round(x["len"], 2)) for x in p.music], "· 곡", inf["dur"],
      "· 마디", round(autoedit.bar_len(inf), 3))
assert len(p.music) == 1 and m["t0"] == 0.0 and m["off"] > 20.0                               # 도입부를 건너뜀(늦게 시작)
assert abs(music.music_end(p.music) - vend) < 0.1 and abs(m["off"] + m["len"] - inf["dur"]) < 0.2, "곡 끝 = 영상 끝(안 잘림)"
bl = autoedit.bar_len(inf)
k = (m["off"] - float(inf.get("lead", 0.0))) / bl
log = open(paths.cache_dir() / "dtme.log", encoding="utf-8").read().splitlines()
ln = [x for x in log if "자동 편집 길이:" in x][-1]
print(ln[-260:])
assert "늦게 시작(영상 모자람)" in ln and "단계별 영상 끝" in ln
assert get_setting("autowin", {}).get("len_mode") is None
print("OK test_ui_v1720", flush=True)
os._exit(0)
