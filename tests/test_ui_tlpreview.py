"""타임라인 프리뷰 점검(정지 화면·글자 표시·모니터에서 글자 이동·재생 중 컷 넘김).
사용: python tests/test_ui_tlpreview.py <샘플.MP4> <4K테스트.mp4> <작업폴더>"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import main as M
from dtme.project import new_text
from dtme.ui_main import MainWindow
S, T, WORK = sys.argv[1:4]; os.makedirs(WORK, exist_ok=True)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show()
def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond(): return True
st, e = w.state, w.edit
e.import_files([S, T]); wait(60, lambda: len(st.project.sources) == 2 and all(st.status.get(x.id) == "준비" for x in st.project.sources))
a, b = st.project.sources
e._select_source(a.id); wait(2)
a.sel_in, a.sel_out = 30, 90; e.send_to_timeline()          # 1초
e._select_source(b.id); wait(2)
b.sel_in, b.sel_out = 10, 100; e.send_to_timeline()
t = new_text(0.3, 1.6, "BOHOL · 2026.10.25"); t["cy"] = 0.3; st.project.titles.append(t); st.touch("titles")
wait(0.5)
# 타임라인 0.5초 클릭 → 타임라인 모드, 소스 a 의 30 + 0.5*59.94 ≈ 60 프레임
tl = e.timeline
QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(tl._x(0.5)), tl.height() - 6)); wait(3)
print("모드:", e.mode, "소스", e.cur_sid == a.id, "프레임", e.player.frame, "모니터 글자", len(e.player.mon.titles))
assert e.mode == "timeline" and e.cur_sid == a.id and abs(e.player.frame - 60) <= 1 and len(e.player.mon.titles) == 1
# 1.4초 → 두 번째 컷(b): 10 + (1.4-1.0)*59.94 ≈ 34
QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(tl._x(1.4)), tl.height() - 6)); wait(3)
print("1.4초 → 소스 b", e.cur_sid == b.id, "프레임", e.player.frame); assert e.cur_sid == b.id and abs(e.player.frame - 34) <= 2
w.grab().save(os.path.join(WORK, "shot_tl.png"))
# 모니터에서 글자 끌기
mon = e.player.mon
r = mon._title_rect(t, None)
QTest.mousePress(mon, Qt.LeftButton, Qt.NoModifier, r.center().toPoint())
QTest.mouseMove(mon, r.center().toPoint() + QPoint(0, 60))
QTest.mouseRelease(mon, Qt.LeftButton, Qt.NoModifier, r.center().toPoint() + QPoint(0, 60)); wait(0.2)
print("글자 끌기 cy:", round(t["cy"], 3)); assert t["cy"] > 0.35
w.undo(); wait(0.3); print("실행취소 cy:", st.project.titles[0]["cy"]); assert abs(st.project.titles[0]["cy"] - 0.3) < 1e-6
# 소스 목록 클릭 → 소스 모드
e._select_source(a.id); wait(1); print("소스 클릭 → 모드", e.mode); assert e.mode == "source"
# 재생: 0.7초에서 Space → 컷 a 끝에서 b 로 넘어가는지
QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(tl._x(0.7)), tl.height() - 6)); wait(3)
e._key("space"); ok = wait(8, lambda: e.cur_sid == b.id and e.player.is_playing())
print("재생 중 컷 넘김:", ok, "타임라인 시간", round(e.tl_time, 2))
e.player.pause()
print("UI TLPREVIEW OK")
