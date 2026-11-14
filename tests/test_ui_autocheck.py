"""v0.16.37 AUTO 창: ✓ 칸 누른 채 쓸기(칠하기·되돌리면 원래대로) · 왼쪽 아래 버전.
사용: python tests/test_ui_autocheck.py"""
import os, subprocess, sys, tempfile, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import main as M
from dtme import __version__, paths
from dtme.ui_main import MainWindow
d = tempfile.mkdtemp(); vids = []
for i in range(5):
    v = os.path.join(d, f"c{i}.mp4")
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", v], check=True); vids.append(v)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1600, 900); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond():
            return True


st, e = w.state, w.edit
e.import_files(vids); wait(60, lambda: len(st.project.sources) == 5 and all(st.status.get(x.id) == "준비" for x in st.project.sources))
print("소스", len(st.project.sources), [st.status.get(x.id) for x in st.project.sources], flush=True)
from dtme import ui_auto  # noqa: E402
ui_auto.AutoDialog.analyze_all = lambda self: None     # 체크 쓸기만 봄 — 뒤 분석 스레드 없이(Windows 종료 때 접근 위반 방지)
dlg = e.make_auto_dialog(); dlg.show(); wait(1)
print("창", dlg.list.count(), flush=True)
assert dlg.ver_lab.text() == f"DTME {__version__}"
vp = dlg.list.viewport()
pt = lambda i: QPoint(dlg.list.visualItemRect(dlg.list.item(i)).left() + 14, dlg.list.visualItemRect(dlg.list.item(i)).center().y())  # noqa: E731
ck = lambda: [r.checked for r in dlg.rows]  # noqa: E731
print("체크", ck(), flush=True)
assert ck() == [True] * 5
sel0 = [it.isSelected() for it in (dlg.list.item(i) for i in range(5))]
# 1번 줄 누름(끔) → 3번까지 쓸기 → 2번으로 되돌림 → 놓기
QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, pt(1)); wait(0.05)
assert ck() == [True, False, True, True, True]
QTest.mouseMove(vp, pt(3)); wait(0.05)
assert ck() == [True, False, False, False, True], ck()
QTest.mouseMove(vp, pt(2)); wait(0.05)
assert ck() == [True, False, False, True, True], ck()
QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, pt(2)); wait(0.2)
assert ck() == [True, False, False, True, True]
assert [it.isSelected() for it in (dlg.list.item(i) for i in range(5))] == sel0, "체크 쓸기 = 줄 선택 안 바뀜"
# 꺼진 줄에서 시작 = 켬 칠하기, 위로
QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, pt(2)); wait(0.05)
QTest.mouseMove(vp, pt(0)); wait(0.05)
QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, pt(0)); wait(0.2)
assert ck() == [True, True, True, True, True], ck()
# 한 번 클릭 = 그 줄만 바뀜
QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, pt(4)); wait(0.2)
assert ck() == [True, True, True, True, False]
# v0.16.91 Shift+클릭 = 지난번 누른 줄(4번 = 끔)부터 여기(1번)까지 같은 상태
QTest.mouseClick(vp, Qt.LeftButton, Qt.ShiftModifier, pt(1)); wait(0.2)
assert ck() == [True, False, False, False, False], ck()
QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, pt(1)); wait(0.2)      # 1번 켬(기준 = 켬)
QTest.mouseClick(vp, Qt.LeftButton, Qt.ShiftModifier, pt(4)); wait(0.2)
assert ck() == [True, True, True, True, True], ck()
QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, pt(4)); wait(0.2)
assert ck() == [True, True, True, True, False]
# 이름 쪽 클릭 = 줄 선택(체크 그대로)
r = dlg.list.visualItemRect(dlg.list.item(3))
QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, QPoint(r.left() + 120, r.center().y())); wait(0.2)
assert dlg.list.item(3).isSelected() and ck() == [True, True, True, True, False]
dlg.grab().save(os.path.join(d, "autocheck.png"))
dlg.hide(); wait(0.3)
print("OK test_ui_autocheck", flush=True)
sys.stderr.flush()
if os.name == "nt":      # Windows: ExitProcess 의 DLL 정리 중 Qt 가 가끔 접근 위반(테스트 끝난 뒤) → 바로 끝냄
    import ctypes
    ctypes.windll.kernel32.TerminateProcess(ctypes.windll.kernel32.GetCurrentProcess(), 0)
os._exit(0)
