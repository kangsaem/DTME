"""v0.16.44: 프리셋 팝업 = 바깥 클릭으로 닫힘(안쪽 클릭 그대로 · [프리셋] 버튼 다시 = 닫힘). python tests/test_ui_presetclose.py"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import main as M
from dtme.ui_main import MainWindow
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show()
def wait(sec):
    t = time.time()
    while time.time() - t < sec: app.processEvents(); time.sleep(0.01)
gp = w.edit.grade
gp.open_presets(); wait(0.3); d = gp._pdlg; assert d and d.isVisible()
QTest.mouseClick(d, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5)); wait(0.3)
assert gp._pdlg is d and d.isVisible(), "안쪽 클릭 = 그대로"
QTest.mouseClick(w.edit.player, Qt.LeftButton, Qt.NoModifier, QPoint(50, 50)); wait(0.3)
assert gp._pdlg is None and not d.isVisible() and not gp.preset.isChecked(), "바깥 클릭 = 닫힘"
gp.open_presets(); wait(0.3); d = gp._pdlg
QTest.mouseClick(gp.preset, Qt.LeftButton); wait(0.3)
assert gp._pdlg is None, "프리셋 버튼 = 닫힘(다시 안 열림)"
QTest.mouseClick(gp.preset, Qt.LeftButton); wait(0.3); assert gp._pdlg is not None, "다시 누르면 열림"
print("OK preset popup"); os._exit(0)
