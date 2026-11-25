"""Iptal testi (yeni mimari): is basladiktan sonra iptal eder."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from PySide6.QtCore import QCoreApplication, QTimer  # noqa: E402

import app_paths  # noqa: E402
from ffmpeg_utils import SubtitleStyle  # noqa: E402
from worker import JobSettings, ModelCache, VideoWorker  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
VIDEO = str(PROJECT / "test" / "konusma ingilizce.mp4")

app = QCoreApplication(sys.argv[:1])

settings = JobSettings(
    input_path=VIDEO,
    model_size="tiny",
    target_lang="tr",
    output_mode="burn",
    style=SubtitleStyle(),
    ffmpeg_path=str(PROJECT / "ffmpeg" / "bin" / "ffmpeg.exe"),
    models_dir=str(app_paths.resolve_models_dir()),
    pipeline_mode="off",
)

cache = ModelCache(app_paths.resolve_models_dir(), log_cb=lambda m: None)
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
passed = state["cancelled"] and remaining is False
print(f"[RESULT] cancelled={state['cancelled']} temp_remaining={remaining} ok={state['ok']} error={state['error']}")
print("PASS" if passed else "FAIL")
sys.exit(0 if passed else 1)
