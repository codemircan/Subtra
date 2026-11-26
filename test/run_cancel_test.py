"""Iptal testi (yeni mimari): is basladiktan sonra iptal eder."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from PySide6.QtCore import QCoreApplication, QTimer  # noqa: E402

import app_paths  # noqa: E402
import fixtures  # noqa: E402
from ffmpeg_utils import SubtitleStyle  # noqa: E402
from worker import JobSettings, ModelCache, VideoWorker  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent

VIDEO = str(fixtures.require_video())
models_root = app_paths.resolve_models_dir()
if not (models_root / "faster-whisper-tiny").exists():
    raise SystemExit(fixtures.skip("Whisper 'tiny' modeli indirilmemiş"))

app = QCoreApplication(sys.argv[:1])

settings = JobSettings(
    input_path=VIDEO,
    model_size="tiny",
    target_lang="tr",
    output_mode="burn",
    style=SubtitleStyle(),
    ffmpeg_path=fixtures._ffmpeg() or "",
    models_dir=str(models_root),
    pipeline_mode="off",
    # Önbellek KAPALI: iptal testi gerçek transkripsiyon akışını ölçmeli.
    # Önbellek isabet ederse iptal edilecek iş kalmaz ve geçici klasör oluşmaz.
    use_transcript_cache=False,
)

cache = ModelCache(models_root, log_cb=lambda m: None)
worker = VideoWorker(settings, models=cache)

state = {"cancelled": False, "error": None, "ok": False, "temp": None}
delay = int(sys.argv[1]) if len(sys.argv) > 1 else 2500


def on_log(message: str) -> None:
    print("[LOG]", message)
    if "Geçici klasör" in message:
        state["temp"] = message.split(":", 1)[1].strip()


worker.log.connect(on_log)
worker.finished_ok.connect(lambda v, s, m: (state.update(ok=True), print("[OK-UNEXPECTED]"), app.quit()))
worker.failed.connect(lambda m: (state.update(error=m), print("[FAIL]", m), app.quit()))
worker.cancelled.connect(lambda: (state.update(cancelled=True), print("[CANCELLED]"), app.quit()))

worker.start()
QTimer.singleShot(delay, worker.cancel)
QTimer.singleShot(delay + 90000, app.quit)
app.exec()
worker.wait(40000)

temp_path = state["temp"]
remaining = Path(temp_path).exists() if temp_path else None
# remaining: False = silindi (doğru), None = temp hiç oluşmadı (önbellek isabeti)
passed = state["cancelled"] and remaining is not True
print(f"[RESULT] cancelled={state['cancelled']} temp_remaining={remaining} ok={state['ok']} error={state['error']}")
print("PASS" if passed else "FAIL")
sys.exit(0 if passed else 1)
