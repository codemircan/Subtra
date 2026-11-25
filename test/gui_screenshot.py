"""GUI ekran goruntuleri: tum sekmeleri PNG olarak kaydeder."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import logging_setup  # noqa: E402
from gui import MainWindow  # noqa: E402

OUT = Path(__file__).resolve().parent


def main() -> int:
    logging_setup.setup_logging()
    app = QApplication(sys.argv[:1])
    window = MainWindow()
    window.resize(960, 900)
    window.show()

    video = sys.argv[1] if len(sys.argv) > 1 else ""
    if video:
        resolved = str(Path(video).resolve())
        window._set_single_input(resolved)
        window._srt_input = resolved
        window.srt_file_label.setText(resolved)
        window._refresh_cache_table()
        window._refresh_ffmpeg_status(silent=True)
        window._refresh_hardware()

    def capture() -> None:
        names = ["tab_video", "tab_queue", "tab_srt", "tab_settings"]
        for index, name in enumerate(names):
            window.tabs.setCurrentIndex(index)
            QApplication.processEvents()
            window.grab().save(str(OUT / f"gui_{name}.png"))
            print("saved", name)
        app.quit()

    QTimer.singleShot(1200, capture)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
