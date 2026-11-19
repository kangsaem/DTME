"""v0.17.3 시작 창 영상: 첫 장면에 멈춤 → [AUTO] = 재생(그림이 바뀜) → 끝나면 자동 창 ·
v0.17.4(MOSCO 기준) 재생 중 버튼 색 그대로 · 재생 중 [AUTO] 한 번 더 = 바로 · 그림 누름 = 안 건너뜀 ·
끌어다 놓기 = 재생 없이 · [취소]로 돌아오면 다시 첫 장면 · 시작 영상 = 워터마크 없음(왼쪽 위가 물색).
사용: python tests/test_ui_v1730.py"""
import os, sys, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
import main as M  # noqa: E402
from dtme import ff, paths  # noqa: E402
from dtme.ui_launch import Launcher  # noqa: E402
from dtme.ui_main import MainWindow  # noqa: E402
app = QApplication(sys.argv); M.dark(app)


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
    return False


clip = paths.asset("start.mp4")
pr = ff.probe(str(clip))
assert clip.exists() and 3.5 < float(pr["duration"]) < 5 and not pr.get("audio"), pr
mw = MainWindow()
la = Launcher(mw); la.show(); wait(0.2)
still = la.img.pixmap().toImage()
assert not still.isNull() and not la.playing and la.b_auto.isEnabled()
# 왼쪽 위(예전 워터마크 자리) = 고른 물색(글자 없음)
import numpy as np  # noqa: E402
im = still.convertToFormat(still.Format.Format_RGB888)
a = np.frombuffer(im.constBits(), np.uint8).reshape(im.height(), im.bytesPerLine())[:, :im.width() * 3].reshape(im.height(), im.width(), 3)
sx = im.width() / 640.0
box = a[int(56 * sx):int(108 * sx), int(54 * sx):int(220 * sx)].astype(float)
print("워터마크 자리 밝기 표준편차", round(float(box[..., 2].std()), 1), "· 파랑", round(float(box[..., 2].mean()), 1))
assert box[..., 2].std() < 12 and box[..., 2].mean() > box[..., 0].mean() + 60, "물색만"

seen = []


def poke(what):
    """자동 창이 뜨면 기록하고 [취소]."""
    from PySide6.QtWidgets import QApplication as _A
    dd = next((x for x in _A.topLevelWidgets() if type(x).__name__ == "AutoWindow" and x.isVisible()), None)
    if dd is None:
        QTimer.singleShot(50, lambda: poke(what)); return
    seen.append((what, time.time(), la.isVisible()))
    dd.cancel()


# 1) [AUTO] = 재생 → 끝나면 자동 창
t0 = time.time()
QTimer.singleShot(50, lambda: poke("auto"))
la.b_auto.click()
assert la.playing and la.b_auto.isEnabled()                              # v0.17.4 버튼 그대로(흐림 없음)
changed = wait(3.0, lambda: la.img.pixmap().toImage() != still)
print("재생 중 그림 바뀜:", changed)
assert wait(15, lambda: bool(seen)), "자동 창이 안 뜸"
took = seen[0][1] - t0
print("자동 창까지", round(took, 2), "초")
assert changed and 3.0 < took < 9.0 and seen[0][2] is False, seen       # 영상(4초)이 끝난 뒤 · 시작 창 숨김
assert wait(2, lambda: la.isVisible() and la.b_auto.isEnabled() and not la.playing)
assert la.img.pixmap().toImage() == still, "[취소] = 다시 첫 장면"
# 2) 재생 중 그림 누름 = 안 건너뜀(MOSCO 와 같음) · [AUTO] 한 번 더 = 바로 자동 창
seen.clear()
QTimer.singleShot(50, lambda: poke("skip"))
la.b_auto.click(); wait(0.5)
QTest.mouseClick(la, Qt.LeftButton, Qt.NoModifier, QPoint(200, 200)); wait(0.6)
assert la.playing and not seen, "그림 누름 = 계속 재생"
t0 = time.time()
la.b_auto.click()
assert wait(5, lambda: bool(seen))
print("건너뜀: 자동 창까지", round(seen[0][1] - t0, 2), "초")
assert seen[0][1] - t0 < 2.5
assert wait(2, lambda: la.isVisible() and la.b_auto.isEnabled())
# 3) 끌어다 놓기(run_auto 바로) = 재생 없음
seen.clear(); t0 = time.time()
QTimer.singleShot(50, lambda: poke("drop"))
la.run_auto([])
assert seen and seen[0][1] - t0 < 1.5 and not la.playing
print("OK test_ui_v1730", flush=True)
os._exit(0)
