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


def main():
    purge_frame_cache()
    # Qt 멀티미디어는 FFmpeg 백엔드 사용(Windows 기본)
    os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
    app = QApplication(sys.argv)
    app.setApplicationName("DTME")
    dark(app)
    w = MainWindow()
    args = [a for a in sys.argv[1:] if Path(a).suffix.lower() in (".mp4", ".mov")]
    if args or os.environ.get("DTME_NO_LAUNCHER"):
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
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
