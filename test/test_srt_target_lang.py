"""SRT sekmesi hedef dil bagimsizligi + coklu dil arayuz testi."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import logging_setup  # noqa: E402
import fixtures  # noqa: E402
from gui import MainWindow  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
# Kendi fixture'ini kullan (baska testin ciktisina bagimli olmasin)
EN_SRT = fixtures.require_srt()

import app_paths  # noqa: E402

_models = app_paths.resolve_models_dir()
if not (_models / "nllb-200-distilled-600M-ct2-int8").exists():
    raise SystemExit(fixtures.skip("NLLB çeviri modeli indirilmemiş"))

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
    window.resize(960, 900)
    window.show()
    window._refresh_ffmpeg_status(silent=True)
    window.model_combo.setCurrentIndex(window.model_combo.findData("tiny"))
    window.pipeline_combo.setCurrentIndex(window.pipeline_combo.findData("off"))

    checks = {}

    # Video sekmesi hedef dil: Turkce
    window.target_combo.setCurrentIndex(window.target_combo.findData("tr"))
    video_target = window.target_combo.currentData()

    # SRT sekmesi hedef dil: Almanca (bagimsiz olmali)
    window.tabs.setCurrentIndex(2)
    window.srt_target_combo.setCurrentIndex(window.srt_target_combo.findData("de"))
    srt_target = window.srt_target_combo.currentData()

    checks["video_tr"] = video_target == "tr"
    checks["srt_de"] = srt_target == "de"
    checks["bagimsiz"] = video_target != srt_target
    print(f"Video hedef: {video_target} | SRT hedef: {srt_target} | bagimsiz={checks['bagimsiz']}")

    # SRT isini baslat -> Almanca cikti bekleniyor
    window._set_srt_input(str(EN_SRT))
    window.srt_lang_combo.setCurrentIndex(window.srt_lang_combo.findData("en"))
    window.srt_output_combo.setCurrentIndex(window.srt_output_combo.findData("srt"))

    state = {}

    def on_done(video: str, srt: str, summary: str) -> None:
        state["srt"] = srt
        state["summary"] = summary
        QTimer.singleShot(150, finish)

    def finish() -> None:
        path = Path(state.get("srt", ""))
        checks["cikti_var"] = path.exists()
        checks["almanca_ad"] = path.name.endswith("_de.srt")
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        checks["almanca_icerik"] = "Hallo" in text or "Untertitelsystem" in text
        print("\nCikti:", path.name)
        print("Ozet:", state.get("summary", "").replace("\n", " | "))

        # Video sekmesi hedefi degismedi mi?
        window.tabs.setCurrentIndex(0)
        checks["video_degismedi"] = window.target_combo.currentData() == "tr"
        print("Video hedef (sonra):", window.target_combo.currentData())

        window.close()
        app.quit()

    window._start_srt()
    if window._worker is not None:
        window._worker.finished_ok.connect(on_done)

    QTimer.singleShot(120000, app.quit)
    app.exec()

    print("\n" + "=" * 60)
    for name, ok in checks.items():
        print(f"  {'OK  ' if ok else 'FAIL'} {name}")
    passed = all(checks.values())
    print("\n" + ("SRT HEDEF DIL TESTI GECTI" if passed else "TEST BASARISIZ"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
