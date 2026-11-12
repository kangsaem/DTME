"""v0.16.54: 프리셋 창 = MOSCO 방식 — 열면 선택 없음 · 누르면 고르기만 · [적용] 으로만 적용(창 그대로) ·
✕·[프리셋] 다시 누르기로만 닫힘(Esc·바깥 클릭 무시) · 항상 위 · 고른 클립 따라감. python tests/test_ui_presetclose.py"""
import os, subprocess, sys, tempfile, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import main as M
from dtme import paths, ui_style
from dtme.ui_main import MainWindow
d0 = tempfile.mkdtemp(); clips = []
for i in range(2):
    c = os.path.join(d0, f"DJI_2026111210{i}000_000{i}_D.MP4")
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", c], check=True)
    clips.append(c)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show()
def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
st, e, gp = w.state, w.edit, w.edit.grade
e.import_files(clips); assert wait(90, lambda: len(st.project.sources) == 2 and all(s.frames for s in st.project.sources))
s0, s1 = st.project.sources
e._select_source(s0.id); wait(0.5)
ui_style.confirm = lambda *a, **k: "all"
s0.auto = {"preset": "night", "by": "user"}; gp._fill_presets()
gp.open_presets(); wait(0.3); d = gp._pdlg; assert d and d.isVisible()
assert d.windowFlags() & Qt.WindowStaysOnTopHint, "항상 위"
# 열면 아무것도 안 골라짐(현재 프리셋 = 글자로만)
assert d.pending is None and not d.b_apply.isEnabled()
assert not any(b.isChecked() for b in d.grid.findChildren(type(d.b_apply))) and not any(b.isChecked() for b in d.user_btns.values())
assert "야간" in d.cur.text(), d.cur.text()
# 누르면 고르기만
before = dict(s0.grade)
d.grid.chosen.emit("deep"); wait(0.2)
assert d.pending == "deep" and d.b_apply.isEnabled() and s0.grade == before and s0.auto["preset"] == "night", "고르기만"
# [적용] → 적용, 창 그대로
QTest.mouseClick(d.b_apply, Qt.LeftButton); wait(0.3)
assert s0.auto.get("preset") == "deep" and gp._pdlg is d and d.isVisible(), "적용 · 창 유지"
assert "깊은" in d.cur.text(), d.cur.text()
# 고른 클립이 바뀌면 따라감(고른 칸은 그대로)
e._select_source(s1.id); wait(0.5)
assert "깊은" not in d.cur.text() and d.pending == "deep", d.cur.text()
QTest.mouseClick(d.b_apply, Qt.LeftButton); wait(0.3)
assert s1.auto.get("preset") == "deep", "떠 있는 채 다른 클립에 적용"
# Esc · 바깥 클릭 = 안 닫힘
QTest.keyClick(d, Qt.Key_Escape); wait(0.2); assert d.isVisible(), "Esc 무시"
QTest.mouseClick(e.player, Qt.LeftButton, Qt.NoModifier, QPoint(50, 50)); wait(0.3)
assert gp._pdlg is d and d.isVisible(), "바깥 클릭 무시"
# ✕ = 닫힘
QTest.mouseClick(d.b_x, Qt.LeftButton); wait(0.3)
assert gp._pdlg is None and not d.isVisible() and not gp.preset.isChecked(), "✕ 닫힘"
# [프리셋] 버튼 토글
QTest.mouseClick(gp.preset, Qt.LeftButton); wait(0.3); d = gp._pdlg; assert d is not None and d.isVisible() and d.pending is None
d.grab().save(os.path.join(d0, "preset.png")); print("그림:", os.path.join(d0, "preset.png"))
QTest.mouseClick(gp.preset, Qt.LeftButton); wait(0.3); assert gp._pdlg is None, "프리셋 버튼 = 닫힘"
print("OK preset popup"); os._exit(0)
