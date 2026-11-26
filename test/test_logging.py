"""Log testi: iş akışı mesajları dosyaya yazılıyor mu, panelde tekrar var mı?"""

import io
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import logging_setup  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


print("=" * 66)
print("LOG TESTİ")
print("=" * 66)

logging_setup.setup_logging()
path = logging_setup.log_file_path()
print(f"Dosya: {path}")

check("log dosyası yolu var", path.parent.exists())
check("log dosyası oluşturuldu", path.exists())

# Panel kuyruğunu boşalt (setup mesajı)
logging_setup.poll_messages(1000)

MARKER_FILE = f"TEST-FILE-ONLY-{os.getpid()}"
MARKER_UI = f"TEST-UI-{os.getpid()}"

print("\n1) log_to_file: dosyaya yazar, panele EKLEMEZ")
logging_setup.log_to_file(MARKER_FILE)
time.sleep(0.15)

tail = logging_setup.read_log_tail(50)
check("mesaj dosyada", MARKER_FILE in tail)

ui = logging_setup.poll_messages(1000)
check("mesaj panelde YOK (tekrar yok)", not any(MARKER_FILE in m for m in ui),
      f"{len(ui)} panel mesajı")

print("\n2) get_logger().info: hem dosyaya hem panele")
log = logging_setup.get_logger("test")
log.info(MARKER_UI)
time.sleep(0.15)

tail = logging_setup.read_log_tail(50)
check("mesaj dosyada", MARKER_UI in tail)

ui = logging_setup.poll_messages(1000)
check("mesaj panelde VAR", any(MARKER_UI in m for m in ui))

print("\n3) RotatingFileHandler yapılandırması")
handler = logging_setup._file_handler
check("dosya handler aktif", handler is not None)
check("rotasyon boyutu 2 MB", getattr(handler, "maxBytes", 0) == 2 * 1024 * 1024,
      str(getattr(handler, "maxBytes", None)))
check("3 yedek dosya", getattr(handler, "backupCount", 0) == 3,
      str(getattr(handler, "backupCount", None)))
check("UTF-8 kodlama", getattr(handler, "encoding", "").lower() == "utf-8")

print("\n4) Arayüz _append_log dosyaya da yazıyor mu")
try:
    from PySide6.QtWidgets import QApplication

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from gui import MainWindow

    window = MainWindow()
    MARKER_GUI = f"TEST-GUI-{os.getpid()}"
    window._append_log(MARKER_GUI)
    time.sleep(0.15)
    tail = logging_setup.read_log_tail(50)
    check("GUI iş akışı mesajı dosyada", MARKER_GUI in tail)
    window.close()
except Exception as exc:  # noqa: BLE001
    check("GUI testi", False, f"{type(exc).__name__}: {exc}")

failed = [label for label, ok, _ in checks if not ok]
print()
if failed:
    print(f"LOG TESTİ BAŞARISIZ: {failed}")
    sys.exit(1)
print("LOG TESTİ GEÇTİ")
