"""BatchWorker kuyruk testi + model yeniden kullanimi."""

import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from PySide6.QtCore import QCoreApplication  # noqa: E402

import app_paths  # noqa: E402
import fixtures  # noqa: E402
from ffmpeg_utils import SubtitleStyle  # noqa: E402
from worker import BatchWorker, JobSettings, ModelCache  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent

VIDEO = str(fixtures.require_video())
models_root = app_paths.resolve_models_dir()
if not (models_root / "faster-whisper-tiny").exists():
    raise SystemExit(fixtures.skip("Whisper 'tiny' modeli indirilmemiş"))

app = QCoreApplication(sys.argv[:1])

jobs = []
for index in range(2):
    jobs.append(
        JobSettings(
            input_path=VIDEO,
            model_size="tiny",
            target_lang="tr" if index == 0 else "en",
            output_mode="srt",
            style=SubtitleStyle(),
            ffmpeg_path=fixtures._ffmpeg() or "",
            models_dir=str(models_root),
            pipeline_mode="off",
        )
    )

cache = ModelCache(models_root, log_cb=lambda m: None)
worker = BatchWorker(jobs, models=cache)

state = {"ok": 0, "failed": 0, "finished": None}
logs = []

worker.log.connect(lambda m: logs.append(m))
worker.item_started.connect(lambda i, p: print(f"[START] {i} {Path(p).name}"))
worker.item_finished.connect(lambda i, v, s, summary: print(f"[OK]    {i} -> {Path(s).name}"))
worker.item_failed.connect(lambda i, m: print(f"[FAIL]  {i}: {m}"))
worker.batch_finished.connect(
    lambda ok, failed, elapsed: (
        state.update(ok=ok, failed=failed, finished=elapsed),
        print(f"[BATCH] ok={ok} failed={failed} time={elapsed}"),
        app.quit(),
    )
)
worker.all_cancelled.connect(lambda: (print("[ALL-CANCELLED]"), app.quit()))

started = time.time()
worker.start()
app.exec()
worker.wait(30000)

print(f"[TOTAL] {time.time()-started:.1f}s")
print("[CACHE]")
for line in logs:
    if "önbellek" in line.lower():
        print("   ", line)

# Kuyrukta modellerin yeniden yuklenmedigi dogrulanir.
reloads = [line for line in logs if "modeli yükleniyor" in line or "modeli hazırlanıyor" in line]
print("Model yukleme sayisi:", len(reloads))
assert state["ok"] == 2, f"iki is de tamamlanmali (ok={state['ok']} failed={state['failed']})"
assert len(reloads) <= 1, f"model birden fazla yuklendi: {reloads}"

# Cikti adlari hedef dile gore ayrilmali (uzerine yazma yok)
tr_out = Path(VIDEO).with_name(Path(VIDEO).stem + "_tr.srt")
en_out = Path(VIDEO).with_name(Path(VIDEO).stem + "_en.srt")
print("TR cikti:", tr_out.exists(), "| EN cikti:", en_out.exists())
assert tr_out.exists() and en_out.exists(), "dil eki ayrimi calismadi"

print("\nKUYRUK TESTI GECTI")
