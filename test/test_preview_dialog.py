"""Önizleme diyaloğu testi — modal kutular tamamen devre dışı."""

import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

# QApplication'dan ÖNCE hiçbir modal kutu açılmasın: modül seviyesinde
# QMessageBox'un statik metodlarını no-op ile değiştir.
import PySide6.QtWidgets as QtWidgets  # noqa: E402

_YES = QtWidgets.QMessageBox.Yes
_OK = QtWidgets.QMessageBox.Ok

QtWidgets.QMessageBox.exec = lambda self: 0
QtWidgets.QMessageBox.clickedButton = lambda self: None
QtWidgets.QMessageBox.information = staticmethod(lambda *a, **k: _OK)
QtWidgets.QMessageBox.warning = staticmethod(lambda *a, **k: _OK)
QtWidgets.QMessageBox.critical = staticmethod(lambda *a, **k: _OK)
QtWidgets.QMessageBox.question = staticmethod(lambda *a, **k: _YES)

app = QApplication(sys.argv[:1])

from subtitle_preview import SubtitlePreviewDialog, parse_srt_text  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
WORK = PROJECT / "test" / "_preview"
WORK.mkdir(parents=True, exist_ok=True)

checks = []


def check(label, ok, detail=""):
    checks.append((label, ok))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


VALID_SRT = (
    "1\n00:00:01,000 --> 00:00:02,500\nMerhaba dünya\n\n"
    "2\n00:00:03,000 --> 00:00:05,000\nİkinci satır\n"
)


def make_srt(name="preview.srt", text=VALID_SRT) -> Path:
    path = WORK / name
    path.write_text(text, encoding="utf-8")
    return path


print("=" * 66)
print("1) SRT ayrıştırma")
print("=" * 66)
entries = parse_srt_text(VALID_SRT)
check("2 girdi", len(entries) == 2, str(len(entries)))
check("zamanlar doğru", entries[0]["start"] == 1.0 and entries[0]["end"] == 2.5)
check("bozuk metin -> boş", parse_srt_text("zaman yok") == [])

print("\n" + "=" * 66)
print("2) Diyalog + içerik")
print("=" * 66)
srt = make_srt()
dialog = SubtitlePreviewDialog(srt, "Test özeti | 2 satır")
app.processEvents()
check("editör içeriği", "Merhaba dünya" in dialog.editor.toPlainText())
check("başlangıçta değişiklik yok", not dialog._edited)
check("Uygula pasif", not dialog.apply_button.isEnabled())

print("\n" + "=" * 66)
print("3) Düzenleme + uygulama")
print("=" * 66)
dialog.editor.setPlainText(VALID_SRT.replace("Merhaba dünya", "Selam dünya"))
app.processEvents()
check("değişiklik algılandı", dialog._edited)
check("Uygula aktif", dialog.apply_button.isEnabled())
dialog._apply()
app.processEvents()
disk = srt.read_text(encoding="utf-8")
check("diske yazıldı", "Selam dünya" in disk)
check("bayrak temiz", not dialog._edited)

print("\n" + "=" * 66)
print("4) Geçersiz düzenleme reddedilir")
print("=" * 66)
dialog.editor.setPlainText("zaman damgası yok")
app.processEvents()
ok, message = dialog._validate(dialog._current_text())
check("geçersiz yakalandı", not ok)
print(f"   mesaj: {message.splitlines()[0]}")
dialog._apply()
disk_after = srt.read_text(encoding="utf-8")
check("geçersiz yazılmadı", "Selam dünya" in disk_after)

print("\n" + "=" * 66)
print("5) Özgün metne dön")
print("=" * 66)
dialog._revert()
app.processEvents()
check("özgün içerik", "Selam dünya" in dialog.editor.toPlainText())
check("bayrak temiz", not dialog._edited)

print("\n" + "=" * 66)
print("6) 'Yalnızca .srt' seçimi")
print("=" * 66)
dialog.only_srt_check.setChecked(True)
dialog._accept()
app.processEvents()
check("skip_video=True", dialog.skip_video is True)
check("kabul edildi", dialog.result() == QDialog.DialogCode.Accepted)

print("\n" + "=" * 66)
print("7) 'Bir daha sorma'")
print("=" * 66)
dialog2 = SubtitlePreviewDialog(make_srt("preview2.srt"))
dialog2.dont_ask_check.setChecked(True)
dialog2._accept()
app.processEvents()
check("dont_ask_again=True", dialog2.dont_ask_again is True)

print("\n" + "=" * 66)
print("8) Vazgeç")
print("=" * 66)
dialog3 = SubtitlePreviewDialog(make_srt("preview3.srt"))
dialog3.reject()
app.processEvents()
check("Rejected", dialog3.result() == QDialog.DialogCode.Rejected)

import shutil

shutil.rmtree(WORK, ignore_errors=True)

failed = [label for label, ok in checks if not ok]
print("\n" + "=" * 66)
print(f"{len(checks) - len(failed)}/{len(checks)} kontrol geçti")
print("ÖNİZLEME TESTİ: " + ("GEÇTİ" if not failed else f"BAŞARISIZ -> {failed}"))
sys.exit(0 if not failed else 1)
