"""보정 패널 점검: 프리셋(여러 클립)·숫자 직접 입력·흰색 찍기·출력 크기·반반.
사용: python tests/test_ui_grade.py <샘플.MP4> <4K테스트.mp4> <작업폴더>"""
import os, sys, time, shutil
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
import main as M
from dtme import paths, project as P
from dtme.ui_main import MainWindow
SAMPLE, T4K, WORK = sys.argv[1:4]; os.makedirs(WORK, exist_ok=True)
shutil.rmtree(paths.app_dir() / "presets", ignore_errors=True)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show()
def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond(): return True
st, e, gp = w.state, w.edit, w.edit.grade
e.import_files([SAMPLE, T4K]); wait(60, lambda: len(st.project.sources) == 2 and all(st.status.get(s.id) == "준비" for s in st.project.sources))
a, b = st.project.sources
# 숫자 직접 입력
v = gp.vals["r_gain"]; QTest.mouseClick(v, Qt.LeftButton); wait(0.1)
v.setText("1.37"); QTest.keyClick(v, Qt.Key_Return); wait(0.3)
print("숫자 입력 빨강:", st.project.grade_for_source(a.id)["r_gain"], "슬라이더", gp.sliders["r_gain"].value())
assert abs(st.project.grade_for_source(a.id)["r_gain"] - 1.37) < 1e-6 and gp.sliders["r_gain"].value() == 137
v.mousePressEvent  # 범위 밖
QTest.mouseClick(v, Qt.LeftButton); v.setText("9"); QTest.keyClick(v, Qt.Key_Return); wait(0.2)
print("범위 밖 9 →", st.project.grade_for_source(a.id)["r_gain"]); assert st.project.grade_for_source(a.id)["r_gain"] == 2.0
w.undo(); wait(0.2); print("실행취소 →", st.project.grade_for_source(st.project.sources[0].id)["r_gain"])
assert abs(st.project.grade_for_source(st.project.sources[0].id)["r_gain"] - 1.37) < 1e-6
a, b = st.project.sources
# 프리셋 저장 → 두 클립 선택 → 적용
gp.sliders["sat"].setValue(140); gp.sliders["wnr"].setValue(30); wait(0.5)
QInputDialog.getText = staticmethod(lambda *x, **k: ("잭피쉬 20m", True))
gp._save_preset(); print("프리셋 목록:", P.list_presets()); assert "잭피쉬 20m" in P.list_presets()
e._select_source(b.id); wait(1.0)
gp._clear_all(); wait(0.2)
for i in range(e.src_list.count()): e.src_list.item(i).setSelected(True)
print("선택:", len(e._selected_sids()))
gp._apply_preset("잭피쉬 20m"); wait(0.3)
ga, gb = st.project.grade_for_source(a.id), st.project.grade_for_source(b.id)
print("적용 후 채도/물 노이즈:", ga["sat"], ga["wnr"], "/", gb["sat"], gb["wnr"], "태그", e._tag(a.id), e._tag(b.id), gp.preset.text())
assert ga["sat"] == gb["sat"] == 1.4 and ga["wnr"] == gb["wnr"] == 30
# 흰색 찍기
e._select_source(a.id); wait(1.5); e.player.seek(100); wait(1.5)
gp.b_white.setChecked(True); wait(0.1); assert e.player.mon.pick_mode
e._white_picked(0.55, 0.75); wait(15, lambda: not gp.b_white.isChecked() and "흰색 찍기 →" in e.status.text())
g = st.project.grade_for_source(a.id); print("흰색 찍기:", e.status.text()[-40:], g["r_gain"], g["b_gain"]); assert not e.player.mon.pick_mode
# 출력 크기
gp.set_output("horizontal2160"); print("출력:", st.project.output.orientation, "모니터 화면비", round(e.player.mon.out_aspect, 3))
e.send_to_render(); print("렌더 항목:", st.project.render_items[-1].orientation)
# 반반
gp.set_view("split"); wait(6, lambda: e.player.mon.before is not None); print("반반 원본 이미지:", e.player.mon.before is not None)
w.grab().save(os.path.join(WORK, "shot_grade.png"))
print("UI GRADE OK")
