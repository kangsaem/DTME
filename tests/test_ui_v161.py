"""v0.16.1 점검: 불러오면 보정 없음(LUT만) · 실행취소 후 화면 갱신 · 이름 클릭 = 잠시 끔(보낸 컷에 사본) ·
모니터 로딩 표시 · AUTO 창(기존 보정·키프레임 위치, 렌즈·흔들림 슬라이더, 프록시 안 기다림) · 프록시 GPU→CPU 재시도.
사용: python tests/test_ui_v161.py <4K테스트.mp4> <작업폴더>"""
import os, sys, time, hashlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import main as M
from dtme import ff, paths, project as P
from dtme.ui_main import MainWindow
CLIP, WORK = sys.argv[1:3]; os.makedirs(WORK, exist_ok=True)
for f in paths.cache_dir().glob("proxy*/*"):
    f.unlink(missing_ok=True)
pp = ff.proxy_path(CLIP)
pp.unlink(missing_ok=True)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond(): return True
    return False


def img():
    im = e.player.mon.img
    return hashlib.md5(bytes(im.constBits())[:im.sizeInBytes()]).hexdigest()[:10] if im is not None else "none"


st, e, gp = w.state, w.edit, w.edit.grade
e.import_files([CLIP]); wait(10, lambda: st.project.sources and st.project.sources[0].frames)
s = st.project.sources[0]
# 1) 보정 없음(LUT만)
g = st.project.grade_for_source(s.id)
print("새 클립:", {k: g[k] for k in ("r_gain", "b_gain", "hue", "sat", "sharpen", "nr_chroma")}, "LUT", repr(g["lut"]), "태그", repr(e._tag(s.id)))
assert P.is_plain(s) and e._tag(s.id) == "" and g["sat"] == 1.0 and g["hue"] == 0 and g["sharpen"] == 0
assert g["lut"] == "" and s.lut_mode == "unknown"          # 합성 영상 = DJI 아님 → LUT 없음(v0.16.4)
# 2) 로딩 표시(프록시 만드는 동안)
e._select_source(s.id)
seen = wait(30, lambda: e.player.mon.loading is not None)
print("로딩 표시:", seen, e.player.mon.loading); assert seen
w.grab().save(os.path.join(WORK, "shot_loading.png"))
wait(180, lambda: st.status.get(s.id) == "준비")
wait(1); print("준비 후 로딩 표시:", e.player.mon.loading); assert e.player.mon.loading is None
log = (paths.cache_dir() / "dtme.log").read_text(encoding="utf-8")
print("프록시 기록:", [l[-60:] for l in log.splitlines() if "프록시" in l][-3:])
gp._set("lut", P.DEFAULT_LUT)                              # 아래 점검은 D-Log 처럼 LUT 를 넣고(→ 그 LUT 로 프록시 다시)
wait(180, lambda: st.status.get(s.id) == "준비" and s.proxy == str(ff.proxy_path(s.path, P.DEFAULT_LUT)))
e.player.seek(60); wait(5)
h0 = img()
# 3) 프리셋 → 실행취소 → 화면이 돌아옴
gp.apply_choice("deep"); wait(6); h1 = img()
w.undo(); wait(6); h2 = img()
print("프리셋/실행취소:", h0, h1, h2); assert h1 != h0 and h2 == h0
gp.sliders["r_gain"].setValue(170); wait(6); h3 = img()
w.undo(); wait(6); h4 = img()
print("빨강/실행취소:", h3, h4); assert h3 != h0 and h4 == h0
# 4) 이름 클릭 = 잠시 끔
gp.apply_choice("deep"); wait(6); hd = img()
s = st.project.sources[0]
gp.names["water"].clicked.emit(); wait(6); hw = img()
print("물빛 끔:", s.off, gp.names["water"].off, "값 표시", gp.vals["water"]._shown, "화면 바뀜", hw != hd)
assert s.off == ["water"] and gp.names["water"].off and hw != hd
assert st.project.grade_for_source(s.id)["water"] == 0 and st.project.grade_for_source(s.id, off=False)["water"] > 0
e.send_to_render(); seg = st.project.render_items[-1].segs[0]
print("보낸 컷 꺼짐 사본:", seg.off); assert seg.off == ["water"]
gp.names["water"].clicked.emit(); wait(6)
print("다시 켬:", s.off, img() == hd); assert s.off == [] and img() == hd
assert st.project.grade_for_source(s.id, seg=seg)["water"] == 0       # 이미 보낸 컷은 그대로 꺼짐
gp.names["sat"].clicked.emit(); gp.sliders["sat"].setValue(130); wait(0.5)
print("끈 항목 슬라이더 조절 → 다시 켬:", s.off); assert "sat" not in s.off
# 렌더 체인: 끈 항목은 보정 없음 값
g_off = st.project.grade_for_source(s.id, seg=seg)
assert "huesaturation@w" not in " ".join(ff.grade_chain(g_off, None, 1920)) or g_off["water"] == 0
# 5) 리셋 = 보정 없음
gp._reset_clip(); wait(0.3); print("리셋 → 보정 없음:", P.is_plain(st.project.sources[0])); assert P.is_plain(st.project.sources[0])
# 6) AUTO 창
dlg = e.make_auto_dialog()
QTimer.singleShot(0, lambda: None)
dlg.show(); wait(1)
ky = dlg.keep.mapTo(dlg, dlg.keep.rect().topLeft()).y(); gy_ = dlg.grid.mapTo(dlg, dlg.grid.rect().topLeft()).y()
print("기존 보정 y", ky, "< 프리셋 격자 y", gy_); assert ky < gy_
dlg.start_analysis(); dlg.lens_s.setValue(40); dlg.stab_s.setValue(25); wait(30, lambda: all(r.result for r in dlg.rows if r.checked))
r = dlg.rows[0]
print("AUTO 결과 렌즈/흔들림:", r.result["grade"]["lens"], r.result["grade"]["stab"]); assert r.result["grade"]["lens"] == 40 and r.result["grade"]["stab"] == 25
dlg.grab().save(os.path.join(WORK, "shot_auto.png"))
dlg.mode = "each"; e._auto_start(dlg); wait(1)
g = st.project.grade_for_source(st.project.sources[0].id)
print("적용 후:", g["lens"], g["stab"], P.get_setting("auto", {}).get("lens")); assert g["lens"] == 40 and g["stab"] == 25
w.grab().save(os.path.join(WORK, "shot_main.png"))
print("UI v0.16.1 OK")
