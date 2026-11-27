"""Terim sozlugu arayuz testi — modal kutular devre disi, offscreen Qt."""

import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication  # noqa: E402
import PySide6.QtWidgets as QtWidgets  # noqa: E402

QtWidgets.QMessageBox.exec = lambda self: 0
QtWidgets.QMessageBox.information = staticmethod(lambda *a, **k: None)
QtWidgets.QMessageBox.warning = staticmethod(lambda *a, **k: None)
QtWidgets.QMessageBox.critical = staticmethod(lambda *a, **k: None)

app = QApplication(sys.argv[:1])

from gui import MainWindow  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
SAMPLE = PROJECT / "docs" / "glossary-ornek.tsv"
WORK = PROJECT / "test" / "_glossary_ui"
WORK.mkdir(parents=True, exist_ok=True)

checks = []


def check(label, ok, detail=""):
    checks.append((label, ok))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


print("=" * 66)
print("TERIM SOZLUGU ARAYUZU")
print("=" * 66)

window = MainWindow()
previous = window._settings.value("glossary_path", "", str) or ""

# --- 1) Gecerli sozluk -----------------------------------------------------
print("\n1) Gecerli sozluk secimi")
ok = window._set_glossary(str(SAMPLE))
check("kabul edildi", ok)
check("yol kaydedildi", window._glossary_path == str(SAMPLE), window._glossary_path)
check("etiket terim sayisi", "terim" in window.glossary_label.text(), window.glossary_label.text())

settings = window._base_settings(input_path="x.mp4")
check("JobSettings tasiyor", settings.glossary_path == str(SAMPLE), settings.glossary_path)

window._save_settings()
check("QSettings kalici", window._settings.value("glossary_path", "", str) == str(SAMPLE))

# --- 2) Bozuk sozluk reddedilir -------------------------------------------
print("\n2) Bozuk sozluk reddedilir")
bad = WORK / "bozuk.tsv"
bad.write_text("tek_sutun\n", encoding="utf-8")
ok = window._set_glossary(str(bad))
check("reddedildi", ok is False)
check("yol temizlendi", window._glossary_path == "", window._glossary_path)
check("JobSettings bos", window._base_settings(input_path="x.mp4").glossary_path == "")

# --- 3) Kaldirma -----------------------------------------------------------
print("\n3) Kaldirma")
window._set_glossary(str(SAMPLE))
window._clear_glossary()
check("yol bos", window._glossary_path == "")
check("etiket kapali", "Kapal" in window.glossary_label.text(), window.glossary_label.text())
check("QSettings bos", window._settings.value("glossary_path", "", str) == "")

# --- 4) Silinmis dosya acilista temizlenir --------------------------------
print("\n4) Silinmis dosya")
gone = WORK / "silinmis.tsv"
gone.write_text("a\tb\n", encoding="utf-8")
window._settings.setValue("glossary_path", str(gone))
gone.unlink()
window2 = MainWindow()
check("acilista yol bos", window2._glossary_path == "", window2._glossary_path)
check("acilista etiket kapali", "Kapal" in window2.glossary_label.text())
window2.close()

# eski ayari geri koy
window._settings.setValue("glossary_path", previous)
window.close()

failed = [label for label, ok in checks if not ok]
print()
if failed:
    print(f"SOZLUK ARAYUZU BASARISIZ: {failed}")
    sys.exit(1)
print(f"{len(checks)} kontrol gecti")
print("SOZLUK ARAYUZU: GECTI")
