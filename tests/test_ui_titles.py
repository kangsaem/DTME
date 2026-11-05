"""타임라인 글자·이미지·음악 화면 점검. 사용: python tests/test_ui_titles.py <4K테스트.mp4> <작업폴더>"""
import os, sys, time, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
import numpy as np
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
import main as M
from dtme import paths, ff
from dtme.ui_main import MainWindow
from dtme.ui_titles import TextDialog
T4K, WORK = sys.argv[1:3]; os.makedirs(WORK, exist_ok=True)
mus = os.path.join(WORK, "m.m4a"); subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=800:d=5", "-c:a", "aac", mus], check=True)
png = os.path.join(WORK, "logo.png"); a = np.zeros((80, 160, 4), np.uint8); a[:] = (240, 200, 40, 255)
subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "160x80", "-i", "-", "-frames:v", "1", png], input=a.tobytes(), check=True)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show()
def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond(): return True
st, e = w.state, w.edit
st.project.output.folder = os.path.join(WORK, "out"); st.project.output.encoder = "x264"; st.project.output.gpu_decode = False
e.import_files([T4K, png, mus]); wait(30, lambda: st.project.sources and st.status.get(st.project.sources[0].id) == "준비" and st.project.images and st.project.images[0].width)
print("목록: 영상", e.src_list.count(), "이미지", e.img_list.count(), "음악", e.mus_list.count(), "음악 길이", st.project.audios[0]["dur"])
s = st.project.sources[0]
for a_, b_ in ((0, 50), (50, 110)):
    s.sel_in, s.sel_out = a_, b_; e.send_to_timeline()
# 글자: 창에서 입력하고 닫음
def fake_exec(self):
    self.text.setPlainText("BOHOL · 2026.10.25\n발리카삭 18m"); self.bg.button(2).click(); return 0
TextDialog.exec = fake_exec
e.tl_time = 0.2; e.add_text(); wait(0.2)
t = st.project.titles[0]; print("글자:", repr(t["text"]), t["t0"], t["t1"], t["bg"])
assert t["text"].startswith("BOHOL") and t["bg"] == "band"
# 빈 글자는 사라짐
TextDialog.exec = lambda self: 0
e.add_text(); wait(0.1); print("빈 글자 추가 후 개수:", len(st.project.titles)); assert len(st.project.titles) == 1
# 이미지 → 타임라인
e.tl_time = 0.5; e.add_title_image(st.project.images[0].id); print("이미지 타이틀:", st.project.titles[-1]["kind"], st.project.titles[-1]["t0"])
# 음악 클릭
e._on_mus_clicked(e.mus_list.item(0)); wait(0.1); m = st.project.music[0]; print("음악:", m["t0"], round(m["len"], 2))
# 타임라인에서 글자 끝 끌기(자석: 첫 컷 끝 50/59.94=0.834초)
tl = e.timeline; wait(0.3)
r = next(rr for k, d, rr in tl._ov_rects() if d is t)
end_x = r.right(); target = tl._x(50 / 59.94 * 1.0 * 1)  # 컷1 끝
QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(end_x) - 1, int(r.center().y())))
QTest.mouseMove(tl, QPoint(int(target) + 3, int(r.center().y())))
QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(int(target) + 3, int(r.center().y()))); wait(0.2)
print("글자 끝 → 자석:", round(t["t1"], 3), "컷1 끝", round(tl.items[0][6] + tl.items[0][1], 3))
assert abs(t["t1"] - (tl.items[0][6] + tl.items[0][1])) < 1e-6
# 우클릭 삭제 → 실행취소
ri = next(rr for k, d, rr in tl._ov_rects() if d.get("kind") == "image")
QTest.mouseClick(tl, Qt.RightButton, Qt.NoModifier, ri.center().toPoint()); wait(0.2)
print("이미지 우클릭 삭제 후:", [d["kind"] for d in st.project.titles]); assert len(st.project.titles) == 1
w.undo(); wait(0.3); print("실행취소:", [d["kind"] for d in st.project.titles]); assert len(st.project.titles) == 2
# 재생 위치 클릭
QTest.mouseClick(e.timeline, Qt.LeftButton, Qt.NoModifier, QPoint(int(e.timeline._x(1.0)), e.timeline.height() - 8)); wait(0.1)
print("재생 위치:", round(e.tl_time, 2))
w.grab().save(os.path.join(WORK, "shot_titles.png"))
# 렌더 리스트로 → 렌더
e.timeline_to_render(); it = st.project.render_items[-1]; print("렌더 항목: 글자", len(it.titles), "음악", len(it.music))
e.render_panel.render(); wait(300, lambda: not e.render_panel.running)
print(e.render_panel.status.get(it.id, "")[:80])
outs = [f for f in os.listdir(os.path.join(WORK, "out")) if f.endswith(".mp4")]; print("출력:", outs)
assert outs and ff.probe(os.path.join(WORK, "out", outs[0]))["has_audio"]
print("UI TITLES OK")
