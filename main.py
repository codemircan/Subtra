"""Subtra - giris noktasi.

Calistirma:
    py main.py
"""

from __future__ import annotations

import ctypes
import os
import sys
import traceback


def _enable_high_dpi() -> None:
    """Windows'ta bulanik arayuzu onler."""
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _check_dependencies() -> list[str]:
    missing: list[str] = []
    for module, package in (
        ("PySide6", "PySide6"),
        ("faster_whisper", "faster-whisper"),
        ("ctranslate2", "ctranslate2"),
        ("requests", "requests"),
        ("tokenizers", "tokenizers"),
    ):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    return missing


def _fatal(message: str) -> int:
    sys.stderr.write(message + "\n")
    try:
        import logging_setup

        logging_setup.get_logger("fatal").error(message)
    except Exception:
        pass
    return 1


def main() -> int:
    _enable_high_dpi()

    missing = _check_dependencies()
    if missing:
        return _fatal(
            "Eksik paket(ler): " + ", ".join(missing) + "\n"
            "Kurulum: py -m pip install -r requirements.txt\n"
        )

    import logging_setup

    logger = logging_setup.setup_logging()
    logger.info("Uygulama başlıyor (sürüm %s)", _version())

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QMessageBox

    from gui import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Subtra")
    app.setApplicationDisplayName("Subtra")
    app.setOrganizationName("Subtra")
    app.setAttribute(Qt.AA_DontUseNativeMenuBar, False)
    app.setFont(QFont("Segoe UI", 9))

    try:
        window = MainWindow()
        window.show()
    except Exception:  # noqa: BLE001
        detail = traceback.format_exc()
        logger.exception("Arayüz başlatılamadı")
        QMessageBox.critical(
            None,
            "Başlatma hatası",
            "Arayüz başlatılamadı:\n\n" + detail,
        )
        return 1

    exit_code = app.exec()
    logger.info("Uygulama kapandı (kod %s)", exit_code)
    return exit_code


def _version() -> str:
    try:
        import error_report

        return error_report.app_version()
    except Exception:
        return "?"


if __name__ == "__main__":
    sys.exit(main())
