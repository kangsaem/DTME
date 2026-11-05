"""이미지 레이어·인/아웃 드래그 화면 점검(오프스크린).
사용: python tests/test_ui_layers.py <샘플.MP4> <LUT.cube> <작업폴더>
캡처: <작업폴더>/shot_layers*.png"""
import faulthandler; faulthandler.enable()  # noqa: E702
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["DTME_NO_AUDIO"] = "1"
import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

SAMPLE, LUT, WORK = sys.argv[1:4]
os.makedirs(WORK, exist_ok=True)
import main as M  # noqa: E402
from dtme import ff, paths  # noqa: E402
from dtme.ui_main import MainWindow  # noqa: E402

shutil.rmtree(paths.cache_dir(), ignore_errors=True)
shutil.copy(LUT, paths.lut_dir() / "DJI_DLogM.cube")
OUT = os.path.join(WORK, "out_layers")
shutil.rmtree(OUT, ignore_errors=True)
# 테스트 이미지: 투명 PNG 600x300(왼쪽 빨강 불투명, 오른쪽 흰색 반투명)
a = np.zeros((300, 600, 4), np.uint8)
a[:, :300] = (230, 40, 30, 255)
a[:, 300:] = (255, 255, 255, 128)
PNG = os.path.join(WORK, "logo.png")
subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "600x300", "-i", "-",
                "-frames:v", "1", PNG], input=a.tobytes(), check=True)

app = QApplication(sys.argv)
M.dark(app)
w = MainWindow()
w.resize(1800, 1000)
w.show()
w.activateWindow()


def wait(sec, cond=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.02)
        if cond and cond():
            return True
    return False


st, e = w.state, w.edit
st.project.grade.update(lut="DJI_DLogM.cube", r_gain=1.25, b_gain=0.88)
o = st.project.output
o.folder, o.encoder, o.gpu_decode, o.prefix = OUT, "x264", False, "보홀"
e.import_files([SAMPLE, PNG])
wait(60, lambda: st.project.sources and st.status.get(st.project.sources[0].id) == "준비"
     and st.project.images and st.project.images[0].width)
src, img = st.project.sources[0], st.project.images[0]
print("이미지 목록:", e.img_list.isVisible(), e.img_list.count(), (img.width, img.height))
assert e.img_list.count() == 1 and (img.width, img.height) == (600, 300)

# ---- D: 인/아웃 끝 드래그 시 프리뷰 위치 고정
e.player.seek(60); wait(0.5)
f0 = e.player.frame
e._io_drag_start(); e._io_drag("in", 20); e._io_drag("out", 180); e._after_io(); wait(0.3)
print("D: 드래그 후 IO", src.io, "프레임", f0, "→", e.player.frame)
assert src.io == (20, 180) and e.player.frame == f0
# 실제 마우스로 소스 바 끝 드래그
sb = e.sbar
x_in = int(sb._x(20))
QTest.mousePress(sb, Qt.LeftButton, Qt.NoModifier, QPoint(x_in, 15))
QTest.mouseMove(sb, QPoint(x_in + 40, 15))
QTest.mouseRelease(sb, Qt.LeftButton, Qt.NoModifier, QPoint(x_in + 40, 15))
wait(0.3)
print("D: 마우스 드래그 후 IO", src.io, "프레임", e.player.frame)
assert src.io[0] > 20 and e.player.frame == f0

# ---- A: 이미지 클릭 → 레이어
e._on_img_clicked(e.img_list.item(0)); wait(0.3)
lay = src.layers[0]
print("레이어:", {k: lay[k] for k in ("fin", "fout", "cx", "cy", "scale")}, "스틸 바 높이", e.lbar.height())
assert (lay["fin"], lay["fout"]) == src.io and lay["scale"] == 1.0 and e.lbar.height() > 0
for _ in range(3):
    e._on_img_clicked(e.img_list.item(0))
wait(0.2)
print("4번 클릭 → 레이어 수", len(src.layers), "상태", e.status.text())
assert len(src.layers) == 3
e.remove_layer(src.layers[2]["id"]); e.remove_layer(src.layers[1]["id"])
assert len(src.layers) == 1
e.player.seek(100); wait(1.0)
mon = e.player.mon
print("모니터 표시 레이어:", len(mon.layers), "출력 영역", mon._out_rect)
assert len(mon.layers) == 1
w.grab().save(os.path.join(WORK, "shot_layers.png"))

# 모니터에서 드래그로 이동 (가운데 → 오른쪽 아래)
r = mon._layer_rect(lay, (600, 300))
c = r.center().toPoint()
QTest.mousePress(mon, Qt.LeftButton, Qt.NoModifier, c)
QTest.mouseMove(mon, c + QPoint(int(mon._out_rect.width() * 0.2), int(mon._out_rect.height() * 0.1)))
QTest.mouseRelease(mon, Qt.LeftButton, Qt.NoModifier, c + QPoint(int(mon._out_rect.width() * 0.2), int(mon._out_rect.height() * 0.1)))
wait(0.2)
print("이동 후 cx,cy:", round(lay["cx"], 3), round(lay["cy"], 3))
assert abs(lay["cx"] - 0.7) < 0.02 and abs(lay["cy"] - 0.6) < 0.02
# 모서리 드래그로 확대 (오른쪽 아래 모서리를 중심에서 1.5배 거리로)
r = mon._layer_rect(lay, (600, 300))
ctr, br = r.center(), r.bottomRight()
to = ctr + (br - ctr) * 1.5
QTest.mousePress(mon, Qt.LeftButton, Qt.NoModifier, br.toPoint())
QTest.mouseMove(mon, to.toPoint())
QTest.mouseRelease(mon, Qt.LeftButton, Qt.NoModifier, to.toPoint())
wait(0.2)
print("확대 후 scale:", round(lay["scale"], 3))
assert 1.4 < lay["scale"] < 1.6
# 실행취소 → 확대 취소
w.undo(); wait(0.3)
src = st.project.sources[0]; lay = src.layers[0]
print("실행취소 후 scale:", round(lay["scale"], 3), "cx", round(lay["cx"], 3))
assert abs(lay["scale"] - 1.0) < 1e-6 and abs(lay["cx"] - 0.7) < 0.02

# 스틸 바 끝 드래그 → 레이어 아웃 (프리뷰 고정)
f0 = e.player.frame
e.lbar.dragStarted.emit(lay["id"]); e._layer_drag(lay["id"], "out", 150); wait(0.2)
print("레이어 범위:", lay["fin"], lay["fout"], "프레임", f0, "→", e.player.frame)
assert lay["fout"] == 150 and e.player.frame == f0
e.player.seek(160); wait(0.3)
print("레이어 범위 밖 프레임 160 → 모니터 레이어", len(mon.layers))
assert len(mon.layers) == 0
e.player.seek(100); wait(0.8)
w.grab().save(os.path.join(WORK, "shot_layers_moved.png"))

# ---- ▼ 타임라인 → 레이어 사본 / 렌더
e.send_to_timeline(); wait(0.2)
seg = st.project.segments[-1]
print("타임라인 컷 레이어:", len(seg.layers), seg.layers[0]["fin"], seg.layers[0]["fout"])
assert len(seg.layers) == 1 and seg.layers[0]["id"] != lay["id"]
e.timeline_to_render(); wait(0.2)
assert st.project.render_items[-1].segs[0].layers
# 세로도 하나
e.grade.orient.button(1).setChecked(True); e.grade._on_output(); wait(1.0)
print("세로 out_wh:", mon.out_wh, "레이어", len(mon.layers))
w.grab().save(os.path.join(WORK, "shot_layers_vertical.png"))
e.send_to_render(); wait(0.2)
e.render_panel.render()
wait(600, lambda: not e.render_panel.running)
for it in st.project.render_items:
    print(" ", it.orientation, e.render_panel.status.get(it.id, "")[:80])
outs = sorted(f for f in os.listdir(OUT) if f.endswith(".mp4"))
print("출력:", outs)
assert len(outs) == 2
# 가로 결과에서 레이어 위치(cx 0.7, cy 0.6)에 빨강이 있는지 (컷 안 레이어 구간 가운데 프레임)
cut = st.project.render_items[0].segs[0]
mid = ((lay["fin"] + 150) // 2 - cut.fin) / 59.94
fo = next(os.path.join(OUT, f) for f in outs if ff.probe(os.path.join(OUT, f))["width"] == 1920)
x0, y0 = int(0.7 * 1920 - 300), int(0.6 * 1080 - 150)
raw = ff.run([paths.ffmpeg(), "-v", "error", "-ss", f"{mid:.3f}", "-i", fo, "-frames:v", "1",
              "-vf", f"crop=200:200:{x0 + 50}:{y0 + 50},scale=in_color_matrix=bt709:in_range=tv,format=rgb24",
              "-f", "rawvideo", "-"])
red = np.frombuffer(raw, np.uint8).reshape(-1, 3).mean(0)
print("렌더 결과 레이어 위치 색:", red.round(1))
assert np.abs(red - (230, 40, 30)).max() < 10
# 이미지 제거 → 모든 레이어 제거
e._last_list = "img"
st.remove_image(img.id); wait(0.3)
print("이미지 제거 후 레이어:", len(st.project.sources[0].layers), len(st.project.segments[-1].layers), e.img_list.isVisible())
assert not st.project.sources[0].layers and not st.project.segments[-1].layers
# 저장·불러오기 왕복
from dtme.project import Project  # noqa: E402
st.project.sources[0].layers.append({"id": "x", "img": "y", "fin": 0, "fout": 5, "cx": .5, "cy": .5, "scale": 1})
d = st.project.to_dict()
p2 = Project.from_dict(d)
assert p2.sources[0].layers[0]["id"] == "x"
print("UI LAYERS OK")
