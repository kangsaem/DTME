"""v0.16.23 점검: 창을 닫으면 남은 작업·ffmpeg 를 정리하고 바로 종료(대기열을 끝까지 돌지 않음).
1) 단위: 긴 ffmpeg 작업 여러 개(돌던 것 + 대기열) → jobs.shutdown() → ffmpeg 0개, 대기열 작업 시작 안 함, 이후 새 ffmpeg 안 띄움
2) 실제 앱: 자식 프로세스로 main.main() 실행 → 긴 ffmpeg 작업을 넣고 메인 창 닫기 → 몇 초 안에 프로세스 종료 + ffmpeg 남지 않음
사용: python tests/test_shutdown.py"""
import os, sys, time, subprocess, textwrap
HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "..", "app")
TAG = f"dtmeshutdown{os.getpid()}"            # ffmpeg 명령 안의 표시 → 남은 프로세스 찾기
LONG = ["-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:d=600", "-metadata", f"comment={TAG}", "-f", "null", "-"]


def leftover() -> int:
    if os.name == "nt":                        # 명령줄에 TAG 가 든 ffmpeg 개수
        ps = (f"(Get-CimInstance Win32_Process -Filter \"Name='ffmpeg.exe'\" | "
              f"Where-Object {{ $_.CommandLine -like '*{TAG}*' }} | Measure-Object).Count")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
        return int((r.stdout.strip() or "0").splitlines()[-1])
    r = subprocess.run(["pgrep", "-f", TAG], capture_output=True, text=True)
    return len([x for x in r.stdout.split() if x.strip() and int(x) != os.getpid()])


# ---------------------------------------------------------------- 1) 단위
if len(sys.argv) < 2:
    sys.path.insert(0, APP)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication(sys.argv)
    from dtme import ff, jobs, paths
    exe = paths.ffmpeg()
    started = []
    if os.name == "nt":                        # Windows: 작업 묶음(DTME 가 죽어도 ffmpeg 같이 종료)
        assert ff._win_job(), "Job Object 만들기 실패"
        print("Windows 작업 묶음: OK")

    def work(i):
        def f():
            started.append(i)
            ff.run([exe] + LONG)
        return f
    for i in range(6):                         # PROXY_POOL = 2 → 2개 돌고 4개 대기
        jobs.submit(jobs.PROXY_POOL, jobs.Job(work(i)))
    t = time.time()
    while not (ff.live_count() == 2 and leftover() == 2) and time.time() - t < 20:   # 2개 다 뜰 때까지(Windows 는 세는 데 시간이 걸림)
        time.sleep(0.2)
    print("돌던 ffmpeg", ff.live_count(), "· 시작한 작업", len(started), "· 남은 프로세스", leftover())
    assert ff.live_count() == 2 and leftover() == 2
    t = time.time()
    n = jobs.shutdown()
    dt = time.time() - t
    time.sleep(0.3)
    print(f"shutdown {dt:.2f}초, 끈 ffmpeg {n}, 남은 ffmpeg {ff.live_count()} / 프로세스 {leftover()}, 시작한 작업 {len(started)}")
    # 대기 작업은 대부분 지워지지만, 끈 작업이 끝나는 순간 풀이 다음 것을 집을 수 있음(Windows CI 에서 가끔) →
    # 그래도 ffmpeg 는 못 띄움(Cancelled) = 핵심은 남은 ffmpeg 0
    time.sleep(0.5)
    assert n >= 2 and ff.live_count() == 0 and leftover() == 0 and dt < 3
    try:
        ff.run([exe, "-version"])
        raise AssertionError("종료 중인데 ffmpeg 를 띄움")
    except ff.Cancelled:
        print("종료 중 새 ffmpeg 막음: OK")

    # ------------------------------------------------------------ 2) 실제 앱
    child = textwrap.dedent(f"""
        import os, sys, threading
        sys.path.insert(0, {APP!r})
        os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["DTME_NO_LAUNCHER"] = "1"; os.environ["DTME_NO_AUDIO"] = "1"
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        import main as M
        from dtme import ff, jobs, paths
        from dtme.ui_main import MainWindow
        orig = MainWindow.__init__
        def init(self, *a, **k):
            orig(self, *a, **k)
            def load():
                for i in range(8):
                    jobs.submit(jobs.PROXY_POOL, jobs.Job(lambda: ff.run([paths.ffmpeg()] + {LONG!r})))
                print("작업 넣음", flush=True)
            QTimer.singleShot(300, load)
            QTimer.singleShot(2500, lambda: (print("창 닫기, ffmpeg", ff.live_count(), flush=True), self.close()))
        MainWindow.__init__ = init
        M.main()
    """)
    t = time.time()
    p = subprocess.Popen([sys.executable, "-c", child], cwd=APP)
    try:
        rc = p.wait(20)
    except subprocess.TimeoutExpired:
        p.kill()
        raise AssertionError(f"창을 닫았는데 20초 안에 안 끝남, 남은 ffmpeg {leftover()}")
    dt = time.time() - t
    time.sleep(0.3)
    print(f"앱 종료 코드 {rc}, 시작부터 {dt:.1f}초(닫기는 2.5초 때), 남은 ffmpeg {leftover()}")
    assert rc == 0 and dt < 8 and leftover() == 0
    print("OK")
