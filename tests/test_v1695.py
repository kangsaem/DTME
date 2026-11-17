"""v0.16.95: 여행 나누기(7일+) · 지명·기간 여행별(같은 지명 = 시·군) · 새 여행 첫 LOG 컷 = LOG 끄고 날짜 바 ·
시작 화면 0초부터 글자(지명 100 · 기간 50, 폭 85% 넘으면 줄임, 5초) · 세로 날짜 바 맨 아래(92%).
사용: python tests/test_v1695.py"""
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
from dtme import autoedit as A, divelog  # noqa: E402
from dtme.project import Project, Source  # noqa: E402


def T(y, mo, d, h=9, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp()      # 현지 시간대 없는 초(코드와 같은 방식)


# 1) 여행 나누기
tr = A.trips_of([(T(2025, 10, 20), T(2025, 10, 20, 10)), (T(2025, 10, 21), T(2025, 10, 21, 10)),
                 (T(2026, 3, 20), T(2026, 3, 20, 10)), (T(2026, 3, 26, 9), T(2026, 3, 26, 10))])
assert len(tr) == 2 and tr[0][0] == T(2025, 10, 20) and tr[1][1] == T(2026, 3, 26, 10), tr      # 6일 뒤(3/26) = 같은 여행
assert len(A.trips_of([(T(2026, 3, 20), T(2026, 3, 20, 10)), (T(2026, 3, 27, 10), T(2026, 3, 27, 11))])) == 2   # 7일 = 새 여행
print("기간:", A.trips_period(tr))
assert A.trips_period(tr) == "2025.10.20 ~ 2026.03.26"                  # v0.16.96 처음 ~ 끝 하나로

# 2) DTMD 메모 '위치:' → loc(뒤 두 부분) + city(앞 부분)
obj = {"logs": [
    {"date": "2025-10-20", "time": "09:00", "state": {"dives": [
        {"fit": True, "memo": "위치: 미야코지마시, 오키나와현, 일본", "sec0": 32406, "pts": [{"t": 0, "d": 0}, {"t": 60, "d": 10}, {"t": 600, "d": 12}, {"t": 900, "d": 0}]}]}},
    {"date": "2026-03-20", "time": "09:00", "state": {"dives": [
        {"fit": True, "memo": "위치: 이시가키시, 오키나와현, 일본", "sec0": 33000, "pts": [{"t": 0, "d": 0}, {"t": 60, "d": 9}, {"t": 600, "d": 11}, {"t": 900, "d": 0}]},
        {"fit": True, "memo": "위치: 다케토미초, 오키나와현, 일본", "sec0": 40000, "pts": [{"t": 0, "d": 0}, {"t": 60, "d": 9}, {"t": 600, "d": 11}, {"t": 900, "d": 0}]},
        {"fit": True, "memo": "위치: 이시가키시, 오키나와현, 일본", "sec0": 46000, "pts": [{"t": 0, "d": 0}, {"t": 60, "d": 9}, {"t": 600, "d": 11}, {"t": 900, "d": 0}]}]}},
    {"date": "2026-06-21", "time": "09:00", "state": {"dives": [
        {"fit": True, "memo": "위치: Panglao, 보홀주, 필리핀", "sec0": 33000, "pts": [{"t": 0, "d": 0}, {"t": 60, "d": 9}, {"t": 600, "d": 11}, {"t": 900, "d": 0}]}]}},
]}
dv = divelog.dtmd_dives(obj, "logbook.json")
print("지명:", [(d.get("loc"), d.get("city")) for d in dv])
assert [d.get("city") for d in dv] == ["미야코지마시", "이시가키시", "다케토미초", "이시가키시", "Panglao"]
assert all(d.get("loc") for d in dv)
# 다시 불러온 같은 백업(예전 프로젝트 = city 없음) → city 붙음
old = [{k: v for k, v in d.items() if k != "city"} for d in dv]
mg = divelog.merge(old, dv) if hasattr(divelog, "merge") else None
if mg is not None:
    assert all(d.get("city") for d in mg), mg

oki2 = [(T(2025, 10, 20, 0), T(2025, 10, 20, 23)), (T(2026, 3, 20, 0), T(2026, 3, 20, 23))]
pl = A.trips_place(dv, oki2)
print("같은 지명 두 여행:", pl)
assert pl == "미야코지마시 · 이시가키시, 오키나와현, 일본"
assert A.trips_place(dv, oki2[:1]) == "오키나와현, 일본"                          # 한 여행 = 예전처럼
pl3 = A.trips_place(dv, oki2 + [(T(2026, 6, 21, 0), T(2026, 6, 21, 23))])
print("세 여행:", pl3)
assert pl3 == "미야코지마시 · 이시가키시, 오키나와현, 일본 · 보홀주, 필리핀"
assert A.trips_place([{**d, "city": ""} for d in dv], oki2) == "오키나와현, 일본"     # 시·군 모름 = 하나로
assert len(A.trips_dives(dv, oki2)) == 4                                          # 여행 사이(6월) 다이빙은 뺌

# 3) 시작 화면: 0초부터 글자 · 크기 · 5초 · 길면 줄임(세로)
assert A.START_SEC == 5.0 and A.START_DARK == 2.0
sc = A.start_card("오키나와현, 일본", "2025.10.20", A.START_SEC, (1920, 1080))
txt = [x for x in sc if x["kind"] == "text"]
assert [x["size"] for x in txt] == [160, 80] and all(x["ain"] == "cut" and x["t0"] == 0.0 and "tdelay" not in x for x in txt)
assert sc[0]["kind"] == "rect" and sc[0]["fade"] == 2.0 and sc[0]["t1"] == 5.0
longp = "미야코지마시 · 이시가키시, 오키나와현, 일본"
sv = [x for x in A.start_card(longp, "2025.10.20 ~ 10.21 · 2026.03.20 ~ 03.23", 5.0, (1080, 1920)) if x["kind"] == "text"]
sh = [x for x in A.start_card(longp, "2025.10.20 ~ 10.21 · 2026.03.20 ~ 03.23", 5.0, (1920, 1080)) if x["kind"] == "text"]
print("세로 줄인 크기:", [x["size"] for x in sv], "가로:", [x["size"] for x in sh])
assert sv[0]["size"] < 160 and sh[0]["size"] <= 160
for x in sv:
    w = A._metrics(x)[0]
    assert w <= 0.85 * 1080 + 2, (x["text"], w)

# 4) 세로 날짜 바 = 맨 아래(사각형 위 ≈ 92%) · 가로 = 예전 그대로
rc_v = A.date_bar(T(2026, 3, 20, 10), 1.0, (1080, 1920))[0]
top_v = rc_v["cy"] - rc_v["h"] / 2
print("세로 날짜 바 위·아래:", round(top_v, 3), round(rc_v["cy"] + rc_v["h"] / 2, 3))
assert abs(top_v - 0.92) < 0.005 and rc_v["cy"] + rc_v["h"] / 2 < 1.0
rc_h = A.date_bar(T(2026, 3, 20, 10), 1.0, (1920, 1080))[0]
assert 0.75 < rc_h["cy"] < 0.9

# 5) 새 여행 첫 컷이 LOG 컷 = 그 컷만 LOG 끄고 날짜 바(클립마다 · 전부 자동 둘 다)
from dtme import dive_draw  # noqa: E402
p = Project()
names = ["DJI_20251020094016_0010_D.MP4", "DJI_20251020101500_0011_D.MP4", "DJI_20260320100009_0042_D.MP4", "DJI_20260320103000_0043_D.MP4"]
for nm in names:
    p.sources.append(Source(path=f"/x/{nm}", fps_num=30, fps_den=1, frames=1200, width=1920, height=1080))
p.dives, p.dive_on = dv, True
dive_draw.cut_dive = lambda *a, **k: True                                       # 모든 컷 = 다이빙 컷으로
picks = [{"src": s, "scene": "", "score": np.ones(80), "surface": None} for s in p.sources]
for dm in ("clip", "gap"):
    plan = A.build(p, picks, 1, seed=1, date_mode=dm)
    segs = plan["segs"]
    first_of = {}
    for g in segs:
        first_of.setdefault(g.src, g)
    logs = [first_of[s.id].log for s in p.sources]
    bars = [x["text"] for x in plan["titles"] if x.get("datebar") and x.get("size") == A.DB_TIME]
    print(dm, "첫 컷 LOG:", logs, "날짜 바:", bars)
    assert logs == [True, True, False, True], logs                              # 2026.03.20 첫 클립만 LOG 끔
    assert bars == ["10:00"], bars                                               # 그 컷에만 날짜 바
print("OK test_v1695", flush=True)
os._exit(0)
