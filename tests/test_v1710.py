"""v0.17.1 엔진: 편집 길이(최소 길이를 길이 맞추기 안에서 · 12초/마디 단위 · 마지막 컷이 정한 시각에 끝남) · 긴 소스 컷 추가 ·
같은 클립 컷 안 겹침 · 곡 넘어가는 자리(장면 바뀜 · 15초 규칙 · 마지막 곡 = 끝이 영상 끝) · 끝 화면 글자 · 화면 읽기 순서(프록시 → LRF → 원본).
사용: python tests/test_v1710.py [작업 폴더]"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["DTME_NO_AUDIO"] = "1"
import numpy as np  # noqa: E402
from dtme import autoedit as A, ff, music as M, paths  # noqa: E402
from dtme.project import Project, Segment, Source, cut_spans, new_music  # noqa: E402

d = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="dtme_v1710_")
os.makedirs(d, exist_ok=True)
FPS = 30.0

# ---------------------------------------------------------------- 1) 최소 단위 · 나누기
assert A.DIVE_MIN == 12.0 and M.TAIL_FILL == 15.0
assert abs(A.unit_len(2.6, True) - 13.0) < 1e-6 and abs(A.unit_len(3.5, True) - 10.5) < 1e-6        # 12초에 가장 가까운 마디 수
assert abs(A.unit_len(2.2, True) - 11.0) < 1e-6 and A.unit_len(1.9, True) >= 10.0                   # 10초 아래로는 안 감
assert abs(A.unit_len(2.6, False) - 5.2) < 1e-6 and abs(A.unit_len(3.5, False) - 3.5) < 1e-6 and A.unit_len(0, True) == 12.0
# 보홀 비슷(사용자 로그 11/17: 14클립 · 3분 · LOG → 본문 213초가 나옴): 최소 12초로 올린 만큼 다른 클립이 줄어 합 = 목표
durs = [213, 40, 35, 60, 25, 30, 45, 50, 28, 33, 70, 22, 38, 41]
S = 180 + 13 * 0.5
c = A.allot(durs, S, cut_min=[12.0] * 14)
assert abs(sum(sum(x) for x in c) - S) < 1e-6 and all(v >= 12.0 - 1e-6 for x in c for v in x), c
assert sum(c[0]) > sum(c[1])                                                    # 긴 소스에 더
c2 = A.allot(durs, S, cut_min=[12.0] * 14, extra=[1] + [0] * 13)               # 꼭 더 넣을 컷 = 최소 단위씩, 합은 그대로
assert len(c2[0]) == 2 and abs(sum(sum(x) for x in c2) - S) < 1e-6 and all(v >= 12.0 - 1e-6 for v in c2[0]), c2
print("나누기:", [round(sum(x), 1) for x in c])


def proj(n, sec, scores=None):
    p = Project()
    picks = []
    for i in range(n):
        s = Source(f"/v/DJI_202510200{9 + i // 6}{(i % 6) * 10:02d}00_00{i:02d}_D.MP4", 30, 1, int(sec[i] * FPS))
        s.width, s.height = 3840, 2160
        p.sources.append(s)
        sc = scores[i] if scores else np.ones(int(sec[i] / A.STEP))
        picks.append({"src": s, "scene": "", "score": sc, "surface": None})
    return p, picks


def body_len(p):
    sp = cut_spans(p)
    return max(t + ln for _c, t, ln in sp) - float(p.lead)


# ---------------------------------------------------------------- 2) build: LOG(전부 다이빙) 14클립 3분 → 본문 ≈ 180(넘지 않음)
orig = A.dive_src
A.dive_src = lambda pr, s: True
try:
    p, picks = proj(14, durs)
    plan = A.build(p, picks, 0, seed=1, titles=False, total=180.0)
    p.segments = plan["segs"]
    b0 = body_len(p)
    lens = [(g.fout - g.fin) / FPS for g in p.segments]
    print("LOG 14클립 3분: 본문", round(b0, 1), "· 컷", len(lens), "· 최소", round(min(lens), 1))
    assert abs(b0 - 180.0) < 2.5 and min(lens) >= 12.0 - 0.05, (b0, lens)
    assert abs(A.end_at(p, 180.0) - 180.0) < 1.0 / FPS + 1e-6                   # 마지막 컷만 고쳐 정한 시각에
finally:
    A.dive_src = orig

# ---------------------------------------------------------------- 3) 긴 소스: 평균의 2배·3배 = 컷 더(점수가 낮으면 뺌) · 같은 클립 컷 안 겹침
sec = [300, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30]
hi = np.ones(600); hi[100:130] = 6; hi[400:430] = 6; hi[250:280] = 5              # 좋은 곳 3군데
flat = np.ones(600); flat[100:110] = 6                                           # 좋은 곳 1군데(5초)뿐
others = [np.concatenate([np.ones(30), np.full(20, 6.0), np.ones(10)]) for _ in range(11)]
p, picks = proj(12, sec, [hi] + others)
plan = A.build(p, picks, 0, seed=2, titles=False, total=90.0)
n0 = sum(1 for g in plan["segs"] if g.src == p.sources[0].id)
print("긴 소스(좋은 곳 3군데):", n0, "컷 ·", plan["extra"])
assert n0 == 3 and plan["extra"] and plan["extra"][0][4] == 2, plan["extra"]     # 3배 이상 = 둘 더(클립당 3컷)
p.segments = plan["segs"]
assert abs(body_len(p) - 90.0) < 2.5
segs0 = sorted((g.fin, g.fout) for g in plan["segs"] if g.src == p.sources[0].id)
assert all(a[1] <= b[0] for a, b in zip(segs0, segs0[1:])), segs0                # 시간순 · 안 겹침
p, picks = proj(12, sec, [flat] + others)
plan = A.build(p, picks, 0, seed=2, titles=False, total=90.0)
n1 = sum(1 for g in plan["segs"] if g.src == p.sources[0].id)
print("긴 소스(좋은 곳 1군데):", n1, "컷 ·", plan["extra"])
assert n1 == 1 and plan["extra"][0][4] == 0                                      # 더 잡은 컷 점수 < 중간값 = 뺌


# ---------------------------------------------------------------- 4) 박자우선: 같은 소스 두 컷이 원본에서 안 겹침 · 최소 = 마디 단위
def info(dur, bpm=120.0, lead=0.0):
    bl = 60.0 / bpm
    beats = [round(lead + i * bl, 4) for i in range(int((dur - lead) / bl))]
    return {"dur": dur, "bpm": bpm, "meter": 4, "conf": 0.9, "lead": lead, "beats": beats, "bars": beats[::4], "loud": -18.0}


p = Project()
s = Source("/v/c0.mp4", 30, 1, int(120 * FPS)); s.width, s.height = 1920, 1080
s2 = Source("/v/c1.mp4", 30, 1, int(60 * FPS)); s2.width, s2.height = 1920, 1080
p.sources += [s, s2]
p.lead = 5.0
g1 = Segment(s.id, 2248, 2248 + 426); g1.trans = {"type": "fadeblack", "dur": 1.0}
g2 = Segment(s.id, 2674, 2674 + 400); g2.trans = {"type": "dissolve", "dur": 0.5}      # 원본에서 바로 붙은 두 컷(사용자 로그의 0164)
g3 = Segment(s2.id, 300, 600); g3.trans = {"type": "dissolve", "dur": 0.5}
p.segments = [g1, g2, g3]
inf = info(200.0, bpm=92.0)
m = new_music("/m/a.mp3", 0.0, 200.0); m["off"], m["len"] = 0.0, 200.0
p.music = [m]
r = A.beat_lock(p, {"/m/a.mp3": inf})
print("박자우선:", r, "·", [(g.fin, g.fout) for g in p.segments])
assert g1.fout <= g2.fin, (g1.fin, g1.fout, g2.fin, g2.fout)                     # 예전 = 늘린 아웃이 다음 컷 인을 넘어 0.6초 겹침
assert r["bar"] == 2

# ---------------------------------------------------------------- 5) 곡 넘어가는 자리
auds = [{"path": "a"}, {"path": "b"}]
infos = {"a": info(168.0, lead=1.0), "b": info(200.0)}
# 한 곡으로 거의 끝까지(남는 구간 12초 ≤ 15) = 그 곡만
h = M.handover(M.plan_whole(auds, infos, 180.0, 2.0), infos, 180.0, 2.0, [(90.0, 0)])
assert [x["path"] for x in h] == ["a"] and M.fill_tail(h, auds, infos, 180.0, 2.0) == h
# 모자람(250초): 범위 [영상 끝 − 뒤 곡 길이, 앞 곡 끝] 안의 장면 바뀜 — 여행 > 날짜 > 물 밖 > 가운데에 가까운 경계
bd = [(60.0, 3), (100.0, 1), (120.0, 3), (150.0, 2)]
h = M.handover(M.plan_whole(auds, infos, 250.0, 2.0), infos, 250.0, 2.0, bd)
assert len(h) == 2 and abs(h[1]["t0"] - 99.0) < 1e-6 and abs(h[0]["len"] - 101.0) < 1e-6, h       # 날짜 바뀜(100초)에서 2초 디졸브
assert abs(M.music_end(h) - 250.0) < 2.01 and M.music_end(h) >= 250.0 - 1e-6                      # 마지막 곡 끝 = 영상 끝(마디 첫 박에서 시작)
assert any(abs(h[1]["off"] + 1.0 - b) < 1e-6 for b in infos["b"]["bars"]) and h[1]["off"] > 10     # 넘어가는 자리 = 뒤 곡 마디 첫 박 · 도입부 건너뜀
h = M.handover(M.plan_whole(auds, infos, 250.0, 2.0), infos, 250.0, 2.0, bd + [(140.0, 0)])
assert abs(h[1]["t0"] - 139.0) < 1e-6                                                              # 여행 바뀜이 먼저
h = M.handover(M.plan_whole(auds, infos, 250.0, 2.0), infos, 250.0, 2.0, [(60.0, 3), (120.0, 3), (140.0, 3)])
assert abs(h[1]["t0"] - 119.0) < 1e-6                                                              # 장면 바뀜 없음 = 범위(51~166) 가운데에 가까운 경계
# 곡이 딱 맞거나 모자람 = 앞 곡 끝 그대로 · 다 쓰고 15초 넘게 남으면 다시
h = M.handover(M.plan_whole(auds, infos, 365.0, 2.0), infos, 365.0, 2.0, [(100.0, 0)])
assert abs(h[1]["t0"] - 165.0) < 1e-6 and abs(h[0]["len"] - 167.0) < 1e-6
f = M.fill_tail(M.handover(M.plan_whole(auds, infos, 400.0, 2.0), infos, 400.0, 2.0, []), auds, infos, 400.0, 2.0)
assert len(f) == 3 and f[2].get("reuse")
print("곡 넘어가기: OK")
# 경계 등급: 여행(7일+) 0 · 날짜 1 · 물 밖 2 · 그 밖 3
p = Project()
for nm in ("DJI_20251020094000_0001_D.MP4", "DJI_20251020101000_0002_D.MP4", "DJI_20251021090000_0003_D.MP4",
           "DJI_20260320090000_0004_D.MP4", "DJI_20260320100000_0005_D.MP4"):
    s = Source("/v/" + nm, 30, 1, 900); s.width, s.height = 1920, 1080
    p.sources.append(s)
    g = Segment(s.id, 0, 300)
    if p.segments:
        g.trans = {"type": "dissolve", "dur": 0.5}
    p.segments.append(g)
bd = A.cut_bounds(p, {p.segments[4].id: "surface"})
assert [r_ for _t, r_ in bd] == [3, 1, 0, 2], bd
assert abs(bd[0][0] - (10.0 - 0.5 + 0.25)) < 1e-6

# ---------------------------------------------------------------- 6) 끝 화면 글자 · 지명 없음 = DTME
assert A.NO_PLACE == "DTME" and not hasattr(A, "END_TAG")
dv = [{"id": "a", "start": 0.0, "pts": [[0, 0], [1200, 22.0], [2400, 0]], "max": 22.0}]
assert [x[1] for x in A.end_lines(True, dv, "보홀주, 필리핀", "2025.10.20")] == [80, 64, 64]
assert A.end_lines(False, [], "DTME", "2025.10.20") == [("DTME", 64, True), ("2025.10.20", 64, True)]
assert A.end_lines(False, [], "", "2025.10.20") == [("2025.10.20", 80, True)]          # 줄이 하나뿐 = 한 단계 크게
ec = A.end_card(100.0, A.end_lines(False, [], "DTME", "2025.10.20"))
assert [x.get("text") for x in ec if x["kind"] == "text"] == ["DTME", "2025.10.20"]
sc = [x for x in A.start_card("DTME", "2025.10.20") if x["kind"] == "text"]
assert [(x["text"], x["size"]) for x in sc] == [("DTME", 160), ("2025.10.20", 80)]

# ---------------------------------------------------------------- 7) 화면 읽기 순서: 프록시 → LRF → 원본(LRF 가 있으면 원본을 안 읽음)
ffm = paths.ffmpeg()
big = os.path.join(d, "DJI_20251020094000_0001_D.MP4")
subprocess.run([ffm, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=6", "-c:v", "libx264", "-preset", "ultrafast",
                "-g", "30", "-pix_fmt", "yuv420p", big], check=True)
lrf = os.path.join(d, "DJI_20251020094000_0001_D.LRF")
subprocess.run([ffm, "-v", "error", "-y", "-i", big, "-vf", "scale=640:360", "-c:v", "libx264", "-preset", "ultrafast", "-g", "30",
                "-pix_fmt", "yuv420p", "-f", "mp4", lrf], check=True)
src = ff.probe(big) if hasattr(ff, "probe") else None
if src is None or not getattr(src, "frames", 0):
    src = Source(big, 30, 1, 180); src.width, src.height = 1280, 720
read = []
_popen = ff._popen


def spy(cmd, **kw):
    if "-i" in cmd:
        read.append(os.path.basename(cmd[cmd.index("-i") + 1]))
    return _popen(cmd, **kw)


assert ff.preview_info(src, "") is not None, "시험용 LRF 판정 통과"
ff._popen = spy
try:
    fr, how = A.scan_src(src, None, "")
finally:
    ff._popen = _popen
print("화면 읽기:", how, read, fr.shape)
assert how == "LRF" and read == [os.path.basename(lrf)] and fr.shape[1:] == (54, 96, 3) and len(fr) >= 10
os.remove(lrf)
ff._pv_cache.clear()
fr2, how2 = A.scan_src(src, None, "")
assert how2 == "원본" and abs(len(fr2) - len(fr)) <= 1
src.proxy = big                                              # 프록시가 있으면 프록시 먼저
assert A.scan_src(src, None, "")[1] == "프록시"
assert float(np.abs(fr[:len(fr2)].mean(axis=(1, 2, 3)) - fr2[:len(fr)].mean(axis=(1, 2, 3))).max()) < 0.05      # 같은 화면
print("OK test_v1710", flush=True)
