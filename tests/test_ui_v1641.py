"""v0.16.41: 다시 실행 · 원본 폴더 다시 지정 · 커브 끄는 동안 화면 · [영상 추가][AUTO][삭제] · 오류 글 유지 · 남은 시간 · 자동 저장 되살리기.
사용: python tests/test_ui_v1641.py"""
import os, shutil, subprocess, sys, tempfile, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication, QPushButton
import main as M
from dtme import paths, ui_edit
from dtme.ui_main import MainWindow
d = tempfile.mkdtemp(); vids = []
for i in range(2):
    v = os.path.join(d, f"k{i}.mp4")
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", v], check=True); vids.append(v)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1700, 950); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond():
            return True


st, e, gp = w.state, w.edit, w.edit.grade
ready = lambda: len(st.project.sources) == 2 and all(st.status.get(x.id) == "준비" for x in st.project.sources)  # noqa: E731
e.import_files(vids); assert wait(60, ready)
s = st.project.sources[0]; e._select_source(s.id); wait(1.0)
e.player.seek(30); wait(2.5, lambda: e.player.overlay_frame == 30)

# 1) 버튼 순서: 영상 추가 · AUTO · 삭제
row = [b for b in e.findChildren(QPushButton) if b.text() in ("영상 추가", "AUTO", "삭제") and b.parent() is e.b_auto.parent()]
xs = {b.text(): b.x() for b in row if b.y() == e.b_auto.y()}
assert xs["영상 추가"] < xs["AUTO"] < xs["삭제"], xs

# 2) 다시 실행
gp._set("r_gain", 1.30); wait(0.2)
gp._set("b_gain", 0.90); wait(0.2)
g = lambda: st.project.grade_for_source(e.cur_sid, 30)  # noqa: E731
assert abs(g()["r_gain"] - 1.30) < 1e-6 and abs(g()["b_gain"] - 0.90) < 1e-6
w.undo(); wait(0.2); assert abs(g()["b_gain"] - 0.90) > 1e-3 and abs(g()["r_gain"] - 1.30) < 1e-6
w.undo(); wait(0.2); assert abs(g()["r_gain"] - 1.30) > 1e-3
w.redo(); wait(0.2); assert abs(g()["r_gain"] - 1.30) < 1e-6
w.redo(); wait(0.2); assert abs(g()["b_gain"] - 0.90) < 1e-6
assert not st.redo()                                      # 더 없음
w.undo(); gp._set("hue", 3.0); wait(0.2); assert not st.redo()      # 새 작업 = 다시 실행 비움

# 3) 커브 끄는 동안 화면 + 실행취소 1번
shown = []
osi = e.player.show_image
e.player.show_image = lambda im: (shown.append(1), osi(im))[1]
n_undo = len(st._undo)
for k in range(12):
    gp._curve_live([[0, 0], [0.5, 0.5 + 0.01 * k], [1, 1]]); wait(0.12)
assert shown, "커브를 끄는 동안 화면이 안 바뀜"
gp._curve_done([[0, 0], [0.5, 0.62], [1, 1]]); wait(1.5)
assert len(st._undo) == n_undo + 1, (len(st._undo), n_undo)
assert g()["curve"][1] == [0.5, 0.62]
w.undo(); wait(0.3); assert g()["curve"] != [[0, 0], [0.5, 0.62], [1, 1]]

# 4) 오류 글은 남고, 누르면 지워짐
e._say("스틸 실패: x", ui_edit.C_WARN); e._say("안내", ui_edit.C_INFO)
assert "스틸 실패" in e.status.text()
e._say("미리보기 오류: y", ui_edit.C_WARN); assert "미리보기 오류" in e.status.text()
e._say_clear(); e._say("안내", ui_edit.C_INFO); assert "안내" in e.status.text()
e._say("프록시 준비 중", ui_edit.C_WARN); e._say("다음", ui_edit.C_INFO); assert "다음" in e.status.text()

# 5) 남은 시간 글
rp = e.render_panel
rp.run_t0 = time.time() - 60
assert rp._left_text(0.5) == "1:00" and rp._left_text(0.01) == "" and rp._left_text(0.25) == "3:00"
rp.run_t0 = time.time() - 3; assert rp._left_text(0.5) == ""

# 6) 원본 폴더 다시 지정: 저장 → 파일을 다른 폴더(아래 폴더)로 옮김 → 불러오면 원본 없음 → relink
st.project.sources[1].grade["r_gain"] = 1.11
proj = os.path.join(d, "p.dtme.json"); st.project.save(proj)
nd = os.path.join(d, "moved", "sub"); os.makedirs(nd)
for v in vids:
    shutil.move(v, nd)
from dtme.project import Project
st.set_project(Project.load(proj)); wait(0.3)
assert len(st.missing()) == 2
assert st.relink(os.path.join(d, "moved")) == 2 and not st.missing()
assert wait(60, ready), st.status
assert all(os.path.dirname(x.path) == nd for x in st.project.sources)
assert abs(st.project.sources[1].grade["r_gain"] - 1.11) < 1e-6        # 보정 그대로

# 7) 자동 저장 → 되살리기(원래 파일 이름 유지 · 저장 안 된 상태) · 저장하면 지워짐
af = w.autosave_file(); keep = af.read_bytes() if af.exists() else None
try:
    st.dirty = True; w._do_autosave(); assert af.exists()
    st.project.sources[1].grade["r_gain"] = 1.5
    assert w.restore_autosave() and st.dirty and st.project.file == proj
    assert abs(st.project.sources[1].grade["r_gain"] - 1.11) < 1e-6
    w.save_project(); assert not af.exists()
finally:
    if keep is not None:
        af.write_bytes(keep)
# 8) v0.16.45 흔들림 보정 한계: 블루워터 = 슬라이더 꺼짐 · 산호 100 · 나머지 50
s0 = st.project.sources[0]; e._select_source(s0.id); wait(0.5)
sl = gp.sliders["stab"]
for pk, lim in (("coral", 100), ("deep", 50), ("bluewater", 0)):
    s0.auto = {"preset": pk}; s0.grade["stab"] = 100; gp._load_controls()
    assert sl.isEnabled() == (lim > 0) and (sl.maximum() == lim or lim == 0), (pk, sl.maximum(), sl.isEnabled())
    assert st.project.grade_for_source(s0.id)["stab"] == lim and sl.value() == min(lim, sl.maximum()), (pk, sl.value())
s0.auto = {}; s0.grade.pop("stab", None); gp._load_controls()
print("UI V1641 OK")
os._exit(0)
