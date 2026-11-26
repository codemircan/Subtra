"""Arayuz uzerinden kuyruk ve SRT akisi testi (gercek butonlar)."""

import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import app_paths  # noqa: E402
import logging_setup  # noqa: E402
import fixtures  # noqa: E402
from gui import MainWindow  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
VIDEO = str(fixtures.require_video())
_models = app_paths.resolve_models_dir()
if not (_models / "faster-whisper-tiny").exists():
    raise SystemExit(fixtures.skip("Whisper 'tiny' modeli indirilmemiş"))
STATE = {"done": False, "ok": 0, "failed": 0, "error": None}


def patch_dialogs() -> None:
    """Otomatik testte modal pencereleri kapat."""
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
    window.resize(960, 900)
    window.show()
    window._refresh_ffmpeg_status(silent=True)
    window._save_settings()

    # Hizli test ayarlari
    window.model_combo.setCurrentIndex(window.model_combo.findData("tiny"))
    for combo, value in ((window.target_combo, ""),):
        pass
    index = window.target_combo.findData("tr")
    window.target_combo.setCurrentIndex(index)
    window.radio_srt.setChecked(True)
    window.pipeline_combo.setCurrentIndex(window.pipeline_combo.findData("off"))
    window.cps_spin.setValue(18)

    result: dict = {}

    def step_queue() -> None:
        window.tabs.setCurrentIndex(1)
        window._add_to_queue([VIDEO])
        print("Kuyruk satir sayisi:", window.queue_table.rowCount())
        assert window.queue_table.rowCount() == 1, "kuyruga eklenemedi"
        window._batch_finished_hook = True
        window._start_queue()
        assert window._batch is not None, "batch baslamadi"
        window._batch.batch_finished.connect(on_batch)

    def on_batch(ok: int, failed: int, elapsed: str) -> None:
        result["queue"] = (ok, failed)
        print(f"[QUEUE] ok={ok} failed={failed} time={elapsed}")
        QTimer.singleShot(200, step_srt)

    def step_srt() -> None:
        # Kuyruk durumunu kontrol et (sütun 2 = Durum, sütun 1 artık hedef dil)
        status = window.queue_table.item(0, 2).text()
        print("Kuyruk durumu:", status)
        assert status == "Tamamlandı", f"beklenmeyen durum: {status}"

        window.tabs.setCurrentIndex(2)
        srt = Path(VIDEO).with_name(Path(VIDEO).stem + "_tr.srt")
        if not srt.exists():
            srt = fixtures.require_srt()
        window._set_srt_input(str(srt))
        window.srt_lang_combo.setCurrentIndex(window.srt_lang_combo.findData("en"))
        window.radio_srt.setChecked(True)
        window._start_srt()
        assert window._worker is not None, "srt isi baslamadi"
        window._worker.finished_ok.connect(on_srt)

    def on_srt(video: str, srt_path: str, summary: str) -> None:
        result["srt"] = srt_path
        print("[SRT-OK]", Path(srt_path).name)
        QTimer.singleShot(200, finish)

    def finish() -> None:
        STATE["done"] = True
        print("\nOZET:", result)
        window.close()
        app.quit()

    QTimer.singleShot(800, step_queue)
    QTimer.singleShot(180000, lambda: (print("[TIMEOUT]"), app.quit()))

    app.exec()
    ok = result.get("queue", (0, 1))[0] == 1 and "srt" in result
    print("ARAYUZ AKIS TESTI:", "GECTI" if ok else "BASARISIZ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
