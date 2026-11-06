"""v0.16.2 점검: 디헤이즈 빼기·블루워터 밝기 커브 · 스틸 8bit 기본 · WinError 32 재시도 · 보정 전 = LUT만 ·
렌더 리스트 보정값 사본(노란 점·지금 보정값으로)·완료 저장 · 렌더 설정 창(취소/확인·실행취소·새 프로젝트 기본값).
사용: python tests/test_ui_v162.py <4K테스트.mp4> <작업폴더>"""
import os, sys, time, json, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication
import main as M
from dtme import auto, ff, project as P
from dtme.ui_main import MainWindow
CLIP, WORK = sys.argv[1:3]; os.makedirs(WORK, exist_ok=True)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond(): return True
    return False


st, e, gp, rp = w.state, w.edit, w.edit.grade, w.edit.render_panel
# 1) 디헤이즈 빼기 + 블루워터 밝기
assert "dehaze" not in gp.sliders and ff.sharpen_chain({"sharpen": 0.1, "dehaze": 50}) == ["unsharp=5:5:0.200:5:5:0"]
bw = auto.builtin_grade("bluewater", P.FACTORY_GRADE)
print("블루워터 디헤이즈", bw["dehaze"], "커브", bw["curve"]); assert bw["dehaze"] == 0 and bw["curve"][2][1] > 0.18 and bw["curve"][3][1] > 0.84
assert auto.builtin_grade("deep", P.FACTORY_GRADE)["curve"][3][1] == 0.78        # 다른 프리셋은 그대로
# 2) WinError 32 재시도
real = subprocess.Popen; n = {"k": 0}
def flaky(*a, **k):
    if n["k"] < 2:
        n["k"] += 1; err = OSError("[WinError 32] 다른 프로세스가 사용 중"); err.winerror = 32; raise err
    return real(*a, **k)
subprocess.Popen = flaky
out = ff.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=16x16:d=0.04", "-frames:v", "1", "-f", "null", "-"])
subprocess.Popen = real
print("WinError 32 두 번 → 성공:", n["k"]); assert n["k"] == 2
# 3) 불러오기 → 보정 전 = LUT만
e.import_files([CLIP]); wait(180, lambda: st.project.sources and st.status.get(st.project.sources[0].id) == "준비")
s = st.project.sources[0]; e._select_source(s.id); wait(2); e.player.seek(60); wait(4)
gp.apply_choice("bluewater"); wait(6)
c = ff.cached_frame(s, 60)
log_png, lut_png = ff.render_preview(c, None), ff.render_preview(c, ff.lut_only(st.project.grade_for_source(s.id)))
gp.set_view("split"); wait(8, lambda: e.player.mon.before is not None)
from PySide6.QtGui import QImage
b = e.player.mon.before
same_lut = b is not None and b == QImage.fromData(lut_png, "PNG"); same_log = b is not None and b == QImage.fromData(log_png, "PNG")
print("반반 왼쪽 = LUT만:", same_lut, "/ Log:", same_log); assert same_lut and not same_log
gp.set_view("grade"); wait(1)
# 4) 스틸 8bit 기본 / 16bit 설정
for bits in (8, 16):
    P.set_setting("still_bits", bits)
    f = os.path.join(WORK, f"still{bits}.png")
    ff.export_still(s, 60, st.project.grade_for_source(s.id, 60), f)
    pf = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=pix_fmt", "-of", "csv=p=0", f], capture_output=True, text=True).stdout.strip()
    print(f"스틸 {bits}bit →", pf); assert pf == ("rgb24" if bits == 8 else "rgb48be")
P.set_setting("still_bits", 8)
# 5) 렌더 리스트 보정값 사본
e.send_to_render(); it = st.project.render_items[-1]; seg = it.segs[0]
print("사본 r_gain", seg.grade.get("r_gain"), "노란 점", st.project.seg_stale(seg)); assert seg.grade and not st.project.seg_stale(seg)
gp.sliders["r_gain"].setValue(160); wait(1)
print("값 바꾼 뒤 노란 점:", st.project.seg_stale(seg), "렌더 값", st.project.grade_for_source(s.id, seg=seg)["r_gain"], "클립", st.project.grade_for_source(s.id)["r_gain"])
assert st.project.seg_stale(seg) and st.project.grade_for_source(s.id, seg=seg)["r_gain"] != 1.6
li = rp.table.item(rp.table.count() - 1); assert li.data(0x0100 + 2)
rp.table.clearSelection(); li.setSelected(True); rp._resnap(); wait(0.3)
seg = st.project.render_items[-1].segs[0]
print("지금 보정값으로 →", seg.grade["r_gain"], st.project.seg_stale(seg)); assert seg.grade["r_gain"] == 1.6 and not st.project.seg_stale(seg)
# 완료 저장 + 새 항목 없음
P.set_setting("last_folder", WORK); st.project.output.folder = WORK; st.project.output.encoder = "x264"
rp.render(); wait(300, lambda: not rp.running)
it = st.project.render_items[-1]
print("완료 기록:", os.path.basename(it.done)); assert it.done and os.path.exists(it.done)
d = st.project.to_dict(); p2 = P.Project.from_dict(json.loads(json.dumps(d)))
assert p2.render_items[-1].done == it.done and p2.render_items[-1].segs[0].grade["r_gain"] == 1.6
msgs = []; rp.message.connect(msgs.append); rp.render(); wait(0.3)
print("다시 렌더 버튼:", msgs); assert msgs == ["새 항목 없음"]
rp.table.clearSelection(); rp.table.item(rp.table.count() - 1).setSelected(True); rp._requeue()
assert st.project.render_items[-1].done == ""
# 6) 렌더 설정 창
dlg = rp.dlg; dlg.settings._load(); dlg.show(); wait(0.5)
dlg.grab().save(os.path.join(WORK, "shot_settings.png"))
br0 = st.project.output.bitrate_mbps
dlg.settings.bitrate.setValue(br0 + 10); dlg.reject(); wait(0.2)
print("취소 → 비트레이트", st.project.output.bitrate_mbps); assert st.project.output.bitrate_mbps == br0
dlg.settings._load(); dlg.settings.bitrate.setValue(br0 + 10); dlg.settings.encoder.setCurrentIndex(1); dlg.accept(); wait(0.2)
print("확인 →", st.project.output.bitrate_mbps, st.project.output.encoder); assert st.project.output.bitrate_mbps == br0 + 10
print("새 프로젝트 기본값:", P.Project().output.bitrate_mbps, P.Project().output.encoder); assert P.Project().output.bitrate_mbps == br0 + 10
w.undo(); wait(0.3); print("실행취소 →", st.project.output.bitrate_mbps); assert st.project.output.bitrate_mbps == br0
P.set_setting("render_defaults", {})
print("UI v0.16.2 OK")
