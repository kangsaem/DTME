"""v0.16.4 점검: DJI 메타로 색 모드 판단 → 불러올 때 LUT(D-Log M = LUT, 일반·알 수 없음 = 없음) · 프록시 = 클립 LUT ·
프리셋·기본값이 클립 LUT 유지 · AUTO 창 LUT 줄(자동/없음/파일, 다시 분석) · 4:3(3840×2880) 원본 렌더.
사용: python tests/test_lut_auto.py <D-Log M 액션4.MP4> <일반 모드 액션4.MP4> <합성(DJI 아님).mp4> <작업폴더>"""
import os, sys, time, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication
import main as M
from dtme import ff, project as P
from dtme.ui_main import MainWindow
DLOG, NORM, SYN, WORK = sys.argv[1:5]; os.makedirs(WORK, exist_ok=True)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond(): return True
    return False


st, e, gp = w.state, w.edit, w.edit.grade
p = st.project
t0 = time.time()
modes = [ff.dji_color_mode(f) for f in (DLOG, NORM, SYN)]
print("색 모드:", modes, f"{(time.time() - t0) / 3:.2f}초/파일"); assert modes == ["dlog", "normal", "unknown"]
e.import_files([DLOG, NORM, SYN])
assert wait(300, lambda: len(p.sources) == 3 and all(st.status.get(s.id) == "준비" for s in p.sources))
d, n, u = p.sources
luts = [p.grade_for_source(s.id)["lut"] for s in (d, n, u)]
print("불러온 LUT:", luts, "표시", [e._tag(s.id) for s in (d, n, u)])
assert luts[0] == P.DEFAULT_LUT and luts[1] == "" and luts[2] == "" and [e._tag(s.id) for s in (d, n, u)] == ["", "", ""]
print("프록시:", [os.path.basename(s.proxy) for s in (d, n, u)])
assert d.proxy == str(ff.proxy_path(d.path, P.DEFAULT_LUT)) and n.proxy == str(ff.proxy_path(n.path, "")) != str(ff.proxy_path(n.path, P.DEFAULT_LUT))
# 프리셋·기본값이 클립 LUT 를 바꾸지 않음
e._select_source(n.id); wait(3)
gp.apply_choice("shallow"); wait(0.5)
print("일반 + 프리셋 → LUT", repr(p.grade_for_source(n.id)["lut"]), "C" if P.has_clip_grade(n) else "-"); assert p.grade_for_source(n.id)["lut"] == ""
gp._clear_all(); wait(0.3)
print("일반 + 기본값 → LUT", repr(p.grade_for_source(n.id)["lut"]), e._tag(n.id)); assert p.grade_for_source(n.id)["lut"] == "" and e._tag(n.id) == "E"
e._select_source(d.id); wait(2); gp.apply_choice("deep"); wait(0.3); assert p.grade_for_source(d.id)["lut"] == P.DEFAULT_LUT
# 보정 패널에서 LUT 를 바꾸면 그 LUT 로 프록시
old = n.proxy
e._select_source(n.id); wait(2)
gp._set("lut", P.DEFAULT_LUT); wait(1)
assert wait(120, lambda: st.status.get(n.id) == "준비" and n.proxy != old)
print("LUT 바꿈 → 프록시", os.path.basename(n.proxy), "플레이어", os.path.basename(e.player.proxy)); assert wait(5, lambda: e.player.proxy == n.proxy)
gp._set("lut", ""); wait(1); assert wait(60, lambda: n.proxy == old)
# AUTO 창 LUT 줄
dlg = e.make_auto_dialog(); dlg.show()
for r in dlg.rows: r.checked = True
dlg.start_analysis()
assert wait(120, lambda: not dlg.pending())
subs = [dlg.row_text(r)[2] for r in dlg.rows]
print("AUTO 자동:", [dlg.row_lut(r) for r in dlg.rows], subs)
assert [dlg.row_lut(r) for r in dlg.rows] == [P.DEFAULT_LUT, "", ""] and subs[0].startswith("D-Log M") and subs[1].startswith("일반 · LUT 없음") and subs[2].startswith("알 수 없음 · LUT 없음")
dlg.grab().save(os.path.join(WORK, "shot_auto_lut.png"))
dlg.lut_combo.setCurrentIndex(dlg.lut_combo.findData(""))           # 전부 LUT 없음
assert wait(120, lambda: not dlg.pending())
print("AUTO LUT 없음:", [dlg.row_lut(r) for r in dlg.rows], [r.result["grade"]["lut"] for r in dlg.rows]); assert all(r.result["grade"]["lut"] == "" for r in dlg.rows)
dlg.mode = "each"; e._auto_start(dlg); wait(1)
print("적용 → D-Log 클립 LUT", repr(p.grade_for_source(d.id)["lut"])); assert p.grade_for_source(d.id)["lut"] == ""
assert wait(180, lambda: st.status.get(d.id) == "준비" and d.proxy == str(ff.proxy_path(d.path, "")))
w.undo(); wait(0.5); assert P.Project.from_dict(p.to_dict()) and st.project.grade_for_source(st.project.sources[0].id)["lut"] == P.DEFAULT_LUT
P.set_setting("auto", {**(P.get_setting("auto", {}) or {}), "lut": "auto"})
# 4:3 원본 렌더(가로 1080 · 세로)
p = st.project; n = p.sources[1]
p.output.encoder, p.output.gpu_decode = "x264", False
for ori, want in (("horizontal", "1920,1080"), ("vertical", "1080,1920")):
    out = os.path.join(WORK, f"n43_{ori}.mp4")
    ff.render_video(p, [p.snap_seg(P.Segment(n.id, 0, 60))], out, orientation=ori, audio=False)
    wh = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", out],
                        capture_output=True, text=True).stdout.strip()
    print("4:3 원본 →", ori, wh); assert wh == want
print("LUT AUTO OK")
