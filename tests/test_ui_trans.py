"""컷편집(화면 전환) 화면 점검. 사용: python tests/test_ui_trans.py <4K테스트.mp4> <작업폴더>"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import main as M
from dtme.ui_main import MainWindow
from dtme.ui_trans import TransitionDialog
SAMPLE, WORK = sys.argv[1:3]; os.makedirs(WORK, exist_ok=True)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1800, 1000); w.show()
def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond(): return True
st, e = w.state, w.edit
e.import_files([SAMPLE]); wait(60, lambda: st.project.sources and st.status.get(st.project.sources[0].id) == "준비")
src = st.project.sources[0]
for a, b in ((0, 40), (40, 80), (80, 120)):
    src.sel_in, src.sel_out = a, b; e.send_to_timeline()
wait(0.3)
segs = st.project.segments
before = st.project.segs_seconds(segs)
e.sel_cut = ""; e.edit_transition(); print("선택 없음:", e.status.text()[-20:])
# 2번째 컷 선택 → 창 열고 회전 줌인 클릭
e._on_cut_selected(segs[1].id)
def click():
    dlg = next(x for x in app.topLevelWidgets() if isinstance(x, TransitionDialog) and x.isVisible())
    dlg.grab().save(os.path.join(WORK, "shot_trans_dialog.png"))
    print("첫 컷 아님 → 모두 사용 가능:", all(b.isEnabled() for b in dlg.buttons.values()))
    a = dlg.buttons["rotzoomin"].a
    print("샘플 = 실제 프레임:", a.width() >= 240 and a.toImage().pixelColor(5, 5).name() != "#3f6fa8")
    for k in ("rotzoomin", "dissolve"):
        dlg.buttons[k].t = 0.35 + 0.9 * 0.5; dlg.buttons[k].update()
    dlg.grab().save(os.path.join(WORK, "shot_trans_dialog_mid.png"))
    dlg.buttons["rotzoomin"].clicked.emit("rotzoomin")
QTimer.singleShot(300, click); e.edit_transition()
print("전환:", segs[1].trans, "길이", round(before, 3), "→", round(st.project.segs_seconds(segs), 3))
assert segs[1].trans["type"] == "rotzoomin"
# 첫 컷: 페이드만
e._on_cut_selected(segs[0].id)
def click0():
    dlg = next(x for x in app.topLevelWidgets() if isinstance(x, TransitionDialog) and x.isVisible())
    en = [k for k, b in dlg.buttons.items() if b.isEnabled()]; print("첫 컷 사용 가능:", en)
    dlg.buttons["fadewhite"].clicked.emit("fadewhite")
QTimer.singleShot(300, click0); e.edit_transition()
w.undo(); wait(0.2); print("실행취소 후 첫 컷:", st.project.segments[0].trans)
e.zoom.setValue(120); wait(0.3)
e.tl_scroll.grab().save(os.path.join(WORK, "shot_trans_timeline.png"))
e.timeline_to_render(); print("렌더 항목 전환 복사:", st.project.render_items[-1].segs[1].trans)
# v0.16.11: 나비 클릭 = 선택 + 미리보기(모니터 위 반복), 우클릭·Del = 빼기, 더블클릭 = 창
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
segs = st.project.segments
segs[1].trans = {"type": "rotzoomin", "dur": 0.5}; st.touch("segments"); wait(0.3)
tl = e.timeline
r = dict(tl._trans_rects())[segs[1].id]
QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(r.center().x()), int(r.center().y())))
print("나비 선택:", e.sel_trans == segs[1].id, e._del_target)
ok = wait(240, lambda: e.trans_prev.isVisible())
print("미리보기 재생:", ok, len(e._tp_frames), "장")
assert ok and len(e._tp_frames) > 20
wait(0.8)
e.player.mon.grab().save(os.path.join(WORK, "shot_trans_preview.png"))
tl.grab().save(os.path.join(WORK, "shot_trans_bowtie.png"))
t0 = time.time(); e.trans_prev.stop(); tl.transSelected.emit(segs[1].id); wait(1, lambda: e.trans_prev.isVisible())
print("같은 경계 다시 = 바로:", e.trans_prev.isVisible(), round(time.time() - t0, 2), "초")
e._key("esc"); print("Esc 닫힘:", not e.trans_prev.isVisible())
e._key("del"); wait(0.2); print("Del 뺌:", segs[1].trans == {})
assert segs[1].trans == {}
w.undo(); wait(0.2); segs = st.project.segments; print("실행취소:", segs[1].trans)
r = dict(tl._trans_rects())[segs[1].id]
QTest.mouseClick(tl, Qt.RightButton, Qt.NoModifier, QPoint(int(r.center().x()), int(r.center().y())))
wait(0.2); print("우클릭 뺌:", st.project.segments[1].trans == {})
assert st.project.segments[1].trans == {}
fr = e._trans_frames(1)
print("컷편집 샘플 실제 프레임:", fr is not None)
assert fr is not None
print("UI TRANS OK")
