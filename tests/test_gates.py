"""v0.16.24 점검: 저장장치·GPU 자리(ff.Gate).
1) 자리 수: 같은 저장장치를 읽는 ffmpeg 가 disk_jobs 를 넘지 않음(풀이 달라도)
2) 우선순위: 자리가 차 있을 때 나중에 온 분석(1)이 먼저 온 프록시(3)보다 먼저
3) 어느 자리를 쓰는지: 파일 입력 = 그 장치, lavfi = 없음, -hwaccel·nvenc = GPU, 화면 스레드 = 기다리지 않음
4) 종료 중이면 기다리던 작업이 Cancelled
사용: python tests/test_gates.py"""
import os, sys, time, threading, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QCoreApplication
app = QCoreApplication(sys.argv)
from dtme import ff, jobs, paths

work = tempfile.mkdtemp()
clip = os.path.join(work, "a.mp4")
ff.run([paths.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:d=1", clip])

# 3) 어느 자리
res = {}
def probe_gates():
    res["file"] = [g.name for g in ff._gates_for([paths.ffmpeg(), "-i", clip, "-f", "null", "-"])]
    res["lavfi"] = [g.name for g in ff._gates_for([paths.ffmpeg(), "-f", "lavfi", "-i", "color", "-f", "null", "-"])]
    res["gpu"] = [g.name for g in ff._gates_for([paths.ffmpeg(), "-hwaccel", "cuda", "-i", clip, "-f", "null", "-"])]
    res["nvenc"] = [g.name for g in ff._gates_for([paths.ffmpeg(), "-i", clip, "-c:v", "h264_nvenc", "o.mp4"])]
t = threading.Thread(target=probe_gates); t.start(); t.join()
res["main"] = ff._gates_for([paths.ffmpeg(), "-i", clip, "-f", "null", "-"])
print("자리:", res)
assert len(res["file"]) == 1 and res["file"][0].startswith("disk:") and res["lavfi"] == [] and res["main"] == []
assert res["gpu"][0] == "gpu" and res["gpu"][1].startswith("disk:") and res["nvenc"][0] == "gpu"

# 1) 2) 자리 수·우선순위: 자리 2개, 긴 ffmpeg(파일 입력)를 프록시 풀 4개 + 분석 풀 2개
from dtme import project
project.set_setting("disk_jobs", 2)
order, peak, lock = [], [0], threading.Lock()
LONG = lambda: [paths.ffmpeg(), "-v", "error", "-stream_loop", "-1", "-re", "-i", clip, "-t", "1.2", "-f", "null", "-"]

def work_fn(tag):
    def f():
        with lock:
            order.append(tag)
        ff.run(LONG())
        return tag
    return f
done = []
for i in range(4):
    j = jobs.Job(work_fn(f"proxy{i}")); j.signals.done.connect(done.append); jobs.submit(jobs.PROXY_POOL, j)
time.sleep(0.15)
# PROXY_POOL 은 2개씩 → proxy0·1 이 자리 2개를 차지. 다른 풀(미리보기 뒤 = 4)도 넣어 둠
for i in range(2):
    j = jobs.Job(work_fn(f"bg{i}")); j.signals.done.connect(done.append); jobs.submit(jobs.PREVIEW_POOL, j, priority=-5)
time.sleep(0.15)
for i in range(2):
    j = jobs.Job(work_fn(f"auto{i}")); j.signals.done.connect(done.append); jobs.submit(jobs.AUTO_POOL, j)
t0 = time.time()
while len(done) < 8 and time.time() - t0 < 60:
    app.processEvents()
    peak[0] = max(peak[0], ff.live_count())
    time.sleep(0.02)
print("끝난 순서:", done, "· 동시 ffmpeg 최대", peak[0])
assert len(done) == 8 and peak[0] <= 2, "자리 2개를 넘음"
first2 = set(done[:2])
assert first2 == {"proxy0", "proxy1"}, first2
assert set(done[2:4]) == {"auto0", "auto1"}, f"분석(1)이 먼저여야: {done}"
assert set(done[-2:]) == {"bg0", "bg1"}, f"뒤에서 미리(4)가 마지막: {done}"
project.set_setting("disk_jobs", 0)

# 4) 종료 중 대기 작업 취소
g = ff.Gate("t", 1); g.acquire(0)
err = {}
def waiter():
    try:
        g.acquire(1)
    except ff.Cancelled:
        err["c"] = True
th = threading.Thread(target=waiter); th.start(); time.sleep(0.3)
ff._closing.set(); th.join(3); ff._closing.clear()
assert err.get("c"), "종료 중 대기 취소 안 됨"
print("OK")
