"""v0.16.70: AUTO 창 크기 칸 = 세로로 찍은 소스는 고른 크기를 90도 돌린 세로(1080×1920 · 1440×2560 · 2160×3840) · `세로` → `인스타`.
사용: python tests/test_ui_v1670.py <작업폴더>"""
import faulthandler, os, subprocess, sys, time  # noqa: E401
faulthandler.enable()
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication
import main as M
from dtme import ff, paths
from dtme.project import out_label
from dtme.ui_main import MainWindow
WORK = os.path.abspath(sys.argv[1]); os.makedirs(WORK, exist_ok=True)
FF = paths.ffmpeg()
land = os.path.join(WORK, "DJI_20261112120000_0001_D.MP4")
vert = os.path.join(WORK, "VID_20261112_120500_002.mp4")
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=3840x2160:r=30:d=1", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", land], check=True)
subprocess.run([FF, "-v", "error", "-y", "-display_rotation", "90", "-i", land, "-c", "copy", vert], check=True)
assert ff.out_size("vertical2160") == (2160, 3840) and ff.out_size("vertical1440") == (1440, 2560)
assert ff.is_vertical("vertical2160") and not ff.is_vertical("horizontal2160")
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
    return False


st, e, gp = w.state, w.edit, w.edit.grade
e.import_files([land, vert])
assert wait(180, lambda: len(st.project.sources) == 2 and all(st.status.get(s.id) == "준비" for s in st.project.sources))
print("단계: 가져옴", flush=True)
p = st.project
sl, sv = (next(s for s in p.sources if s.path == f) for f in (land, vert))
assert (sv.width, sv.height) == (2160, 3840), (sv.width, sv.height)
# 기본(프로젝트 1080) = 가로 1920×1080 / 세로 촬영 1080×1920
assert p.out_of(sl) == "horizontal" and p.out_of(sv) == "vertical"
assert out_label("vertical", sl) == "인스타 1080×1920" and out_label("vertical", sv) == "1080×1920"
assert out_label("vertical", sl, short=True) == "인스타" and out_label("vertical2160", sv, short=True) == "세로 4K"
# AUTO 창: 4K → 가로 3840×2160 / 세로 촬영 2160×3840
print("단계: AUTO 창", flush=True)
dlg = e.make_auto_dialog(); dlg.show(); wait(0.3)
assert dlg.out.btns["vertical"].text() == "인스타" and "릴스" in dlg.out.btns["vertical"].toolTip()
dlg.list.clearSelection()
dlg._out("horizontal2160"); wait(0.1)
outs = {r.sid: r.out for r in dlg.rows}
assert outs == {sl.id: "horizontal2160", sv.id: "vertical2160"}, outs
dlg._out("horizontal1440"); wait(0.1)
assert {r.sid: r.out for r in dlg.rows} == {sl.id: "horizontal1440", sv.id: "vertical1440"}
dlg._out("vertical"); wait(0.1)                       # 인스타 = 가로 촬영 → 1080×1920, 세로 촬영 → 세로 1080
assert {r.sid: r.out for r in dlg.rows} == {sl.id: "vertical", sv.id: "vertical"}
# 세로 촬영 줄만 고르면 인스타 버튼 숨김, 1440·4K 버튼은 보임
i_v = next(i for i, r in enumerate(dlg.rows) if r.sid == sv.id)
dlg.list.setCurrentRow(i_v); dlg.list.item(i_v).setSelected(True); wait(0.1)
dlg._out_options()
assert dlg.out.btns["vertical"].isHidden() and not dlg.out.btns["horizontal2160"].isHidden()
dlg._out("horizontal2160"); dlg._sel_changed(); wait(0.1)
assert dlg.out.value() == "horizontal2160"            # 세로 4K 줄 = 4K 버튼 켜짐
dlg.grab().save(os.path.join(WORK, "auto_out.png"))
# [보정+편집] 적용과 같은 경로: 줄 출력 → 소스 출력(개별)
for r in dlg.rows:
    p.source(r.sid).out = r.out
print("단계: 보정 패널", flush=True)
dlg.reject(); wait(0.2)
e._select_source(sv.id); wait(0.5)
assert gp.out.currentData() == "vertical2160" and gp.out.itemText(gp.out.currentIndex()) == "2160×3840"
assert e.player.mon.out_aspect < 1
e._select_source(sl.id); wait(0.5)
assert gp.out.currentData() == "vertical" and gp.out.itemText(gp.out.currentIndex()) == "인스타 1080×1920"
assert "vertical2160" not in [gp.out.itemData(i) for i in range(gp.out.count())]   # 가로 촬영 = 세로 1440·4K 없음
# 렌더 항목 = 소스별
for i in range(e.src_list.count()):
    e.src_list.item(i).setSelected(True)
e.sources_to_render(); wait(0.3)
assert {it.segs[0].src: it.orientation for it in p.render_items} == {sl.id: "vertical", sv.id: "vertical2160"}
# 세로 4K 실제 렌더 크기
print("단계: 렌더", flush=True)
it = next(x for x in p.render_items if x.segs[0].src == sv.id)
out = os.path.join(WORK, "v4k.mp4")
p.output.encoder = "x264"
ff.render_video(p, it.segs, out, orientation="vertical2160")
pr = ff.probe(out)
assert (pr["width"], pr["height"]) == (2160, 3840), pr
print("OK test_ui_v1670", flush=True); os._exit(0)
