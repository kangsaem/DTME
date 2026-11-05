"""세로 크롭 위치 이동 화면 점검. 사용: python tests/test_ui_reframe.py <샘플.MP4> <작업폴더>"""
import os, sys, time, shutil
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import main as M
from dtme import ff, paths
from dtme.ui_main import MainWindow
SAMPLE, WORK = sys.argv[1:3]; os.makedirs(WORK, exist_ok=True)
shutil.rmtree(paths.cache_dir(), ignore_errors=True)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1800, 1000); w.show()
def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond(): return True
st, e = w.state, w.edit
st.project.output.folder = os.path.join(WORK, "out"); st.project.output.encoder = "x264"; st.project.output.gpu_decode = False
e.import_files([SAMPLE]); wait(60, lambda: st.project.sources and st.status.get(st.project.sources[0].id) == "준비")
src = st.project.sources[0]
e.grade.orient.button(1).setChecked(True); e.grade._on_output(); wait(1.0)
mon = e.player.mon
# 가로 상태에서는 크롭 드래그 없음 확인은 생략. 프레임 30 에서 크롭 틀을 왼쪽으로 끌기
e.player.seek(30); wait(0.8)
c = mon._out_rect.center().toPoint()
dx_screen = int(mon._img_rect.width() * 0.1)          # 원본 폭의 10% = 384px
QTest.mousePress(mon, Qt.LeftButton, Qt.NoModifier, c)
QTest.mouseMove(mon, c - QPoint(dx_screen, 0))
QTest.mouseRelease(mon, Qt.LeftButton, Qt.NoModifier, c - QPoint(dx_screen, 0)); wait(0.2)
print("키프레임 1:", src.reframe, "프레임", e.player.frame)
assert len(src.reframe) == 1 and src.reframe[0]["f"] == 30 and -400 < src.reframe[0]["dx"] < -370
# 프레임 150 에서 오른쪽 끝까지(±540 제한)
e.player.seek(150); wait(0.5)
c = mon._out_rect.center().toPoint()
QTest.mousePress(mon, Qt.LeftButton, Qt.NoModifier, c)
QTest.mouseMove(mon, c + QPoint(int(mon._img_rect.width() * 0.5), 0))
QTest.mouseRelease(mon, Qt.LeftButton, Qt.NoModifier, c + QPoint(int(mon._img_rect.width() * 0.5), 0)); wait(0.2)
print("키프레임 2:", src.reframe)
assert src.reframe[1] == {"f": 150, "dx": 540.0}
e.player.seek(90); wait(0.5)
print("중간 프레임 90 크롭 이동:", round(mon.crop_dx, 1), "소스 바 ◇", e.sbar.keys)
assert abs(mon.crop_dx - (-384 + 540) / 2) < 30
w.grab().save(os.path.join(WORK, "shot_reframe.png"))
# ◇ 클릭 → 그 위치로
x = int(e.sbar._x(150)); QTest.mouseClick(e.sbar, Qt.LeftButton, Qt.NoModifier, QPoint(x, 5)); wait(0.3)
print("◇ 클릭 →", e.player.frame); assert e.player.frame == 150
# ◇ 우클릭 → 삭제 / 실행취소
QTest.mouseClick(e.sbar, Qt.RightButton, Qt.NoModifier, QPoint(x, 5)); wait(0.2)
print("우클릭 후:", [k["f"] for k in src.reframe]); assert [k["f"] for k in src.reframe] == [30]
w.undo(); wait(0.3); src = st.project.sources[0]; print("실행취소:", [k["f"] for k in src.reframe]); assert len(src.reframe) == 2
# ▼ → 렌더 (세로)
src.sel_in, src.sel_out = 0, 180; e.send_to_timeline(); e.timeline_to_render(); wait(0.2)
assert st.project.render_items[-1].segs[0].reframe
e.render_panel.render(); wait(600, lambda: not e.render_panel.running)
print([e.render_panel.status.get(r.id, "")[:40] for r in st.project.render_items])
# 가로로 바꾸면 ◇ 숨김
e.grade.orient.button(0).setChecked(True); e.grade._on_output(); wait(0.5)
print("가로 ◇:", e.sbar.keys); assert e.sbar.keys == []
print("UI REFRAME OK")
