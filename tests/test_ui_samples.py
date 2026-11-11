"""v0.16.49: 샘플 = 왼쪽 패널에서 빠지고 창으로. 1536×864(1920×1080 125%)에서 왼쪽 패널 스크롤 없음(묶음 모두 편 상태).
[샘플](G) → 6장 + 창 뜸 · 창이 닫혀 있으면 샘플 화면을 안 만듦 · 타일 클릭 = 모니터에 크게(예전과 같음) · Esc/버튼 = 닫힘.
사용: python tests/test_ui_samples.py [캡처 저장 폴더]"""
import os, subprocess, sys, tempfile, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_AUDIO"] = "1"
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import main as M
from dtme import ff, paths
from dtme.ui_main import MainWindow
d = tempfile.mkdtemp(); v = os.path.join(d, "k0.mp4")
subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=8",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", v], check=True)
app = QApplication(sys.argv); M.dark(app)
w = MainWindow(); w.resize(1536, 834); w.show()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents(); time.sleep(0.01)
        if cond and cond():
            return True


st, e, gp = w.state, w.edit, w.edit.grade
for sct in gp.sections:                         # 묶음 모두 편 상태
    if not sct.head.isChecked():
        sct.head.click()
wait(0.8)
sb = gp._scroll.verticalScrollBar()
print("왼쪽 패널: 내용", gp._scroll.widget().sizeHint().height(), "· 보이는 높이", gp._scroll.viewport().height(), "· 스크롤 최대", sb.maximum(), "· 커브", gp.curve.height())
assert sb.maximum() == 0, "1536×864 에서 스크롤이 생김"
assert gp.curve.height() >= 120, gp.curve.height()
e.import_files([v]); assert wait(60, lambda: st.project.sources and st.status.get(st.project.sources[0].id) == "준비")
s = st.project.sources[0]; e._select_source(s.id); wait(1.0)
assert not gp.smp_win.isVisible() and gp.b_smp.text() == "샘플 보기"
# 닫혀 있으면 샘플 화면을 안 만듦
made = []
orig = ff._render_preview
ff._render_preview = lambda c, g: (made.append(1), orig(c, g))[1]
gp._set("r_gain", 1.2); wait(1.5); n0 = len(made)
# [샘플](G) = 6장 + 창
QTest.keyClick(e.player, Qt.Key_G)
assert wait(30, lambda: gp.samples.count() == 6 and all(not gp.samples.item(i).icon().isNull() for i in range(6)))
assert gp.smp_win.isVisible() and gp.b_smp.isChecked() and gp.b_smp.text() == "샘플 보기 6/6"
assert gp.samples.width() >= 3 * 320 and sb.maximum() == 0
# 띄워 둔 채 값 바꿈 → 샘플도 다시
m0 = len(made); gp._set("r_gain", 1.4); wait(6, lambda: len(made) >= m0 + 7); assert len(made) >= m0 + 7, (len(made), m0)
# 타일 클릭 = 모니터에 크게(예전과 같음)
shown = []
osi = e.player.show_image
e.player.show_image = lambda im: (shown.append(1), osi(im))[1]
gp._on_sample(gp.samples.item(4)); wait(0.3)
assert shown, "타일을 눌러도 모니터에 안 뜸"                    # 예전과 같음: 누른 샘플을 모니터에 크게
e.player.show_image = osi
if len(sys.argv) > 1:
    os.makedirs(sys.argv[1], exist_ok=True); w.grab().save(os.path.join(sys.argv[1], "samples_main.png")); gp.smp_win.grab().save(os.path.join(sys.argv[1], "samples_win.png"))
# 닫기: 버튼 · Esc
gp.b_smp.click(); wait(0.3); assert not gp.smp_win.isVisible() and not gp.b_smp.isChecked()
m1 = len(made); gp._set("r_gain", 1.1); wait(2.0)
assert len(made) - m1 <= 2, "창이 닫혔는데 샘플을 만듦"          # 모니터 화면만(보정 + 반반이면 2장)
gp.b_smp.click(); wait(0.3); assert gp.smp_win.isVisible()
QTest.keyClick(gp.smp_win, Qt.Key_Escape); wait(0.3); assert not gp.smp_win.isVisible() and not gp.b_smp.isChecked()
print("닫힌 동안 만든 화면", n0, "→ OK test_ui_samples")
os._exit(0)
