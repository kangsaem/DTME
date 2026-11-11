"""DTME (Diving Tour Movie Editor) 실행 진입점."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dtme.ui_main import MainWindow  # noqa: E402


def dark(app: QApplication):
    from dtme import ui_style
    app.setStyle(ui_style.BevelStyle())      # Fusion + 모든 버튼 입체감(그림자 없음, v0.16.5)
    p = QPalette()
    c = {QPalette.Window: "#232323", QPalette.WindowText: "#e6e6e6", QPalette.Base: "#1a1a1a",
         QPalette.AlternateBase: "#262626", QPalette.Text: "#e6e6e6", QPalette.Button: "#2e2e2e",
         QPalette.ButtonText: "#e6e6e6", QPalette.Highlight: "#4a6fa5", QPalette.HighlightedText: "#ffffff",
         QPalette.ToolTipBase: "#333", QPalette.ToolTipText: "#eee", QPalette.PlaceholderText: "#777"}
    for role, col in c.items():
        p.setColor(role, QColor(col))
    app.setPalette(p)


def purge_frame_cache():
    """미리보기 프레임 캐시는 시작할 때 비운다(프레임 이동마다 쌓이므로)."""
    import shutil
    from dtme import paths
    shutil.rmtree(paths.cache_dir() / "frames", ignore_errors=True)


_fault_file = None


def crash_log():
    """화면 코드에서 난 오류·프로그램이 튕길 때의 위치를 기록으로(v0.16.40). 창만 있는 exe 는 오류가 보이지 않고 사라졌음.
    cache/dtme.log = 파이썬 오류, cache/crash.log = 튕김(접근 위반 등) 때 스레드별 위치."""
    global _fault_file
    import faulthandler
    import threading
    import traceback
    from dtme import ff, paths
    ff.log_trim()
    try:
        f = paths.cache_dir() / "crash.log"
        if f.exists() and f.stat().st_size > (1 << 20):
            f.unlink()
        _fault_file = open(f, "a", encoding="utf-8")       # 닫지 않음(튕길 때 여기에 씀)
        faulthandler.enable(_fault_file)
    except Exception:  # noqa: BLE001
        pass
    old = sys.excepthook

    def hook(tp, val, tb):
        if not issubclass(tp, KeyboardInterrupt):
            ff.log_error("오류", "".join(traceback.format_exception(tp, val, tb))[-3000:])
        old(tp, val, tb)
    sys.excepthook = hook
    threading.excepthook = lambda a: ff.log_error(
        f"오류(스레드 {a.thread.name if a.thread else '?'})",
        "".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback))[-3000:])


def hw_check():
    """그래픽 판별(NVENC → Quick Sync → 없음)을 뒤에서 미리 — 첫 렌더·프록시가 기다리지 않게(v0.16.48)."""
    import threading
    from dtme import ff, jobs

    def work():
        try:
            ff.hw_kind()
            jobs.apply_hw()
        except Exception as e:  # noqa: BLE001
            ff.log_error("그래픽 확인", str(e))
    threading.Thread(target=work, name="hw", daemon=True).start()


def main():
    purge_frame_cache()
    crash_log()
    # Qt 멀티미디어는 FFmpeg 백엔드 사용(Windows 기본)
    os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
    app = QApplication(sys.argv)
    app.setApplicationName("DTME")
    hw_check()
    dark(app)
    w = MainWindow()
    args = [a for a in sys.argv[1:] if Path(a).suffix.lower() in (".mp4", ".mov")]
    restored = False
    if w.autosave_file().exists() and not args and not os.environ.get("DTME_SELFTEST"):
        # 자동 저장 파일이 남아 있음 = 지난번에 정상 종료가 아니었음(정상 종료·저장 때는 지움, v0.16.41)
        from dtme import ui_style
        if ui_style.confirm(None, "저장 안 된 작업이 남아 있습니다.",
                            [("cancel", "버리기", 80, None), ("ok", "되살리기", 92, "blue")]) == "ok":
            restored = w.restore_autosave()
        w.drop_autosave()
    if args or restored or os.environ.get("DTME_NO_LAUNCHER"):
        w.show()
    else:                                  # 시작 창: 큰 AUTO + 작은 MANUAL (v0.16.8)
        from dtme.ui_launch import Launcher
        w._launcher = Launcher(w)
        w._launcher.center()
        w._launcher.show()
    if os.environ.get("DTME_SELFTEST"):   # 빌드 점검용: 창을 띄우고 2초 뒤 종료
        from PySide6.QtCore import QTimer
        from PySide6.QtMultimedia import QMediaFormat
        n = len(QMediaFormat().supportedFileFormats(QMediaFormat.Decode))
        QTimer.singleShot(2000, lambda: app.exit(0 if n > 0 else 3))
    if args:
        w.edit.import_files(args)
    code = app.exec()
    sys.exit(finish(code))


def finish(code: int) -> int:
    """창을 닫으면 남은 작업·ffmpeg 를 정리하고 바로 끝냄(v0.16.23). 스레드가 끝날 때까지 기다리지 않음."""
    from dtme import ff, jobs, paths
    try:                                   # 정상 종료 = 자동 저장 파일 지움(남아 있으면 다음에 되살릴지 물음)
        (paths.cache_dir() / "autosave.dtme.json").unlink(missing_ok=True)
    except OSError:
        pass
    try:
        n = jobs.shutdown()
        if n:
            ff.log_info(f"종료: ffmpeg {n}개 끔")
    except Exception:  # noqa: BLE001
        pass
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass
    if os.environ.get("DTME_NO_HARD_EXIT"):
        return code
    os._exit(code)


if __name__ == "__main__":
    main()
