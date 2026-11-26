"""Loglama: hem donen dosyaya hem arayuz paneline yazan tek kaynak."""

from __future__ import annotations

import logging
import queue
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

import app_paths

LOGGER_NAME = "subtra"
LOG_FILE_NAME = "subtra.log"
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 3
FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class _QueueHandler(logging.Handler):
    """Log kayitlarini thread-guvenli bir kuyruga aktarir."""

    def __init__(self, sink: "queue.Queue[str]") -> None:
        super().__init__()
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._sink.put_nowait(self.format(record))
        except Exception:
            pass


_ui_queue: "queue.Queue[str]" = queue.Queue()
_initialised = threading.Lock()
_ready = False
_file_handler: RotatingFileHandler | None = None


def log_file_path() -> Path:
    return app_paths.logs_dir() / LOG_FILE_NAME


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Kok logger'i bir kez yapilandirir (idempotent)."""
    global _ready, _file_handler
    with _initialised:
        logger = logging.getLogger(LOGGER_NAME)
        if _ready:
            return logger

        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        formatter = logging.Formatter(FORMAT, DATE_FORMAT)

        try:
            file_handler = RotatingFileHandler(
                log_file_path(),
                maxBytes=MAX_BYTES,
                backupCount=BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            _file_handler = file_handler
        except OSError:
            pass  # log dosyasi acilamazsa uygulama yine calissin

        ui_handler = _QueueHandler(_ui_queue)
        ui_handler.setLevel(logging.DEBUG)
        ui_handler.setFormatter(formatter)
        logger.addHandler(ui_handler)

        if sys.stderr and sys.stderr.isatty():
            console = logging.StreamHandler(sys.stderr)
            console.setLevel(level)
            console.setFormatter(formatter)
            logger.addHandler(console)

        _ready = True
        logger.info("Loglama başlatıldı. Dosya: %s", log_file_path())
        return logger


def log_to_file(message: str, level: int = logging.INFO) -> None:
    """Mesaji YALNIZCA dosyaya yazar (arayuz kuyruguna eklemez).

    Arayuzde zaten gorunen is akisi mesajlari icin kullanilir; boylece
    panelde tekrar olusmaz ama cokme durumunda kayit dosyada kalir.
    """
    setup_logging()
    if _file_handler is None:
        return
    try:
        record = logging.LogRecord(
            name=f"{LOGGER_NAME}.worker",
            level=level,
            pathname=__file__,
            lineno=0,
            msg=message,
            args=(),
            exc_info=None,
        )
        _file_handler.handle(record)
    except Exception:
        pass



def get_logger(suffix: str = "") -> logging.Logger:
    setup_logging()
    if suffix:
        return logging.getLogger(f"{LOGGER_NAME}.{suffix}")
    return logging.getLogger(LOGGER_NAME)


def poll_messages(limit: int = 300) -> list[str]:
    """Arayuz tarafindan cagrilir; birikmis log satirlarini bosaltir."""
    messages: list[str] = []
    for _ in range(limit):
        try:
            messages.append(_ui_queue.get_nowait())
        except queue.Empty:
            break
    return messages


def read_log_tail(max_lines: int = 200) -> str:
    """Hata raporu icin log dosyasinin son satirlari."""
    path = log_file_path()
    if not path.exists():
        return "(log dosyası bulunamadı)"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError as exc:
        return f"(log okunamadı: {exc})"
    tail = lines[-max_lines:]
    return "".join(tail).strip() or "(log boş)"
