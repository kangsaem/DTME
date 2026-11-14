"""v0.16.91 화면 보는 중(B·D): 뒤 작업 ffmpeg 일시정지·다시 · 새 화면 요청 = 지난 화면 ffmpeg 끔(Cancelled).
사용: python tests/test_browse.py"""
import os, sys, threading, time  # noqa: E401
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from dtme import ff, paths  # noqa: E402
cmd = [paths.ffmpeg(), "-v", "error", "-re", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=3", "-f", "null", "-"]
# 뒤 작업(prio 3) = 화면 보는 중이면 멈췄다가 다시
res = {}


def bg():
    ff.set_prio(3)
    t = time.time(); ff.run(cmd); res["bg"] = time.time() - t
th = threading.Thread(target=bg); th.start(); time.sleep(0.3)
ff.set_browsing(True); time.sleep(0.3)
sus = list(ff._suspended)
state = ""
if sus and os.path.exists(f"/proc/{sus[0].pid}/stat"):
    state = open(f"/proc/{sus[0].pid}/stat").read().split(")")[1].split()[0]
print("멈춘 뒤 작업:", len(sus), "상태", state)
assert len(sus) == 1 and (state in ("T", "t") or os.name == "nt")
time.sleep(1.0); ff.set_browsing(False)
assert not ff._suspended
th.join(60)
print("뒤 작업 걸린 시간:", round(res["bg"], 2))
assert "bg" in res
# 화면 작업 = 새 요청이 오면 끔 → Cancelled
out = {}


def pv():
    ff.set_prio(0)
    try:
        with ff.preview_job(1):
            ff.run([paths.ffmpeg(), "-v", "error", "-re", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=60", "-f", "null", "-"])
        out["r"] = "끝남"
    except ff.Cancelled:
        out["r"] = "취소"
th = threading.Thread(target=pv); th.start(); time.sleep(0.5)
n = ff.kill_previews(2)
th.join(10)
print("끔:", n, out)
assert n == 1 and out["r"] == "취소"
print("OK test_browse", flush=True)
