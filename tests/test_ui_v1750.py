"""v0.17.5 화면: 자동 창 접힘 메뉴(처음 = 모두 끔·접힘 · 단계 줄 위로 붙음 · ▸/▾ · 흐림 없음 · 음악 말풍선)
· 소스 목록 끌어다 놓기 안내(빈 목록 = 점선 상자 + 종류 3줄 · 파일 있으면 맨 아래 한 줄 · 끄는 중 = 파란 실선).
사용: python tests/test_ui_v1750.py <작업폴더>"""
import os, subprocess, sys, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
import main as M  # noqa: E402
from dtme import paths, ui_style  # noqa: E402
from dtme.project import Project, set_setting  # noqa: E402
from dtme.ui_autowin import FOOT_HINT, KIND_HINT  # noqa: E402
WORK = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "v1750_ui_test"); os.makedirs(WORK, exist_ok=True)
vids = []
for n in ("DJI_20251020094016_0010_D.MP4", "DJI_20251020101500_0011_D.MP4"):
    v = os.path.join(WORK, n)
    if not os.path.exists(v):
        subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", v], check=True)
    vids.append(v)
from dtme.ui_main import MainWindow  # noqa: E402
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1500, 850)


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
    return False


st, e = w.state, w.edit
ui_style.confirm = lambda *a, **k: "ok"
st.set_project(Project()); st.defer_proxy = True
set_setting("autowin", {"on": {"grade": True, "edit": True, "music": True, "render": True}})    # 예전 기억 = 안 따름
d = e.make_auto_window(from_edit=False); d.show(); wait(0.3)

# ---------------------------------------------------------------- 1) 처음 = 모두 끔·접힘 · 위로 붙음 · 흐림 없음
assert not any(sr.on or sr.open_ or sr.body.isVisible() for sr in d.stages.values())
assert all(sr.body.isEnabled() for sr in d.stages.values())
assert all(sr.height() == 34 + 2 * sr.frameWidth() or sr.height() <= 40 for sr in d.stages.values()), [sr.height() for sr in d.stages.values()]
gy = d.stages["grade"].mapTo(d, d.stages["grade"].rect().topLeft()).y()
sy = d.sum.mapTo(d, d.sum.rect().bottomLeft()).y()
assert 0 <= gy - sy <= 20, (gy, sy)
d.grab().save(os.path.join(WORK, "1_start.png"))
# 펼침 = ▾ · 접힘 = ▸ (그림으로 — 오른쪽 끝 글자 자리 밝기)
from PySide6.QtGui import QImage  # noqa: E402


def head_img(k):
    return d.stages[k].head.grab().toImage().convertToFormat(QImage.Format_RGB32)


def lit(img, x0, x1):
    return sum(1 for x in range(x0, x1) for y in range(img.height()) if QImage.pixelColor(img, x, y).lightness() > 150)


i0 = head_img("edit")
W_ = i0.width()
assert lit(i0, W_ - 26, W_ - 10) > 0, "▸ 보임"
assert lit(i0, 40, 84) > 0, "꺼져도 이름 = 단계 색(밝게)"
d.stages["edit"].set_on(True); d._sync(); wait(0.1)
assert d.stages["edit"].body.isVisible() and d.stages["edit"].open_
d.stages["grade"].set_on(True); d.stages["music"].set_on(True); d.stages["render"].set_open(True); d._sync(); wait(0.2)
d.grab().save(os.path.join(WORK, "2_some.png"))
d.stages["edit"].set_on(False); d._sync(); wait(0.1)
assert not d.stages["music"].body.isVisible() and not d.stages["music"].active()
d.stages["music"].press(20); wait(0.1)
assert d.stages["music"].bubble.startswith("편집을 켜야")
d.grab().save(os.path.join(WORK, "3_bubble.png"))
wait(d.stages["music"].BUBBLE_MS / 1000 + 0.5, lambda: not d.stages["music"].bubble)
assert not d.stages["music"].bubble, "말풍선 = 2.5초 뒤 사라짐"
for k in d.stages:
    d.stages[k].set_on(False)
d._sync()
print("접힘 메뉴: OK")

# ---------------------------------------------------------------- 2) 소스 목록 안내 · 끌어다 놓는 중
L = d.list
assert L.count() == 0 and not L.foot.isVisible() and len(KIND_HINT) == 3
img = L.viewport().grab().toImage()
assert img.width() > 300
md = QMimeData(); md.setUrls([QUrl.fromLocalFile(v) for v in vids])
ev = QDragEnterEvent(QPoint(100, 100), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
d.dragEnterEvent(ev)
assert L.dragging and "#4a8fe0" in L.styleSheet()
wait(0.1); d.grab().save(os.path.join(WORK, "4_empty_drag.png"))
d.dragLeaveEvent(QDragLeaveEvent())
assert not L.dragging and "#4a8fe0" not in L.styleSheet()
wait(0.1); d.grab().save(os.path.join(WORK, "5_empty.png"))
d.dragEnterEvent(QDragEnterEvent(QPoint(100, 100), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
d.dropEvent(QDropEvent(QPointF(100, 100), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
assert not L.dragging
assert wait(60, lambda: len(st.project.sources) == 2 and all(s.frames for s in st.project.sources))
wait(0.5)
assert L.count() >= 2 and L.foot.isVisible(), (L.count(), L.foot.isVisible())
fg = L.foot.geometry()
assert fg.bottom() <= L.height() and fg.top() > L.viewport().geometry().bottom() - 2, (fg, L.viewport().geometry())
assert FOOT_HINT.startswith("+ 영상")
d.grab().save(os.path.join(WORK, "6_files.png"))
d.list.clear(); d._fill_list(); wait(0.2)
assert L.foot.isVisible()
print("끌어다 놓기 안내: OK")
d.reject()
set_setting("autowin", {})                  # 다음 시험에 영향 없게
w.close()
print("OK test_ui_v1750")
os._exit(0)
