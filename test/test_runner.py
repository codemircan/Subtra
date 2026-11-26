"""Yeni JobRunner uctan uca testi (GUI yok)."""

import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import app_paths  # noqa: E402
import fixtures  # noqa: E402
from errors import SubtraError  # noqa: E402
from ffmpeg_utils import SubtitleStyle  # noqa: E402
from worker import JobHooks, JobRunner, JobSettings, ModelCache  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent


def run(settings: JobSettings, label: str) -> bool:
    cache = ModelCache(settings.models_dir, log_cb=lambda m: None)
    hooks = JobHooks(
        log=lambda m: print("  LOG ", m),
        stage=lambda t, p: None,
        progress=lambda p: None,
        language=lambda c, n, p: print(f"  DIL  {c}/{n}/%{p*100:.1f}"),
    )
    runner = JobRunner(settings, cache, hooks)
    started = time.time()
    try:
        video, srt, summary = runner.run()
    except SubtraError as exc:
        print(f"  HATA {exc}")
        return False
    finally:
        cache.release_all()
    print(f"  SURE {time.time()-started:.1f}s")
    print("  VIDEO:", video or "-", "| SRT:", srt)
    print("  " + summary.replace("\n", "\n  "))
    print("\n  --- SRT ---")
    for line in Path(srt).read_text(encoding="utf-8").splitlines():
        print("  " + line)
    print(f"\n[{label}] {'PASS' if srt else 'FAIL'}\n")
    return bool(srt)


def base(mode: str, **kwargs) -> JobSettings:
    cfg = dict(
        input_path=str(VIDEO),
        model_size="tiny",
        target_lang="tr",
        output_mode=mode,
        style=SubtitleStyle(font_size=20),
        ffmpeg_path=fixtures._ffmpeg() or "",
        models_dir=str(app_paths.resolve_models_dir()),
    )
    cfg.update(kwargs)
    return JobSettings(**cfg)


# --- Fixture ve model kontrolü -------------------------------------------
VIDEO = fixtures.require_video()

models_root = app_paths.resolve_models_dir()
if not (models_root / "faster-whisper-tiny").exists():
    raise SystemExit(fixtures.skip("Whisper 'tiny' modeli indirilmemiş"))
if not (models_root / "nllb-200-distilled-600M-ct2-int8").exists():
    raise SystemExit(fixtures.skip("NLLB çeviri modeli indirilmemiş"))

results = {}

print("=== 1) sadece SRT, ceviri acik, pipeline kapali ===")
results["srt"] = run(base("srt", pipeline_mode="off"), "srt")

print("=== 2) burn-in ===")
results["burn"] = run(base("burn", pipeline_mode="off"), "burn")

print("=== 3) pipeline acik (zorlanmis) ===")
results["pipeline"] = run(base("srt", pipeline_mode="on"), "pipeline")

srt_path = VIDEO.with_name(VIDEO.stem + "_tr.srt")
if not srt_path.exists():
    srt_path = fixtures.require_srt()
print("=== 4) SRT ice aktarma (transkripsiyon atlanir) ===")
results["import"] = run(
    base("srt", input_path="", input_srt=str(srt_path), source_lang="en", pipeline_mode="off"),
    "import",
)

# Cikti adi kaynak dosyanin uzerine yazmamali (veri kaybi guard'i).
# konusma ingilizce_tr.srt -> tr icin cikti konusma ingilizce_tr_2.srt olur.
collision_guard = srt_path.with_name(srt_path.stem + "_2.srt")
safe = collision_guard.exists() or not srt_path.exists()
print(f"  Kaynak korundu / cakisma guard'i: {safe} ({collision_guard.name})")
results["isim"] = safe

print("\nSONUC:", results)
sys.exit(0 if all(results.values()) else 1)
