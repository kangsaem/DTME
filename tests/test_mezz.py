"""v0.16.91 보정용 중간 파일(SSD 조각): 만들기 · 미리보기 입력이 원본과 같은 화면 · 상한 넘으면 오래된 것부터 지움.
사용: python tests/test_mezz.py <작업폴더>"""
import os, subprocess, sys, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import numpy as np  # noqa: E402
from dtme import ff, paths  # noqa: E402
from dtme.project import NEUTRAL, set_setting  # noqa: E402
W = os.path.abspath(sys.argv[1]); os.makedirs(W, exist_ok=True)
v = os.path.join(W, "src.mp4")
subprocess.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=25", "-c:v", "libx265", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p10le", "-x265-params", "log-level=error:keyint=300", v], check=True)
s = ff.probe_source(v) if hasattr(ff, "probe_source") else None
from dtme.project import Source  # noqa: E402
info = ff.probe(v)
s = Source(v, info["fps_num"], info["fps_den"], info["frames"], info["width"], info["height"])
for f in ff.mezz_dir().glob("*.mkv"):
    f.unlink()
fr = 400                                     # 13.3초 = 조각 1
lead = ff.PREVIEW_LEAD
assert not ff.mezz_has(s, fr - lead, fr)
t = time.time(); a = ff.cached_frame(s, fr); t_src = time.time() - t
ff._frame_cache.clear()
t = time.time(); ok = ff.mezz_make(s, fr // ff._mezz_n(s)); t_make = time.time() - t
assert ok and ff.mezz_has(s, fr - lead, fr) and ff.frame_ready(s, fr)
t = time.time(); b = ff.cached_frame(s, fr); t_mz = time.time() - t
a.key = b.key = ""               # 결과 기억 안 쓰게(같은 키 = 같은 그림 돌려줌)
pa, pb = ff.render_preview(a, dict(NEUTRAL)), ff.render_preview(b, dict(NEUTRAL))
from PySide6.QtGui import QImage  # noqa: E402
ia, ib = QImage.fromData(pa), QImage.fromData(pb)
def arr(im):
    im = im.convertToFormat(QImage.Format_RGB888)
    return np.frombuffer(im.constBits(), np.uint8, im.bytesPerLine() * im.height()).reshape(im.height(), im.bytesPerLine())[:, :im.width() * 3].astype(float)
d = np.abs(arr(ia) - arr(ib)).mean()
sz = ff.mezz_path(s, fr // ff._mezz_n(s)).stat().st_size / 1048576
print(f"원본 {t_src:.2f}s · 중간 파일 만들기 {t_make:.2f}s · 중간 파일에서 {t_mz:.2f}s · 화면 차 {d:.2f} · 조각 {sz:.1f}MB · 크기 {b.size}")
assert d < 2.0 and b.size[0] == ff.PREVIEW_LONG
# 상한: 0.000001GB → 다 지움
set_setting("mezz_gb", 1e-9); ff.mezz_trim(); set_setting("mezz_gb", 10)
assert not list(ff.mezz_dir().glob("*.mkv"))
print("OK test_mezz", flush=True)
