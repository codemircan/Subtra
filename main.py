"""Subtra — giriş noktası.

Çalıştırma:
    py main.py          (konsollu, hata mesajları görünür)
    pyw main.py         (konsolsuz, önerilen)

DPI hakkında not:
    Qt 6, Windows'ta varsayılan olarak `PER_MONITOR_AWARE_V2` DPI bağlamını
    kendisi ayarlar (en iyi seçenek: çoklu monitörde net metin). Uygulama
    ayrıca `SetProcessDpiAwareness()` çağırırsa Qt bunu "zaten ayarlanmış"
    görüp uyarı basar ve bizim ayarımız daha zayıf olduğu için bulanıklık
    oluşur. Bu yüzden DPI ayarına hiç dokunmuyoruz.
"""

from __future__ import annotations

import ctypes
import os
import sys
import traceback


def _has_console() -> bool:
    """Gerçek bir konsol penceresi var mı? (pyw ile çalışırken yok)"""
    stream = sys.stderr
    if stream is None:
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def _show_error_box(title: str, message: str) -> None:
    """Konsol yokken hatayı MessageBox ile gösterir."""
    if os.name != "nt":
        return
    try:
        MB_ICONERROR = 0x10
        ctypes.windll.user32.MessageBoxW(None, message, title, MB_ICONERROR)
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
    """Konsol varsa stderr'e, yoksa MessageBox'a yazar; her durumda loglar."""
    try:
        if sys.stderr is not None:
            sys.stderr.write(message + "\n")
    except Exception:
        pass

    try:
        import logging_setup

        logging_setup.get_logger("fatal").error(message)
    except Exception:
        pass

    if not _has_console():
        _show_error_box("Subtra", message.strip())
    return 1


def main() -> int:
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
