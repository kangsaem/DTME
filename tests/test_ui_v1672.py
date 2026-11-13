"""v0.16.72: 타임라인 출력 칸 · AUTO 창 작업 중 [취소] = 창 남김 · 파일 추가(시작 창·AUTO 창에 음악·사진) · 자동 편집 글자 = 전환 끝 1초 뒤 · 사각형 왼쪽 끝.
사용: python tests/test_ui_v1672.py <작업폴더>"""
import os, subprocess, sys, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QMimeData, QPointF, Qt, QTimer, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication, QDialog
import main as M
from dtme import paths
from dtme.project import Segment
from dtme.ui_main import MainWindow
from dtme.ui_launch import Launcher, collect_media
WORK = os.path.abspath(sys.argv[1]); os.makedirs(WORK, exist_ok=True)
FF = paths.ffmpeg()
vids = []
for i in range(2):
    v = os.path.join(WORK, f"DJI_2026102509{50 + i}00_000{i}_D.MP4")
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=8", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", v], check=True)
    vids.append(v)
mp3 = os.path.join(WORK, "song.mp3")
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=20", mp3], check=True)
png = os.path.join(WORK, "pic.png")
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240", "-frames:v", "1", png], check=True)
os.makedirs(os.path.join(WORK, "more"), exist_ok=True)
png2 = os.path.join(WORK, "more", "pic2.png")
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240", "-frames:v", "1", png2], check=True)
assert sorted(map(os.path.basename, collect_media([WORK]))) == sorted(map(os.path.basename, vids + [mp3, png]))
app = QApplication(sys.argv); M.dark(app)
mw = MainWindow(); mw.resize(1600, 900)


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond(): return True
    return False


# 1) 시작 창: 영상·음악·사진 한 번에 → AUTO 창 = 영상 줄 + 음악·사진 개수
la = Launcher(mw); la.show(); wait(0.2)
seen = {}


def poke():
    dlg = getattr(mw.edit, "_auto_dlg", None)
    if dlg is None or not dlg.isVisible():
        QTimer.singleShot(100, poke); return
    wait(1.0)
    seen["rows"] = len(dlg.rows)
    seen["media"] = dlg.media_lab.text()
    # AUTO 창에 사진 하나 더 끌어다 놓기
    md = QMimeData(); md.setUrls([QUrl.fromLocalFile(png2)])
    ev = QDropEvent(QPointF(10, 10), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    dlg.dropEvent(ev); wait(1.0)
    seen["media2"] = dlg.media_lab.text()
    # 2) 작업 중 [취소] = 창 남김
    for r in dlg.rows:                       # 분석 안 끝난 상태로(끝났으면 기다림 없이 바로 넘어감)
        r.result, r.prog = None, 0.5
    dlg.mode = "each"; dlg.waiting = "start"; dlg.set_busy(True)     # [보정+편집] 누른 뒤 분석 기다리는 중(작업 중)
    seen["busy"] = bool(dlg.busy or dlg.waiting)
    dlg.cancel(); wait(0.3)
    seen["after_cancel_visible"] = dlg.isVisible()
    seen["after_cancel_busy"] = bool(dlg.busy or dlg.waiting)
    dlg.reject()                             # 이제(작업 없음) [취소] = 예전대로 닫힘
QTimer.singleShot(100, poke)
quit_called = []
la._quit = lambda: quit_called.append(1)
la.run_auto([WORK])
print(seen)
assert seen["rows"] == 2 and seen["media"] == "음악 1 · 사진 1", seen
assert seen["media2"] == "음악 1 · 사진 2", seen
assert seen["busy"] and seen["after_cancel_visible"] and not seen["after_cancel_busy"], seen
st, e = mw.state, mw.edit
p = st.project
assert len(p.audios) == 1 and len(p.images) == 2
# 3) 파일 추가 버튼 이름
from PySide6.QtWidgets import QPushButton
assert any(b.text() == "파일 추가" and b.toolTip() == "영상·사진·음악" for b in e.findChildren(QPushButton))
# 4) 타임라인 출력 칸
mw.show(); wait(60, lambda: all(st.status.get(s.id) == "준비" for s in p.sources))
a, b = p.sources
a.out = "vertical"
p.segments = [Segment(a.id, 0, 120), Segment(b.id, 0, 120)]
st.touch("segments"); wait(0.3)
assert e.tl_out.isVisible() and e.tl_out.itemData(0) == "" and "인스타" in e.tl_out.itemText(0)
e.timeline_to_render(); wait(0.1)
assert p.render_items[-1].orientation == "vertical"              # 자동 = 첫 컷
e.tl_out.setCurrentIndex(e.tl_out.findData("horizontal")); e._tl_out_chosen(); wait(0.1)
assert p.tl_out == "horizontal"
e.timeline_to_render(); wait(0.1)
assert p.render_items[-1].orientation == "horizontal"            # 정한 값
from dtme.project import Project
f = os.path.join(WORK, "p.json"); p.save(f); assert Project.load(f).tl_out == "horizontal"
print("OK test_ui_v1672", flush=True); os._exit(0)
