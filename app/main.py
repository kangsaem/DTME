"""DTME (Diving Tour Movie Editor) 실행 진입점."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dtme.ui_main import MainWindow  # noqa: E402


def dark(app: QApplication):
    app.setStyle("Fusion")
    p = QPalette()
    c = {QPalette.Window: "#232323", QPalette.WindowText: "#e6e6e6", QPalette.Base: "#1a1a1a",
         QPalette.AlternateBase: "#262626", QPalette.Text: "#e6e6e6", QPalette.Button: "#2e2e2e",
         QPalette.ButtonText: "#e6e6e6", QPalette.Highlight: "#4a6fa5", QPalette.HighlightedText: "#ffffff",
         QPalette.ToolTipBase: "#333", QPalette.ToolTipText: "#eee", QPalette.PlaceholderText: "#777"}
    for role, col in c.items():
        p.setColor(role, QColor(col))
    app.setPalette(p)


def main():
    # Qt 멀티미디어는 FFmpeg 백엔드 사용(Windows 기본)
    os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
    app = QApplication(sys.argv)
    app.setApplicationName("DTME")
    dark(app)
    w = MainWindow()
    w.show()
    args = [a for a in sys.argv[1:] if Path(a).suffix.lower() in (".mp4", ".mov")]
    if args:
        w.edit.import_files(args)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
