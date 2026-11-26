"""Kuyrukta dosya başına hedef dil testi (arayüz üzerinden)."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import app_paths  # noqa: E402
import fixtures  # noqa: E402
import logging_setup  # noqa: E402
from gui import MainWindow  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
VIDEO = str(fixtures.require_video())
models_root = app_paths.resolve_models_dir()
if not (models_root / "faster-whisper-tiny").exists():
    raise SystemExit(fixtures.skip("Whisper 'tiny' modeli indirilmemiş"))

checks = []


def check(label, ok, detail=""):
    checks.append((label, ok))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


def patch_dialogs():
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
    QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Ok)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    QMessageBox.exec = lambda self: 0
    QMessageBox.clickedButton = lambda self: None


def main() -> int:
    logging_setup.setup_logging()
    app = QApplication(sys.argv[:1])
    patch_dialogs()

    window = MainWindow()
    window.resize(1000, 900)
    window.show()
    window._refresh_ffmpeg_status(silent=True)
    window.model_combo.setCurrentIndex(window.model_combo.findData("tiny"))
    window.pipeline_combo.setCurrentIndex(window.pipeline_combo.findData("off"))
    window.radio_srt.setChecked(True)
    window.batch_spin.setValue(0)
    window.cache_check.setChecked(True)
    window._save_settings()

    print("=" * 70)
    print("1) Kuyruk tablosu yapısı")
    print("=" * 70)
    check("4 sütun (Dosya / Hedef dil / Durum / Çıktı)", window.queue_table.columnCount() == 4)

    print("\n" + "=" * 70)
    print("2) Aynı video 3 kez, 3 farklı dil")
    print("=" * 70)
    window.tabs.setCurrentIndex(1)
    window.target_combo.setCurrentIndex(window.target_combo.findData("tr"))
    window._add_to_queue([VIDEO])
    window._add_to_queue([VIDEO])  # aynı yol: eklenmez (tekrar koruması)
    check("aynı yol iki kez eklenmiyor", window.queue_table.rowCount() == 1)

    # Satırı klonla: aynı dosya farklı dille (gerçek kullanımda farklı dosyalar)
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTableWidgetItem

    for code in ("de", "fr"):
        row = window.queue_table.rowCount()
        window.queue_table.insertRow(row)
        item = window.queue_table.item(0, 0)
        clone = QTableWidgetItem(item.text())
        clone.setData(Qt.UserRole, item.data(Qt.UserRole))
        window.queue_table.setItem(row, 0, clone)
        window.queue_table.setItem(row, 1, window._target_item(code))
        window.queue_table.setItem(row, 2, QTableWidgetItem("Bekliyor"))
        window.queue_table.setItem(row, 3, QTableWidgetItem("—"))

    check("3 satır var", window.queue_table.rowCount() == 3)
    targets = [window._queue_target(row) for row in range(3)]
    print(f"   hedef diller: {targets}")
    check("satır bazında farklı diller", targets == ["tr", "de", "fr"], str(targets))

    jobs = window._queue_jobs()
    check("_queue_jobs 3 iş üretiyor", len(jobs) == 3)
    check(
        "her iş kendi hedef dilini taşıyor",
        [job.target_lang for job in jobs] == ["tr", "de", "fr"],
        str([job.target_lang for job in jobs]),
    )
    print(f"   çıktı adları: {[job.output_base().name for job in jobs]}")
    check(
        "çıktı adları çakışmıyor",
        len({job.output_base().name for job in jobs}) == 3,
    )

    print("\n" + "=" * 70)
    print("3) Toplu dil uygulama")
    print("=" * 70)
    window.queue_target_combo.setCurrentIndex(window.queue_target_combo.findData("ja"))
    window._apply_queue_target_all()
    applied = [window._queue_target(row) for row in range(3)]
    check("tümü Japonca", applied == ["ja", "ja", "ja"], str(applied))
    print(f"   {window.queue_summary.text()}")

    # Geri al
    for row, code in enumerate(("tr", "de", "fr")):
        window.queue_table.setItem(row, 1, window._target_item(code))

    print("\n" + "=" * 70)
    print("4) Kuyruk gerçekten çalışıyor (3 dil, transkript 1 kez)")
    print("=" * 70)
    import transcript_cache

    transcript_cache.clear(app_paths.transcripts_dir())

    result = {}

    def on_batch(ok, failed, elapsed):
        result["ok"] = ok
        result["failed"] = failed
        result["elapsed"] = elapsed
        print(f"   [BATCH] ok={ok} failed={failed} süre={elapsed}")
        QTimer.singleShot(300, finish)

    def finish():
        outputs = []
        for row in range(window.queue_table.rowCount()):
            item = window.queue_table.item(row, 3)
            outputs.append(item.text() if item else "?")
        statuses = [window.queue_table.item(row, 2).text() for row in range(3)]
        print(f"   durumlar: {statuses}")
        print(f"   çıktılar: {outputs}")
        check("3 iş de tamamlandı", result.get("ok") == 3, str(result))
        check("hata yok", result.get("failed") == 0)
        expected = ["_tr.srt", "_de.srt", "_fr.srt"]
        check(
            "her dil ayrı dosya",
            all(any(exp in out for exp in expected[i:i + 1]) for i, out in enumerate(outputs)),
            str(outputs),
        )
        files = list(app_paths.transcripts_dir().glob("*.json"))
        check("transkript tek kez çıkarıldı (1 önbellek kaydı)", len(files) == 1, f"{len(files)}")
        # loglarda 1 transkripsiyon, 2 önbellek isabeti olmalı
        window.close()
        app.quit()

    window._start_queue()
    assert window._batch is not None, "kuyruk başlamadı"
    window._batch.batch_finished.connect(on_batch)
    QTimer.singleShot(600000, app.quit)

    app.exec()

    failed = [label for label, ok in checks if not ok]
    print("\n" + "=" * 70)
    print(f"{len(checks) - len(failed)}/{len(checks)} kontrol geçti")
    print("KUYRUK / DİL TESTİ: " + ("GEÇTİ" if not failed else f"BAŞARISIZ -> {failed}"))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
