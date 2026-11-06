"""원본 구간 캐시(v0.16.7) 점검: 구간에서 잘라 온 미리보기 = 한 장씩 디코딩한 미리보기(픽셀 같음) · 근처 프레임 속도.
사용: python tests/test_range_cache.py <4K테스트.mp4>   (CI 포함)"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from PySide6.QtGui import QImage
from dtme import auto, ff, project as P

clip = sys.argv[1]
info = ff.probe(clip)
s = P.Source(path=clip, **{k: info[k] for k in ("fps_num", "fps_den", "frames", "width", "height", "has_audio")})
g = auto.builtin_grade("shallow", P.FACTORY_GRADE)
g["lut"] = ""                         # 합성 영상(LUT 없이도 같은 비교)


def one_by_one(fr):
    ff._frame_cache.clear()
    ff.range_clear()
    t = time.time()
    png = ff.render_preview(ff.cached_frame(s, fr), g)
    return png, time.time() - t


center = min(s.frames - 10, 60)
t = time.time()
assert ff.prefetch_range(s, center), "구간 채우기 실패"
t_fill = time.time() - t
frames = [center - 30, center - 1, center, center + 1, center + 25]
worst, t_old, t_new = 0, 0.0, 0.0
for fr in frames:
    ref, dt_old = one_by_one(fr)
    t_old += dt_old
    ff._frame_cache.clear()
    assert ff.prefetch_range(s, center) or ff.range_lookup(s.path, fr - 4, fr) is not None
    c = ff.cached_frame(s, fr)
    assert c.fmt == "raw", f"{fr}: 구간 캐시를 안 씀"
    t = time.time()
    got = ff.render_preview(c, g)
    t_new += time.time() - t
    a, b = QImage.fromData(ref, "PNG"), QImage.fromData(got, "PNG")
    assert a.size() == b.size()
    diff = 0
    for y in range(0, a.height(), 7):
        for x in range(0, a.width(), 7):
            pa, pb = a.pixel(x, y), b.pixel(x, y)
            diff = max(diff, abs(((pa >> 16) & 255) - ((pb >> 16) & 255)), abs(((pa >> 8) & 255) - ((pb >> 8) & 255)), abs((pa & 255) - (pb & 255)))
    worst = max(worst, diff)
    print(f"프레임 {fr}: 한 장씩 {dt_old:.2f}초 · 구간에서 {t_new / (frames.index(fr) + 1):.2f}초(평균) · 차이 {diff}")
print(f"구간 채우기({2 * ff.RANGE_HALF}장) {t_fill:.1f}초 · 한 장씩 평균 {t_old / len(frames):.2f}초 → 구간 {t_new / len(frames):.2f}초 · 최대 차이 {worst}")
assert worst == 0, "구간 캐시 화면이 다름"
# 구간 밖은 예전 방식
far = min(s.frames - 1, center + ff.RANGE_HALF + 20)
ff._frame_cache.clear()
if far > center + ff.RANGE_HALF:
    assert ff.cached_frame(s, far).fmt == "nut"
print("RANGE CACHE OK")
