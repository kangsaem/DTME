"""v0.16.96: 시작 화면(지명 160 가운데 · 기간 80 높이 80%) · 기간 = 처음 ~ 끝 하나 · 끝 화면(요약/지명/기간 3줄,
LOG 없음 = 지명/기간, 맨 아래 하늘색 'See You Underwater', 직접 쓴 문구 = 그것만) · 끝 소리(흰 화면 동안 내림) ·
선 아래 색 = 3.0초부터 0.4초 디졸브 · 분홍 점 1초 · 음악 = 한 곡 처음~끝 한 번, 30초 규칙, 컷 경계 = 마디 첫 박.
사용: python tests/test_v1696.py"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
app = QApplication(sys.argv)
from dtme import autoedit as A, dive_draw as D, ff, music as M  # noqa: E402
from dtme.project import Project, Segment, Source, cut_spans, new_music  # noqa: E402


def T(y, mo, d, h=9):
    return datetime(y, mo, d, h, tzinfo=timezone.utc).timestamp()


# ---------------------------------------------------------------- 1) 시작 화면 · 기간
tr = A.trips_of([(T(2025, 10, 20), T(2025, 10, 21)), (T(2026, 3, 20), T(2026, 3, 23))])
assert len(tr) == 2
assert A.trips_period(tr) == "2025.10.20 ~ 2026.03.23", A.trips_period(tr)          # 처음 ~ 끝 하나로
assert A.trips_period(tr[:1]) == "2025.10.20 ~ 10.21" and A.trips_period([]) == ""
sc = A.start_card("보홀주, 필리핀", "2025.10.20 ~ 10.21")
tx = [x for x in sc if x["kind"] == "text"]
assert [(x["size"], x["cy"]) for x in tx] == [(160, 0.5), (80, 0.8)], [(x["size"], x["cy"]) for x in tx]
assert all(x["t0"] == 0.0 and x["ain"] == "cut" and x["aout"] == "fade" for x in tx)
assert [x["cy"] for x in A.start_card("", "2025.10.20") if x["kind"] == "text"] == [0.8]      # 지명 없음 = 기간만(자리 그대로)
sv = [x for x in A.start_card("미야코지마시 · 이시가키시, 오키나와현, 일본", "2025.10.20 ~ 2026.03.23", 5.0, (1080, 1920)) if x["kind"] == "text"]
assert len(sv) == 4 and sv[0]["size"] < 160 and abs(sv[1]["cy"] - 0.5) < 1e-6 and sv[-1]["cy"] == 0.8   # v0.16.97 세로 = 3줄(가운데 묶음) · 기간 자리 같음
for x in sv:
    assert A._metrics(x)[0] <= 0.85 * 1080 + 2
print("시작 화면:", [(x["text"], x["size"], x["cy"]) for x in tx], "· 세로 지명", sv[0]["size"])

# ---------------------------------------------------------------- 2) 끝 화면
dv = [{"id": "a", "start": T(2025, 10, 20), "pts": [[0, 0], [1200, 22.0], [2400, 0]], "max": 22.0}]
ls = A.end_lines(True, dv, "보홀주, 필리핀", "2025.10.20")
assert [(x[0][:6], x[1]) for x in ls] == [("1 DIVE", 52), ("보홀주, 필", 36), ("2025.1", 36)], ls     # 3줄
assert [x[0] for x in A.end_lines(False, [], "보홀주, 필리핀", "2025.10.20")] == ["보홀주, 필리핀", "2025.10.20"]
assert [x[0] for x in A.end_lines(False, [], "", "2025.10.20")] == ["2025.10.20"] and A.end_lines(False, [], "", "") == []
assert [x[0] for x in A.end_lines(True, dv, "p", "d", "Bye / 2025")] == ["Bye", "2025"]         # 직접 쓴 문구 = 그것만
ec = A.end_card(100.0, ls, tag=True)
tg = [x for x in ec if x.get("tag")]
assert len(tg) == 1 and ec[-1] is tg[0] and tg[0]["text"] == "See You Underwater" and tg[0]["color"] == "#4FB3E8"
assert tg[0]["size"] == 84 and tg[0]["cy"] == 0.88                                   # v0.16.97 3배 and tg[0]["ain"] == "fade" and abs(tg[0]["t0"] - 102.0) < 1e-6
assert not any("DTME" == x.get("text") for x in ec)
mid = [x for x in ec if x["kind"] == "text" and not x.get("tag")]
assert len(mid) == 3 and all(x["color"] == A.CARD_COLOR for x in mid) and mid[0]["cy"] < mid[1]["cy"] < mid[2]["cy"] < 0.7
assert not [x for x in A.end_card(100.0, A.end_lines(True, dv, "p", "d", "Bye")) if x.get("tag")]   # 직접 쓴 문구 = 아래 줄 없음
e0 = A.end_card(100.0, [], tag=True)
assert [x["kind"] for x in e0] == ["rect", "text"] and e0[1].get("tag")                          # 가운데 비움 + 아래 줄
assert all(x.get("card") == "end" for x in ec)
print("끝 화면:", [(x.get("text"), x.get("size"), x.get("cy")) for x in ec if x["kind"] == "text"])

# ---------------------------------------------------------------- 3) 끝 소리: 흰 화면 시작부터 1초 내림
assert ff.end_white_at(ec) == (99.0, 1.0) and ff.end_white_at(sc) is None and ff.end_white_at([]) is None
fp, cmd = ["[0:a]anull[am]", "[0:v]null[vm]"], []
ff.post_graph(fp, cmd, Project(), {"titles": [x for x in ec if x["kind"] == "rect"], "mix": {}, "music": []}, 108.0, "horizontal", True, 1)
g = ";".join(fp)
assert "[aew]afade=t=out:st=99.0000:d=1.0000[ao]" in g and g.count("[ao]") == 1, g[-300:]
fp2 = ["[0:a]anull[am]", "[0:v]null[vm]"]
ff.post_graph(fp2, [], Project(), {"titles": [], "mix": {}, "music": []}, 108.0, "horizontal", True, 1)
assert "afade=t=out:st=99" not in ";".join(fp2) and ";".join(fp2).count("[ao]") == 1
print("끝 소리:", g[g.rfind("[aew]afade"):])
# 실제 ffmpeg: 사인 소리 18초 + 끝 화면(영상 끝 10초) → 9초 전 = 그대로 · 9~10초 = 내려감 · 10초 뒤 = 무음
import re  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from dtme import paths  # noqa: E402
ec2 = A.end_card(10.0, A.end_lines(False, [], "Bohol", "2025.10.20"), tag=True)
outf = os.path.join(tempfile.mkdtemp(prefix="dtme_v1696_"), "endfade.mp4")
c2 = [paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-t", "18", "-i", "color=c=blue:s=320x180:r=30",
      "-f", "lavfi", "-t", "18", "-i", "sine=f=440:r=48000"]
fp3 = ["[0:v]format=yuv420p[vm]", "[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo[am]"]
ff.post_graph(fp3, c2, Project(), {"titles": ec2, "mix": {"orig": 1.0}, "music": []}, 18.0, "horizontal", True, 2)
c2 += [*ff.filter_complex_args(";".join(fp3)), "-map", "[vo]", "-map", "[ao]", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", outf]
lut = paths.cache_dir() / "lut"
lut.mkdir(parents=True, exist_ok=True)
rr = subprocess.run(c2, capture_output=True, cwd=str(lut))
assert rr.returncode == 0 and os.path.getsize(outf) > 1000, rr.stderr.decode("utf-8", "replace")[-600:]


def vol(ss, t):
    e = subprocess.run([paths.ffmpeg(), "-ss", str(ss), "-t", str(t), "-i", outf, "-af", "volumedetect", "-vn", "-f", "null", "-"],
                       capture_output=True).stderr.decode("utf-8", "replace")
    return float(re.search(r"mean_volume: ([-\d.]+)", e).group(1))


v0, v1, v2 = vol(5, 3), vol(9.3, 0.4), vol(10.3, 7)
print("끝 소리(실제 렌더, dB): 앞", v0, "· 내리는 중", v1, "· 끝 화면", v2)
assert v0 > -40 and v0 - 15 < v1 < v0 - 2 and v2 < -70, (v0, v1, v2)

# ---------------------------------------------------------------- 4) 선 아래 색 = 디졸브(긁기 없음) · 분홍 1초
fi = [D.fill_in(D.anim(tc, 20.0)[1]) for tc in (0.0, 2.0, 2.99, 3.0, 3.2, 3.4, 5.0)]
assert fi[:4] == [0.0, 0.0, 0.0, 0.0] or max(fi[:4]) < 1e-3, fi
assert abs(fi[4] - 0.5) < 0.02 and fi[5] > 0.999 and fi[6] > 0.999, fi
dive = {"id": "d", "start": 0.0, "pts": [[0, 0], [300, 20.0], [600, 5.0], [900, 0]], "max": 20.0}
a_half = D.fill_alpha(480, 270, dive, 600.0, D.anim(3.2, 20.0)[1])[0]
a_full = D.fill_alpha(480, 270, dive, 600.0, 1.0)[0]
on = a_full > 0.02
assert on.sum() > 500
ratio = a_half[on] / a_full[on]
assert abs(float(ratio.mean()) - 0.5) < 0.03 and float(ratio.std()) < 0.01, (ratio.mean(), ratio.std())     # 전체가 같은 비율 = 디졸브
assert float(D.fill_alpha(480, 270, dive, 600.0, D.anim(2.9, 20.0)[1])[0].max()) < 1e-3
nfr = int(D.PULSE_SEC * D.PULSE_FPS)
assert sum(D.is_flash(j / nfr) for j in range(nfr)) == D.PULSE_FPS == 12 and D.is_flash(0.0) and not D.is_flash(1.0 / D.PULSE_SEC + 1e-3)
print("색 디졸브:", [round(x, 2) for x in fi], "· 분홍", sum(D.is_flash(j / nfr) for j in range(nfr)), "장/주기")


# ---------------------------------------------------------------- 5) 음악: 한 곡 처음~끝 한 번 · 30초 규칙
def info(dur, bpm=120.0, lead=0.0, mood=0.5):
    bl = 60.0 / bpm
    beats = [round(lead + i * bl, 4) for i in range(int((dur - lead) / bl))]
    return {"dur": dur, "bpm": bpm, "meter": 4, "conf": 0.9, "lead": lead, "beats": beats, "bars": beats[::4],
            "energy": [-20.0] * int(dur * 2), "mood": mood, "loud": -18.0}


auds = [{"path": "/m/a.mp3"}, {"path": "/m/b.mp3"}]
infos = {"/m/a.mp3": info(60.0, lead=1.0), "/m/b.mp3": info(50.0)}
it = M.plan_whole(auds, infos, 200.0, 2.0)
assert len(it) == 2 and len({x["path"] for x in it}) == 2                       # 곡마다 한 번(되풀이 없음)
for x in it:
    inf = infos[x["path"]]
    assert abs(x["off"] - inf["lead"]) < 1e-6 and abs(x["off"] + x["len"] - inf["dur"]) < 1e-6      # 처음 ~ 끝
assert it[0]["t0"] == 0.0 and abs(it[1]["t0"] - (it[0]["len"] - 2.0)) < 1e-6    # 2초 겹쳐 이어짐
end2 = M.music_end(it)                                                          # 59 - 2 + 50 = 107
assert abs(end2 - 107.0) < 1e-6
# 남은 영상 20초(≤ 30) = 그대로(뒤는 음악 없음)
assert M.fill_tail(it, auds, infos, end2 + 20.0, 2.0) == it
# 남은 영상 40초(> 30) = 한 번 더, 다른 소절(곡 뒷부분, 마디 첫 박)부터 · 곡 끝 ≈ 영상 끝
f = M.fill_tail(it, auds, infos, end2 + 40.0, 2.0)
assert len(f) == 3 and f[2].get("reuse") and f[2]["path"] != it[1]["path"]
ri = infos[f[2]["path"]]
assert f[2]["off"] > ri["lead"] + 5 and any(abs(f[2]["off"] - b) < 1e-6 for b in ri["bars"])
assert abs(f[2]["t0"] - (end2 - 2.0)) < 1e-6 and M.music_end(f) >= end2 + 40.0 - 1e-6
c = M.clip_end([dict(x) for x in f], end2 + 40.0)
assert abs(M.music_end(c) - (end2 + 40.0)) < 1e-3 and len(c) == 3
# 한 곡 · 영상이 훨씬 긺 = 되풀이 횟수 최소(매번 통째로, 마지막만 뒷부분)
one = [{"path": "/m/b.mp3"}]
f1 = M.fill_tail(M.plan_whole(one, infos, 170.0, 2.0), one, infos, 170.0, 2.0)
assert len(f1) == 3 and 170.0 - M.music_end(f1) <= 30.0 + 1e-6, [(x["t0"], x["off"], x["len"]) for x in f1]
starts = [x["off"] for x in f1]
assert starts[0] == 0.0 and all(M.music_end(f1[:k + 1]) > M.music_end(f1[:k]) for k in range(1, len(f1)))
# 영상이 곡보다 짧음 = 한 곡을 처음부터, 영상 끝에서 자름
s1 = M.clip_end(M.fill_tail(M.plan_whole(auds, infos, 40.0, 2.0), auds, infos, 40.0, 2.0), 40.0)
assert len(s1) == 1 and s1[0]["off"] == infos[s1[0]["path"]]["lead"] and abs(s1[0]["len"] - 40.0) < 1e-6
# 올린 곡 먼저, 기본 음악은 뒤
mix = [{"path": "/m/b.mp3", "builtin": True}, {"path": "/m/a.mp3"}]
assert [x["path"] for x in M.plan_whole(mix, infos, 200.0, 2.0)] == ["/m/a.mp3", "/m/b.mp3"]
assert M.plan_whole([], infos, 100.0) == [] and M.fill_tail([], auds, infos, 100.0) == []
print("음악:", [(Path(x["path"]).stem, x["t0"], x["off"], x["len"], bool(x.get("reuse"))) for x in f])

# ---------------------------------------------------------------- 6) 컷 경계 = 마디 첫 박, 컷 길이 = 마디의 정수배(음악은 제자리)
p = Project()
p.lead = 5.0
for i in range(6):
    s = Source(f"/v/DJI_2025102009{i:02d}00_0001_D.MP4", 30, 1, 30 * 120)
    s.width, s.height = 3840, 2160
    p.sources.append(s)
    g = Segment(s.id, 300, 300 + int(30 * (7.3 + 1.7 * i)))
    if i:
        g.trans = {"type": "dissolve", "dur": 0.5}
    p.segments.append(g)
vend0 = max(t + ln for _c, t, ln in cut_spans(p))
items = M.fill_tail(M.plan_whole(auds, infos, vend0, 2.0), auds, infos, vend0, 2.0)
p.music = [{**new_music(x["path"], x["t0"], x["dur"]), "off": x["off"], "len": x["len"], "follow": False} for x in items]
before = [(m["t0"], m["len"]) for m in p.music]
r = A.beat_lock(p, infos)
assert [(m["t0"], m["len"]) for m in p.music][1:] == before[1:] and p.music[0]["t0"] == before[0][0]      # 음악 = 제자리
m0 = p.music[0]
bars0 = M.beats_on_timeline(m0, infos[m0["path"]], bars=True)
sp = cut_spans(p)
assert min(abs(sp[0][1] - b) for b in bars0) < 0.02                              # 첫 컷 시작 = 마디 첫 박
bar = 2.0
pts = [sp[0][1]] + [sp[i][1] + 0.25 for i in range(1, len(sp))]                  # 첫 컷 시작 · 경계(전환 가운데)
for i in range(1, len(pts)):
    assert min(abs(pts[i] - b) for b in bars0) < 0.02, (i, pts[i])               # 경계 = 마디 첫 박
    n_bars = (pts[i] - pts[i - 1]) / bar
    assert abs(n_bars - round(n_bars)) < 0.02 and round(n_bars) >= 2, n_bars     # 경계 사이 = 마디의 정수배
assert r["bar"] == len(p.segments) - 1 and r["miss"] == 0, r
print("박자:", r, "· 컷 간격(마디)", [round((pts[i] - pts[i - 1]) / bar) for i in range(1, len(pts))])
_ = np
print("OK test_v1696")
sys.stdout.flush()
os._exit(0)
