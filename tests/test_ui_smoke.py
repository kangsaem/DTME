"""화면 동작 점검(오프스크린). 사용:
python tests/test_ui_smoke.py <샘플.MP4> <LUT.cube> <합성4K.mp4> <작업폴더>
캡처: <작업폴더>/shot_*.png"""
import faulthandler; faulthandler.enable()
import sys, time, os, shutil, glob, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"]="offscreen"; os.environ["DTME_NO_AUDIO"]="1"
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
SAMPLE, LUT, TEST4K, WORK = sys.argv[1:5]
os.makedirs(WORK, exist_ok=True)
COPY = os.path.join(WORK, "DJI_20261025100118_0148_D.mp4")
import main as M
from dtme.ui_main import MainWindow
from dtme import paths
shutil.rmtree(paths.cache_dir(), ignore_errors=True)
shutil.copy(LUT, paths.lut_dir()/"DJI_DLogM.cube")
OUT=os.path.join(WORK,"out_ui"); shutil.rmtree(OUT, ignore_errors=True)
shutil.copy(TEST4K, COPY)
app=QApplication(sys.argv); M.dark(app)
w=MainWindow(); w.resize(1800,1000); w.show(); w.activateWindow()
def wait(sec, cond=None):
    t=time.time()
    while time.time()-t<sec:
        app.processEvents(); time.sleep(0.02)
        if cond and cond(): return True
    return False
st=w.state; e=w.edit
st.project.grade.update(lut="DJI_DLogM.cube", r_gain=1.25, b_gain=0.88)
o=st.project.output; o.folder=OUT; o.encoder="x264"; o.gpu_decode=False; o.prefix="보홀"
e.import_files([SAMPLE, COPY])
src=st.project.sources[0]
wait(2); w.grab().save(""+WORK+"/shot_loading.png")
wait(40, lambda: all(st.status.get(s.id)=="준비" for s in st.project.sources))
def key(k, mod=Qt.NoModifier, n=1):
    for _ in range(n): QTest.keyClick(e.player, k, mod); wait(0.03)
key(Qt.Key_Right, n=30); key(Qt.Key_I); key(Qt.Key_Right, n=90); key(Qt.Key_O); key(Qt.Key_Down)
key(Qt.Key_G); wait(15, lambda: e.grade.samples.count()==6 and all(not e.grade.samples.item(i).icon().isNull() for i in range(6)))
# 세로 + 크롭 표시
e.grade.orient.button(1).setChecked(True); e.grade._on_output(); wait(3)
print("세로 aspect:", round(e.player.mon.out_aspect,3))
w.grab().save(""+WORK+"/shot_edit.png")
# 소스 전환 → 즉시 '로딩 중'
e._select_source(st.project.sources[1].id); app.processEvents()
print("전환 직후 모니터 텍스트:", repr(e.player.mon.text), "이미지 없음:", e.player.mon.img is None)
wait(3); key(Qt.Key_Return)
e._select_source(src.id); wait(2); e.timeline_to_render()
print("렌더 리스트:", [(r.name) for r in st.project.render_items])
# 재생 시작 시 보정 화면 즉시 해제
e.player.seek(100); wait(2); g0=e.pgen; e.player.play(2.0); wait(0.3)
print("재생 시작 시 pgen 증가:", e.pgen>g0, "overlay:", e.player.overlay_frame); e.player.pause()
e.render_panel.render(); wait(300, lambda: not e.render_panel.running)
for r in st.project.render_items: print(" ", e.render_panel.status.get(r.id)[:60])
print(sorted(os.path.basename(x) for x in glob.glob(OUT+"/*")))
w.grab().save(""+WORK+"/shot_after.png")
w.tabs.setCurrentIndex(1); wait(0.3); w.grab().save(""+WORK+"/shot_settings.png")
