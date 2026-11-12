"""v0.16.59: 사각형 테두리(두께·색) · 그림자(거리) — 그림(PNG) · 렌더 위치 · 창 · 모니터. 사용: python tests/test_rect_style.py <작업폴더>"""
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["DTME_NO_AUDIO"] = "1"
from dtme import ff, paths  # noqa: E402
from dtme.project import Project, Segment, Source, default_mix, new_rect  # noqa: E402

W, H = 1920, 1080


def png(path):
    w, h = (int(x) for x in subprocess.run([paths.ffprobe(), "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
                                           capture_output=True, text=True).stdout.strip().split(","))
    raw = subprocess.run([paths.ffmpeg(), "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 4).astype(int)


def main(work):
    d = Path(work)
    d.mkdir(parents=True, exist_ok=True)
    # 1) 그림
    r = new_rect(0.0, 2.0)
    r.update(cx=0.4, cy=0.4, w=0.25, h=0.2, color="#ff0000", opacity=1.0, radius=0, fade=0.0)
    a = png(ff.rect_png(r, 300, 100, 1.0))
    assert a.shape == (100, 300, 4) and tuple(a[50, 150]) == (255, 0, 0, 255) and tuple(a[0, 0]) == (255, 0, 0, 255), "예전과 같은 그림"
    assert ff.rect_margin(r, 1.0) == 0
    r.update(border=6, bcolor="#ffffff", shadow=20, radius=10)
    m = ff.rect_margin(r, 1.0)
    a = png(ff.rect_png(r, 300, 100, 1.0))
    assert a.shape == (100 + 2 * m, 300 + 2 * m, 4) and m >= 20
    assert tuple(a[m + 2, m + 150]) == (255, 255, 255, 255), "테두리(안쪽 6px)"
    assert tuple(a[m + 50, m + 150]) == (255, 0, 0, 255) and tuple(a[m + 8, m + 150]) == (255, 0, 0, 255), "안 = 사각형 색"
    assert a[m + 110, m + 150, :3].max() < 5 and 100 <= a[m + 110, m + 150, 3] <= 135, ("그림자(아래 10px) = 검정 50%", a[m + 110, m + 150])
    assert a[m + 50, m + 310, 3] > 90 and a[m + 50, m - 5, 3] == 0 and a[1, 1, 3] == 0, "그림자 = 오른쪽 아래만"
    # 2) 렌더: 사각형 자리 그대로(그림자 여백만큼 밀리지 않음) + 그림자가 오른쪽 아래
    clip = d / "gray.mp4"
    subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x808080:s=1920x1080:r=60000/1001:d=2",
                    "-f", "lavfi", "-i", "sine=d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)], check=True)
    info = ff.probe(str(clip))
    src = Source(path=str(clip), **{k: info[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
    p = Project()
    p.sources.append(src)
    p.grade.update(lut="", nr_chroma=0, nr_luma=0, sharpen=0, hue=0, sat=1.0, r_gain=1.0, b_gain=1.0, wnr=0, gy=0, water=0)
    p.output.encoder, p.output.gpu_decode = "x264", False
    out = d / "rect.mp4"
    ff.render_video(p, [Segment(src.id, 0, 100, 1.0)], str(out), orientation="horizontal",
                    extras={"titles": [r], "music": [], "mix": default_mix()})
    raw = ff.run([paths.ffmpeg(), "-v", "error", "-i", str(out), "-frames:v", "1", "-vf",
                  "select=eq(n\\,20),scale=in_color_matrix=bt709:in_range=tv,format=rgb24", "-f", "rawvideo", "-"])
    f = np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(int)
    x, y, w, h = ff.rect_box(r, W, H)
    assert f[y + h // 2, x + w // 2, 0] > 200 and f[y + h // 2, x + w // 2, 1] < 60, "가운데 = 빨강"
    assert f[y + 3, x + w // 2].min() > 215, ("위쪽 테두리 = 흰색", f[y + 3, x + w // 2])
    assert abs(f[y - 6, x + w // 2].mean() - 128) < 8 and abs(f[y + h // 2, x - 6].mean() - 128) < 8, "왼쪽·위 바깥 = 회색 그대로"
    assert f[y + h + 10, x + w // 2].mean() < 90 and f[y + h // 2, x + w + 10].mean() < 90, ("아래·오른쪽 = 그림자", f[y + h + 10, x + w // 2])
    # 3) 창 · 모니터
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication
    import main as M
    from dtme.ui_main import MainWindow
    from dtme.ui_titles import RectDialog
    app = QApplication(sys.argv)
    M.dark(app)
    win = MainWindow()
    win.resize(1536, 834)
    win.show()

    def wait(sec):
        t = time.time()
        while time.time() - t < sec:
            app.processEvents()
            time.sleep(0.01)
    r2 = new_rect(0.0, 2.0)
    dlg = RectDialog(r2, win)
    dlg.show()
    wait(0.1)
    dlg.vals["border"].setValue(8)
    dlg.vals["shadow"].setValue(24)
    dlg.bsw[1][1].click()
    assert (r2["border"], r2["shadow"], r2["bcolor"]) == (8, 24, "#000000"), r2
    dlg.grab().save(str(d / "rect_dialog.png"))
    dlg.reject()
    wait(0.05)
    assert "border" not in r2 and "shadow" not in r2
    mon = win.edit.player.mon
    img = QImage(1920, 1080, QImage.Format_RGB32)
    img.fill(QColor("#808080"))
    mon.set_image(img)
    mon.title_anim = {}
    mon.set_titles([(r, 1.0, None, None)], "")
    wait(0.3)
    g = mon.grab().toImage()
    rr = mon._title_rect(r, None)
    c = lambda px, py: QColor(g.pixel(int(px), int(py)))                       # noqa: E731
    mid, top = c(rr.center().x(), rr.center().y()), c(rr.center().x(), rr.top() + 1)
    sh, clr = c(rr.center().x(), rr.bottom() + 5), c(rr.center().x(), rr.top() - 5)
    assert mid.red() > 200 and mid.green() < 60 and min(top.red(), top.green(), top.blue()) > 200, (mid.name(), top.name())
    assert sh.red() < 115 and abs(clr.red() - 128) < 8, (sh.name(), clr.name())
    g.save(str(d / "rect_monitor.png"))
    print("OK test_rect_style")
    os._exit(0)


if __name__ == "__main__":
    main(sys.argv[1])
