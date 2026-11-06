"""RAM 캐시: 구간 디코딩 결과 == 한 장씩 디코딩 결과, 속도 비교. 인자: 영상 작업폴더"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import numpy as np
from fractions import Fraction
from dtme import ff, framecache, paths

src, work = sys.argv[1], sys.argv[2]
os.makedirs(work, exist_ok=True)
prox = os.path.join(work, "proxy.mp4")
info = ff.probe(src)
fps = Fraction(info["fps_num"], info["fps_den"])
ff.run([paths.ffmpeg(), "-v", "error", "-y", "-stream_loop", "3", "-i", src, "-t", "6", "-vf", "scale=960:-2", "-c:v", "libx264",
        "-g", "1", "-crf", "18", "-pix_fmt", "yuv420p", "-an", prox])
n = ff.probe(prox)["frames"]
fc = framecache.FrameCache()
fc.cap = 1 << 30
t = time.time()
fc.request(prox, fps, n, 130)
while not fc.has(prox, 130):
    time.sleep(0.01)
t_first = time.time() - t
while fc.stats()[0] < (n + framecache.CHUNK - 1) // framecache.CHUNK:
    time.sleep(0.02)
t_all = time.time() - t
# 정확성: 몇 프레임을 한 장씩 디코딩과 비교
for f in (0, 1, 119, 120, 130, n - 1):
    a, (w, h) = fc.get(prox, f)
    bmp = ff.grab_proxy_frame(prox, fps, f)
    b = np.frombuffer(bmp[-w * h * 3:], np.uint8).reshape(h, w, 3)[::-1, :, ::-1]
    d = np.abs(a.astype(int) - b).mean()
    assert d < 0.5, (f, d)
t = time.time()
for f in range(0, n, 7):
    img = framecache.qimage(fc.get(prox, f))
    assert img.width() == 960
t_hit = (time.time() - t) / len(range(0, n, 7))
t = time.time()
for f in range(0, 40, 4):
    ff.grab_proxy_frame(prox, fps, f)
t_old = (time.time() - t) / 10
print(f"frames={n} 첫 구간 {t_first:.2f}s 전체 {t_all:.2f}s 디코딩 {fc.decode_count}번 | 캐시 {t_hit*1000:.2f}ms/장 vs 기존 {t_old*1000:.0f}ms/장")
fc.cap = framecache.CHUNK * 960 * 540 * 3 + 1      # 상한: 한 구간만 → 창 안이면 유지, 창 밖 정리 확인
fc.focus = (prox, fps, n, 0); fc._evict()
print("FRAMECACHE OK")
