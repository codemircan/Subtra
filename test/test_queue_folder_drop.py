"""Kuyruga klasor surukle-birak testi.

Model/FFmpeg gerekmez: yalnizca yol genisletme ve arayuz davranisi.
Sahte video dosyalari (icerik onemsiz) uretilir.
"""

import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QMimeData, Qt, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
import PySide6.QtWidgets as QtWidgets  # noqa: E402

QtWidgets.QMessageBox.information = staticmethod(lambda *a, **k: None)
QtWidgets.QMessageBox.warning = staticmethod(lambda *a, **k: None)

app = QApplication(sys.argv[:1])

import gui  # noqa: E402
from worker import SUPPORTED_EXTENSIONS  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


WORK = Path(tempfile.mkdtemp(prefix="subtra_klasor_"))


def touch(relative: str, size: int = 256) -> Path:
    path = WORK / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)
    return path


print("=" * 66)
print("KUYRUGA KLASOR SURUKLE-BIRAK")
print("=" * 66)

# --- Fixture: ic ice klasorler + alakasiz dosyalar -------------------------
print("\n0) Test klasoru hazirlaniyor")
root = WORK / "Türkçe Dizi"
bolum1 = touch("Türkçe Dizi/1. Bölüm.mp4")
bolum2 = touch("Türkçe Dizi/Sezon 2/2. bölüm.mkv")
srt = touch("Türkçe Dizi/1. Bölüm.srt")
notlar = touch("Türkçe Dizi/notlar.txt")
gizli = touch("Türkçe Dizi/.gizli/3.mp4")
bos_klasor = WORK / "Boş Klasör"
bos_klasor.mkdir()
sadece_metin = WORK / "Sadece Metin"
(sadece_metin / "okuma.txt").parent.mkdir(parents=True, exist_ok=True)
(sadece_metin / "okuma.txt").write_text("x", encoding="utf-8")

print(f"   kok: {root}")
check("fixture olustu", root.is_dir() and bolum1.exists() and bolum2.exists())

# --- 1) expand_paths: klasoru videolara acar -------------------------------
print("\n1) _expand_paths: klasor -> video listesi")
expand = getattr(gui, "expand_paths", None)
check("gui.expand_paths tanimli", expand is not None)

if expand is not None:
    found = expand([str(root)], SUPPORTED_EXTENSIONS)
    names = [Path(p).name for p in found]
    check("2 video bulundu", len(found) == 2, str(names))
    check("alt klasor dahil", "2. bölüm.mkv" in names, str(names))
    check(".srt haric", srt.name not in names, str(names))
    check(".txt haric", notlar.name not in names, str(names))
    check("gizli klasor haric", all(".gizli" not in p for p in found), str(found))
    check("mutlak yollar", all(Path(p).is_absolute() for p in found), str(found[:2]))
    check(
        "sirali (deterministik)",
        found == expand([str(root)], SUPPORTED_EXTENSIONS),
        str(names),
    )

    direct = touch("Bolum 9.mp4")
    mixed = expand([str(root), str(direct), str(notlar)], SUPPORTED_EXTENSIONS)
    check("dogrudan dosya da gecer", str(direct) in mixed, str(len(mixed)))
    check("alakasiz dosya elenir", str(notlar) not in mixed)
    check("tekrar yok", len(mixed) == len(set(mixed)), str(mixed))
    check("alt klasordeki dosya dogrudan verilebilir",
          str(bolum2) in expand([str(bolum2)], SUPPORTED_EXTENSIONS))

    check("bos klasor -> bos liste", expand([str(bos_klasor)], SUPPORTED_EXTENSIONS) == [])
    check(
        "video olmayan klasor -> bos liste",
        expand([str(sadece_metin)], SUPPORTED_EXTENSIONS) == [],
    )
    check("olmayan yol -> sessiz", expand([str(WORK / "yok")], SUPPORTED_EXTENSIONS) == [])

# --- 2) _add_to_queue: klasoru kuyruga ekler ------------------------------
print("\n2) _add_to_queue: klasor kuyruga eklenir")
window = gui.MainWindow()
window.queue_table.setRowCount(0)

window._add_to_queue([str(root)])
check("2 satir eklendi", window.queue_table.rowCount() == 2,
      str(window.queue_table.rowCount()))
added = [
    Path(window.queue_table.item(row, 0).data(Qt.UserRole)).name
    for row in range(window.queue_table.rowCount())
]
check("satirlar videolar", sorted(added) == ["1. Bölüm.mp4", "2. bölüm.mkv"], str(added))

print("\n3) Ayni klasoru tekrar birakmak satir cogaltmaz")
window._add_to_queue([str(root)])
check("hala 2 satir", window.queue_table.rowCount() == 2,
      str(window.queue_table.rowCount()))

print("\n4) Karisik birakma: klasor + tek dosya")
before = window.queue_table.rowCount()
window._add_to_queue([str(sadece_metin), str(direct)])
check("yalniz tek dosya eklendi", window.queue_table.rowCount() == before + 1,
      f"{before} -> {window.queue_table.rowCount()}")

print("\n5) Bos klasor geri bildirim verir")
logs: list[str] = []
window._append_log = logs.append
before = window.queue_table.rowCount()
window._add_to_queue([str(sadece_metin)])
check("satir eklenmedi", window.queue_table.rowCount() == before,
      str(window.queue_table.rowCount()))
check("log uyarisi", any("bulunamadı" in line.lower() for line in logs),
      str(logs[-2:]))

# --- 6) DropArea: kuyruk klasor kabul eder, tek video alani etmez ---------
print("\n6) Surukleme: kuyruk klasor kabul eder, tek video etmez")


class FakeDragEvent:
    """Qt olay nesnesi kurmak bu platformda segfault veriyor (0xC0000005).

    DropArea yalnizca `mimeData()`, `acceptProposedAction()` ve `ignore()`
    kullaniyor; bu ucunu taklit etmek karari aynen olcer.
    """

    def __init__(self, paths: list[str]) -> None:
        self._mime = QMimeData()
        self._mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
        self.accepted = False
        self.ignored = False
        self.proposed = False

    def mimeData(self) -> QMimeData:
        return self._mime

    def acceptProposedAction(self) -> None:  # noqa: N802
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True

    def setDropAction(self, action) -> None:  # noqa: N802
        pass


event = FakeDragEvent([str(root)])
window.queue_drop.dragEnterEvent(event)
check("kuyruk alani klasoru kabul etti", event.accepted and not event.ignored,
      f"accepted={event.accepted} ignored={event.ignored}")

event = FakeDragEvent([str(root)])
window.single_drop.dragEnterEvent(event)
check("tek video alani klasoru reddetti", event.ignored and not event.accepted,
      f"accepted={event.accepted} ignored={event.ignored}")

event = FakeDragEvent([str(bolum1)])
window.single_drop.dragEnterEvent(event)
check("tek video alani dosyayi hala kabul ediyor", event.accepted)

# Birakma: sinyal klasor yolunu oldugu gibi yayar (genisletme _add_to_queue'da)
captured: list[list[str]] = []
window.queue_drop.files_dropped.connect(captured.append)
window.queue_drop.dropEvent(FakeDragEvent([str(root)]))
check(
    "sinyal klasor yolunu yaydi",
    bool(captured) and Path(captured[-1][0]) == root,
    str(captured[-1:] if captured else []),
)

event = FakeDragEvent([str(notlar)])
window.queue_drop.dragEnterEvent(event)
check("alakasiz dosya reddedilir", event.ignored and not event.accepted)

window.close()

failed = [label for label, ok, _ in checks if not ok]
print()
if failed:
    print(f"KLASOR TESTI BASARISIZ: {failed}")
    import shutil

    shutil.rmtree(WORK, ignore_errors=True)
    sys.exit(1)
print(f"{len(checks)} kontrol gecti")
print("KLASOR TESTI: GECTI")
