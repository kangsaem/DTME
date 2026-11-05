"""색 키프레임 ◆·★ 화면 점검. 사용: python tests/test_ui_gkeys.py <4K테스트.mp4>"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtWidgets import QApplication
import main as M
from dtme.ui_main import MainWindow
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.show()
def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond(): return True
st, e, gp = w.state, w.edit, w.edit.grade
e.import_files([sys.argv[1]]); wait(30, lambda: st.project.sources and st.status.get(st.project.sources[0].id) == "준비")
s = st.project.sources[0]
e.player.seek(20); wait(0.3)
gp.kbtn["r_gain"].click(); wait(0.2)                 # 20 프레임 키 (현재값)
print("키 1:", s.gkeys)
e.player.seek(80); wait(0.3)
gp.sliders["r_gain"].setValue(160); wait(0.5)        # 키 있는 항목 → 80 프레임에 자동 키
print("키 2:", s.gkeys["r_gain"])
assert [k["f"] for k in s.gkeys["r_gain"]] == [20, 80] and abs(s.gkeys["r_gain"][1]["v"] - 1.6) < 1e-6
e.player.seek(50); wait(0.3)
print("50 프레임 표시값:", gp.vals["r_gain"].text(), "슬라이더", gp.sliders["r_gain"].value())
assert 120 < gp.sliders["r_gain"].value() < 140
print("소스 바 ◆:", e.sbar.gkeys, "태그", e._tag(s.id)); assert e.sbar.gkeys == [20, 80]
e.player.seek(80); wait(0.3); gp.kbtn["r_gain"].click(); wait(0.2)     # 다시 누르면 삭제
print("삭제 후:", s.gkeys); assert [k["f"] for k in s.gkeys["r_gain"]] == [20]
w.undo(); wait(0.3); s = st.project.sources[0]; print("실행취소:", [k["f"] for k in s.gkeys["r_gain"]]); assert len(s.gkeys["r_gain"]) == 2
e._delete_gkeys(20); s = st.project.sources[0]; print("우클릭 삭제 20:", [k["f"] for k in s.gkeys["r_gain"]])
e._key("m"); wait(0.1); print("★:", s.stars, e.sbar.stars); assert s.stars == [e.player.frame]
e._key("m"); wait(0.1); assert not s.stars
e._key("m"); s.sel_in, s.sel_out = 0, 100; e.send_to_timeline(); wait(0.2)
print("타임라인 컷 색 키:", st.project.segments[-1].gkeys); assert st.project.segments[-1].gkeys
print("UI GKEYS OK")
