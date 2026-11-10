"""v0.16.35 ◆ 화면: 종류별 색·활성 · key◀▶ · ◆ 클릭 → 보정 줄 · 칩 X · 전체◆ · 프리셋 확인(전체/이 프레임/취소).
사용: python tests/test_ui_v1635.py"""
import os, subprocess, sys, tempfile, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication
import main as M
from dtme import paths, ui_style
from dtme.ui_main import MainWindow
d = tempfile.mkdtemp(); vids = []
for i in range(2):
    v = os.path.join(d, f"k{i}.mp4")
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=20",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", v], check=True); vids.append(v)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1700, 950); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond():
            return True


st, e, gp, sb = w.state, w.edit, w.edit.grade, w.edit.sbar
e.import_files(vids); wait(60, lambda: len(st.project.sources) == 2 and all(st.status.get(x.id) == "준비" for x in st.project.sources))
s = st.project.sources[0]
e._select_source(s.id) if hasattr(e, "_select_source") else None
wait(0.3)
assert e._cur() is s or e._cur().id == s.id
s = e._cur()
c1 = [[0, 0], [0.3, 0.4], [1, 1]]; c2 = [[0, 0], [1, 1]]
s.gkeys = {"r_gain": [{"f": 0, "v": 1.1}, {"f": 270, "v": 1.2}, {"f": 450, "v": 1.05}],
           "b_gain": [{"f": 0, "v": 1.0}, {"f": 270, "v": 0.95}, {"f": 450, "v": 1.0}],
           "curve": [{"f": 0, "v": c1}, {"f": 60, "v": c2}, {"f": 90, "v": c2}]}
s.auto = {"preset": "shallow", "by": "auto", "rec": "shallow", "nkeys": 5}
e._refresh_marks(); gp._load_controls(); wait(0.2)
assert set(sb.gtypes) == {"r_gain", "b_gain", "curve"} and sb._gx(0) >= 6
# 1) 종류 없이 key▶ = 모든 ◆, 도착 = 그 종류 테두리(필터 없음)
e.player.seek(0); wait(0.3)
e.goto_gkey(1); wait(0.3)
assert e.player.frame == 60 and gp.marked == ["curve"] and gp.active == [], (e.player.frame, gp.marked, gp.active)
# 2) 빨강 슬라이더 만짐 = 빨강 활성 → key▶ 는 빨강만
gp._touch("r_gain"); wait(0.1)
assert gp.active == ["r_gain"] and sb.active == ["r_gain"]
e.goto_gkey(1); wait(0.3); assert e.player.frame == 270, e.player.frame
e.goto_gkey(1); wait(0.3); assert e.player.frame == 450
e.goto_gkey(-1); wait(0.3); assert e.player.frame == 270
# 3) 칩 X = 전체
sb.activeCleared.emit(); wait(0.1); assert gp.active == [] and sb.active == []
# 4) ◆ 클릭 = 그 프레임 종류 활성
e._gkey_clicked(270); wait(0.1); assert gp.active == ["r_gain", "b_gain"] and sb.active == ["r_gain", "b_gain"]
# 5) 전체◆: 빨강 ◆ 모두 +0.05, 위치 그대로, 실행취소
assert gp.b_all.isEnabled()
gp.b_all.setChecked(True)
e.player.seek(270); wait(0.3)
gp._set("r_gain", 1.25, slider=True); wait(0.4)
vals = [round(k["v"], 3) for k in s.gkeys["r_gain"]]
print("전체◆ 후 빨강:", vals); assert vals == [1.15, 1.25, 1.1] and [k["f"] for k in s.gkeys["r_gain"]] == [0, 270, 450]
assert [k["v"] for k in s.gkeys["b_gain"]] == [1.0, 0.95, 1.0]
w.undo(); wait(0.3); s = e._cur()
assert [round(k["v"], 3) for k in s.gkeys["r_gain"]] == [1.1, 1.2, 1.05]
# 6) 클립 바꾸면 전체◆ 꺼짐·활성 없앰
gp.b_all.setChecked(True)
other = [x for x in st.project.sources if x.id != s.id][0]
gp.set_current_source(other.id); wait(0.1)
assert not gp.b_all.isChecked() and gp.active == []
gp.set_current_source(s.id); wait(0.1)
# 7) 프리셋 확인: 취소 / 이 프레임 / 전체
asked = []
orig = ui_style.confirm
for ans in ("cancel", "frame", "all"):
    ui_style.confirm = lambda parent, text, btns, a=ans: (asked.append((text, [b[1] for b in btns])), a)[1]
    s = e._cur()
    before = {k: [dict(x) for x in v] for k, v in s.gkeys.items()}
    e.player.seek(150); wait(0.3)
    gp.apply_choice("deep", "mid"); wait(0.3)
    s = e._cur()
    if ans == "cancel":
        assert s.gkeys == before
    elif ans == "frame":
        assert any(x["f"] == 150 for x in s.gkeys["r_gain"]) and any(x["f"] == 0 for x in s.gkeys["r_gain"]), s.gkeys["r_gain"]
        assert s.auto.get("by") == "auto"
    else:
        assert s.gkeys == {} and s.auto.get("by") == "user"
ui_style.confirm = orig
print("질문:", asked[0])
assert asked[0][1] == ["취소", "이 프레임에 ◆", "전체 바꾸기"] and "AUTO 보정·◆" in asked[0][0]
# ◆·AUTO 없으면 묻지 않음
n = len(asked)
ui_style.confirm = lambda *a: (asked.append(1), "cancel")[1]
gp.apply_choice("light", "mid"); wait(0.2)
ui_style.confirm = orig
assert len(asked) == n
# v0.16.36: 스틸 → 타임라인 = 0초, 재생 중 = 고른 틀 숨김
import numpy as np  # noqa: E402
png = os.path.join(d, "dot.png")
a = np.zeros((60, 60, 4), np.uint8); a[10:50, 10:50] = (230, 40, 30, 255)
subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "60x60", "-i", "-",
                "-frames:v", "1", png], input=a.tobytes(), check=True)
st.import_images([png]); wait(3, lambda: st.project.images and st.project.images[0].width)
s = e._cur(); s.sel_in, s.sel_out = 0, 300; e.send_to_timeline(); wait(0.3)
e.tl_time = 5.0
e.add_title_image(st.project.images[0].id); wait(0.5)
im = st.project.titles[-1]
assert im["kind"] == "image" and im["t0"] == 0.0 and abs(e.tl_time) < 1e-6, (im["t0"], e.tl_time)
e.player.play(); wait(0.8)
print("재생 중 틀 숨김:", e.player.mon.playing); assert e.player.mon.playing
e.player.pause(); wait(0.3); assert not e.player.mon.playing
print("UI V1635 OK")
os._exit(0)
