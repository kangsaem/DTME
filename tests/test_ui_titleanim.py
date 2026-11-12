"""v0.16.57: 글자·사각형·이미지 창의 인/아웃 [페이드 | → | ← | ↑ | ↓] + 모니터가 밀린 자리에 그림. python tests/test_ui_titleanim.py"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
import numpy as np
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
import main as M
from dtme.project import anim_offset, new_rect, new_text, new_title_image, title_anim
from dtme.ui_main import MainWindow
from dtme.ui_titles import ImageDialog, RectDialog, TextDialog
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show()


def wait(sec):
    t = time.time()
    while time.time() - t < sec: app.processEvents(); time.sleep(0.01)


# 1) 창: 버튼 → 값
for dlg_cls, d in ((TextDialog, new_text(0, 3, "가")), (RectDialog, new_rect(0, 3)), (ImageDialog, new_title_image("x", 0, 3))):
    dlg = dlg_cls(d, w); dlg.show(); wait(0.1)
    assert dlg.anim["ain"].checkedButton().property("key") == "fade" and dlg.anim["aout"].checkedButton().property("key") == "fade"
    dlg.anim["ain"].buttons()[1].click(); dlg.anim["aout"].buttons()[4].click(); wait(0.05)
    assert (d["ain"], d["aout"]) == ("right", "down"), d
    if dlg_cls is TextDialog and len(sys.argv) > 1:
        os.makedirs(sys.argv[1], exist_ok=True); dlg.grab().save(os.path.join(sys.argv[1], "text_dialog.png"))
    dlg.reject(); wait(0.05)
    assert "ain" not in d and "aout" not in d, "취소 = 되돌림"
# 2) 계산
rc = new_rect(0.0, 3.0); rc.update(cx=0.3, cy=0.3, w=0.2, h=0.1, color="#ff0000", opacity=1.0, radius=0, fade=1.0, ain="right", aout="down")
assert title_anim(rc, 0.0)[1:] == ("in", "right", 1.0) and title_anim(rc, 1.5) == (1.0, None, "", 0.0) and title_anim(rc, 3.0)[1:] == ("out", "down", 1.0)
assert anim_offset("in", "right", 1.0, (100, 50, 200, 80), 1920, 1080) == (-300.0, 0.0)       # 왼쪽 화면 밖에서
assert anim_offset("out", "down", 1.0, (100, 50, 200, 80), 1920, 1080) == (0.0, 1030.0)       # 아래 화면 밖으로
# 3) 모니터: 밀린 자리에 그림
mon = w.edit.player.mon
img = QImage(1920, 1080, QImage.Format_RGB32); img.fill(QColor("#000000")); mon.set_image(img); wait(0.2)


def red_left():
    g = mon.grab().toImage().convertToFormat(QImage.Format_RGB888)
    a = np.frombuffer(g.constBits(), np.uint8).reshape(g.height(), g.bytesPerLine())[:, :g.width() * 3].reshape(g.height(), g.width(), 3).astype(int)
    xs = np.nonzero(((a[..., 0] > 180) & (a[..., 1] < 60) & (a[..., 2] < 60)).any(0))[0]
    return None if len(xs) == 0 else int(xs.min())


mon.title_anim = {}; mon.set_titles([(rc, 1.0, None, None)], ""); wait(0.2)
x0 = red_left(); assert x0 is not None
c = mon._out_rect
_a, ph, key, f = title_anim(rc, 0.5)
mon.title_anim = {rc["id"]: (ph, key, f)}; mon.set_titles([(rc, 1.0, None, None)], ""); wait(0.2)
x1 = red_left()
r = mon._title_rect(rc, None)
want = anim_offset(ph, key, f, (r.left() - c.left(), r.top() - c.top(), r.width(), r.height()), c.width(), c.height(), 2 * c.width() / 1920)[0]
print("모니터 사각형 왼쪽:", x0, "→", x1, "(밀기", round(want, 1), ")")
assert x1 is not None and abs((x1 - x0) - want) <= 2 and want < -5
mon.title_anim = {rc["id"]: ("in", "right", 1.0)}; mon.set_titles([(rc, 1.0, None, None)], ""); wait(0.2)
assert red_left() is None, "처음 = 화면 밖"
print("OK test_ui_titleanim"); os._exit(0)
