"""v0.16.94 [박자우선]: 컷 경계(전환 가운데) = 그 자리 곡 마디 첫 박 · 첫 컷 시작 = 마디 첫 박 · LOG 15초 이상 마디 배수 · 원본 끝 = 컷인 앞으로.
자동 편집 창: '음악 자동' 아래 들여쓴 '박자우선' — 올린 곡 있으면 기본 켬, 음악 자동 끄면 막힘.
사용: python tests/test_v1694.py"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["DTME_NO_AUDIO"] = "1"
from dtme import autoedit as A  # noqa: E402
from dtme.project import Project, Segment, Source, cut_spans, new_music  # noqa: E402

FPS = 30.0
BAR = 2.0                                     # 120 BPM 4/4
inf = {"conf": 0.9, "dur": 300.0, "bpm": 120.0, "meter": 4,
       "bars": [0.3 + BAR * i for i in range(150)], "beats": [0.3 + 0.5 * i for i in range(600)]}


def proj(lens, src_sec=(40, 40, 40, 40), lead=6.0, trans=("dissolve", 0.5)):
    p = Project()
    for i, sec in enumerate(src_sec):
        s = Source(path=f"/x/c{i}.mp4", fps_num=30, fps_den=1, frames=int(sec * FPS), width=1920, height=1080)
        p.sources.append(s)
    p.lead = lead
    for i, ln in enumerate(lens):
        s = p.sources[i]
        fin = int(5 * FPS)
        g = Segment(s.id, fin, fin + int(round(ln * FPS)), 1.0)
        if i:
            g.trans = {"type": trans[0], "dur": trans[1]}
        else:
            g.trans = {"type": "fadeblack", "dur": 1.0}
        p.segments.append(g)
    m = new_music("/x/song.mp3", 0.0, 300.0)
    m["off"], m["len"] = 0.3, 200.0              # 곡 시작 = 마디 첫 박(타임라인 0)
    p.music = [m]
    return p


def centers(p):
    sp = cut_spans(p)
    return [t + float((p.segments[i].trans or {}).get("dur", 0)) / 2 for i, (_c, t, _l) in enumerate(sp) if i]


def on_bar(p, T, tol=1.5 / FPS):
    from dtme.music import beats_on_timeline
    bars = beats_on_timeline(p.music[0], inf, bars=True)
    return min(abs(b - T) for b in bars) <= tol


# 1) 아무 길이(7.3 · 9.1 · 6.2 · 8) → 모든 경계가 마디 첫 박 · 첫 컷 시작(6초)도
p = proj([7.3, 9.1, 6.2, 8.0])
r = A.beat_lock(p, {"/x/song.mp3": inf})
print("결과:", r, "경계:", [round(x, 3) for x in centers(p)])
assert r["bar"] == 3 and r["miss"] == 0 and r["weak"] == 0, r
assert all(on_bar(p, T) for T in centers(p)), centers(p)
assert on_bar(p, cut_spans(p)[0][1]), "첫 컷 시작 = 마디 첫 박"
for g in p.segments[:-1]:
    assert (g.fout - g.fin) / FPS >= A.CUT_MIN - 1e-6

# 1-1) 시작 화면 끝(5.3초)이 마디 첫 박이 아님 → 곡 시작 위치를 옮겨 맞춤
p = proj([7.3, 9.1, 6.2, 8.0], lead=5.3)
A.beat_lock(p, {"/x/song.mp3": inf})
assert on_bar(p, cut_spans(p)[0][1]) and all(on_bar(p, T) for T in centers(p)) and abs(p.music[0]["off"] - 0.3) <= BAR / 2 + 1e-6

# 2) 원본 끝에 막힘: 첫 소스가 컷 끝 = 원본 끝 → 늘려야 하면 컷인을 앞으로
p = proj([7.6, 9.0, 6.0], src_sec=(12.6, 40, 40))
g0 = p.segments[0]
s0 = p.sources[0]
g0.fin, g0.fout = s0.frames - int(7.6 * FPS), s0.frames
A.beat_lock(p, {"/x/song.mp3": inf})
assert all(on_bar(p, T) for T in centers(p)), centers(p)
assert p.segments[0].fout <= s0.frames and p.segments[0].fin >= 0

# 3) LOG 다이빙 컷 = 15초 아래로 안 줄임(15초 넘는 마디 배수)
p = proj([15.2, 9.0, 6.0])
p.dive_on, p.dives = True, [{"id": "d"}]
orig = A.dive_src
A.dive_src = lambda pr, s: s.id == pr.sources[0].id
try:
    A.beat_lock(p, {"/x/song.mp3": inf})
finally:
    A.dive_src = orig
ln0 = (p.segments[0].fout - p.segments[0].fin) / FPS
print("LOG 컷:", ln0)
assert ln0 >= A.DIVE_MIN - 1e-6 and all(on_bar(p, T) for T in centers(p))

# 4) 리듬 흐린 곡 = 안 맞춤
p = proj([7.3, 9.1, 6.2])
before = [(g.fin, g.fout) for g in p.segments]
r = A.beat_lock(p, {"/x/song.mp3": {**inf, "conf": 0.1}})
assert r["weak"] == 1 and r["bar"] == 0 and [(g.fin, g.fout) for g in p.segments] == before, r

# 5) 자동 편집 창: 박자우선 = 음악 자동 아래 · 올린 곡 있으면 기본 켬 · 음악 자동 끄면 막힘
from PySide6.QtWidgets import QApplication  # noqa: E402
app = QApplication(sys.argv)
from dtme.state import AppState  # noqa: E402
from dtme.ui_autoedit import AutoEditDialog  # noqa: E402
st = AppState()
st.project.sources.append(Source(path="/x/a.mp4", fps_num=30, fps_den=1, frames=900, width=1920, height=1080))
d = AutoEditDialog(st, {st.project.sources[0].id})
assert d.beat_on.text() == "박자우선"
assert not d.beat_on.isChecked(), "올린 곡 없음 = 기본 끔"
st.project.audios.append({"path": "/x/song.mp3", "dur": 300.0})
d = AutoEditDialog(st, {st.project.sources[0].id})
assert d.beat_on.isChecked() and d.beat_on.isEnabled() and d.settings()["beat"]
d.music_on.setChecked(False)
assert not d.beat_on.isEnabled() and not d.settings()["beat"]
d.music_on.setChecked(True)
assert d.beat_on.isEnabled()
print("OK test_v1694", flush=True)
os._exit(0)
