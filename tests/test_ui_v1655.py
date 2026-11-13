"""v0.16.55: 출력 = 소스별 · 샘플 창(제목줄 없음 · ✕ · [저장] · 출력 화면대로 자름) · 이름에 날짜 없는 파일 = 만든 시각 · 아이폰 AAE 자르기 → 인/아웃.
사용: python tests/test_ui_v1655.py <작업폴더>"""
import base64, json, os, plistlib, subprocess, sys, time, zlib  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QFileDialog
import main as M
from dtme import ff, paths
from dtme.project import short_name
from dtme.ui_main import MainWindow
WORK = os.path.abspath(sys.argv[1]); os.makedirs(WORK, exist_ok=True)
FF = paths.ffmpeg()
land = os.path.join(WORK, "DJI_20261112120000_0001_D.MP4")
vert = os.path.join(WORK, "VID_20261112_120500_002.mp4")
phone = os.path.join(WORK, "BJVS0001.MP4")
tmp = os.path.join(WORK, "tmp.mp4")
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", land], check=True)
subprocess.run([FF, "-v", "error", "-y", "-display_rotation", "90", "-i", land, "-c", "copy", vert], check=True)
subprocess.run([FF, "-v", "error", "-y", "-i", land, "-c", "copy", "-metadata", "creation_time=2026-06-25T02:35:25.000000Z", phone], check=True)
adj = {"adjustments": [{"identifier": "Trim", "enabled": True, "settings": {
    "startTime": {"value": 1, "timescale": 1}, "endTime": {"value": 4500000, "timescale": 1000000}}}]}
co = zlib.compressobj(wbits=-15)
with open(os.path.join(WORK, "BJVS0001.AAE"), "wb") as fh:
    plistlib.dump({"adjustmentData": co.compress(json.dumps(adj).encode()) + co.flush()}, fh)
assert ff.aae_trim(phone) == (1.0, 4.5) and ff.aae_trim(land) is None
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
    return False


st, e, gp = w.state, w.edit, w.edit.grade
e.import_files([land, vert, phone])
assert wait(120, lambda: len(st.project.sources) == 3 and all(st.status.get(s.id) == "준비" for s in st.project.sources))
p = st.project
sl, sv, sp = (next(s for s in p.sources if s.path == f) for f in (land, vert, phone))
# 1) 이름에 날짜 없음 = 파일 안의 만든 시각(현지 시간) · 이름에 날짜 있으면 그대로
import datetime as _dt
want = _dt.datetime(2026, 6, 25, 2, 35, tzinfo=_dt.timezone.utc).astimezone().strftime("%Y%m%d%H%M")
assert short_name(phone) == want == sp.ctime, (short_name(phone), want)
assert short_name(land) == "202611121200" and not sl.ctime
# 2) AAE 자르기 → 인/아웃(1초~4.5초)
assert sp.io == (30, 135), sp.io
assert sl.io == (0, sl.frames)
# 3) 출력 = 소스별
e._select_source(sl.id); wait(0.5)
assert gp.out.currentData() == "horizontal"
gp.set_output("vertical"); wait(0.3)
assert sl.out == "vertical" and sv.out == "" and p.output.orientation == "horizontal", (sl.out, sv.out)
assert gp.out.itemText(gp.out.currentIndex()) == "인스타 1080×1920"    # v0.16.70 가로 촬영의 세로 = 인스타
assert e.player.mon.out_aspect < 1
e._select_source(sv.id); wait(0.5)
assert gp.out.currentData() == "vertical" and e.player.mon.out_aspect < 1, "다른 소스 = 그 소스의 출력(v0.16.70 세로 촬영 = 돌린 크기)"
assert gp.out.itemText(gp.out.currentIndex()) == "1080×1920"            # 세로 촬영의 세로 = 인스타 이름 아님
e._select_source(sl.id); wait(0.5)
assert gp.out.currentData() == "vertical" and e.player.mon.out_aspect < 1
for i in range(e.src_list.count()):
    e.src_list.item(i).setSelected(e.src_list.item(i).data(Qt.UserRole) in (sl.id, sv.id))
e.sources_to_render(); wait(0.3)
got = {it.segs[0].src: it.orientation for it in p.render_items}
assert got == {sl.id: "vertical", sv.id: "vertical"}, got
st.undo(); wait(0.2)
# 4) 샘플: 세로 촬영 = 기본 세로(v0.16.70, 예전 = 가로로 잘라서) — 가로로 바꾸면 가로로 잘림 · 창 = 제목줄 없음 · [저장]
e._select_source(sv.id); wait(0.5)
gp.set_output("horizontal"); wait(0.3)
e._select_source(sv.id); wait(0.5)
assert gp.make_samples()
assert wait(60, lambda: gp.samples.count() == 6 and all(gp.samples.item(i).data(Qt.UserRole + 1) for i in range(6)))
im = QImage(gp.samples.item(0).data(Qt.UserRole + 1))
assert abs(im.width() / im.height() - 16 / 9) < 0.02, (im.width(), im.height())
assert gp.smp_win.windowFlags() & Qt.FramelessWindowHint
gp.smp_win.grab().save(os.path.join(WORK, "samples_win.png"))
out = os.path.join(WORK, "saved"); os.makedirs(out, exist_ok=True)
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: out)
from dtme import ui_style
said = []; ui_style.notice = lambda parent, text: said.append(text)      # v0.16.58 저장 확인 창
gp.b_smp_save.click(); wait(0.3)
assert said == ["샘플 6장 저장됨"], said
names = sorted(os.listdir(out)); print("저장:", names)
assert names == [f"202611121205_{k}.png" for k in range(1, 7)]
gp.set_output("vertical")
assert wait(60, lambda: (lambda q: not q.isNull() and q.width() < q.height())(QImage(gp.samples.item(0).data(Qt.UserRole + 1) or "")))
gp.set_view("split"); wait(3)
gp._on_sample(gp.samples.item(3)); wait(0.3)
assert e.player.mon.before is None, "v0.16.63 샘플 클릭 = 샘플 그림만(지금 프레임 원본을 겹치지 않음)"
gp.b_smp_x.click(); wait(0.3); assert not gp.smp_win.isVisible() and not gp.b_smp.isChecked()
print("OK test_ui_v1655"); os._exit(0)
