"""P1 testleri: transkript önbelleği, batch, kuyrukta dosya başına dil.

Ölçüm: aynı video ikinci dile çevrildiğinde Whisper atlanıyor mu?
"""

import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import app_paths  # noqa: E402
import fixtures  # noqa: E402
import transcript_cache  # noqa: E402
from ffmpeg_utils import SubtitleStyle  # noqa: E402
from worker import JobHooks, JobRunner, JobSettings, ModelCache  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
VIDEO = fixtures.require_video()
models_root = app_paths.resolve_models_dir()

for needed, label in (
    ("faster-whisper-tiny", "Whisper tiny"),
    ("nllb-200-distilled-600M-ct2-int8", "NLLB"),
):
    if not (models_root / needed).exists():
        raise SystemExit(fixtures.skip(f"{label} modeli indirilmemiş"))

checks = []


def check(label, ok, detail=""):
    checks.append((label, ok))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


def run(target: str, batch: int = 0, cache: bool = True, tag: str = "") -> dict:
    settings = JobSettings(
        input_path=str(VIDEO),
        model_size="tiny",
        target_lang=target,
        output_mode="srt",
        style=SubtitleStyle(),
        ffmpeg_path=fixtures._ffmpeg() or "",
        models_dir=str(models_root),
        pipeline_mode="off",
        batch_size=batch,
        use_transcript_cache=cache,
    )
    logs: list[str] = []
    hooks = JobHooks(log=logs.append)
    cache_obj = ModelCache(models_root, log_cb=lambda m: None)
    runner = JobRunner(settings, cache_obj, hooks)
    started = time.time()
    try:
        _, srt, _ = runner.run()
    finally:
        cache_obj.release_all()
    elapsed = time.time() - started
    return {"srt": srt, "logs": logs, "elapsed": elapsed, "tag": tag}


print("=" * 70)
print("1) Transkript önbelleği — soğuk çalıştırma")
print("=" * 70)
transcript_cache.clear(app_paths.transcripts_dir())

cold = run("tr", tag="cold")
check("çıktı üretildi", Path(cold["srt"]).exists())
check(
    "önbelleğe yazıldı",
    any("önbelleğe yazıldı" in line for line in cold["logs"]),
    f"{cold['elapsed']:.1f}s",
)
check(
    "transkripsiyon yapıldı (önbellek yoktu)",
    any("Konuşma metne çevriliyor" in line or "Transkripsiyon tamamlandı" in line
        for line in cold["logs"]),
)
files = list(app_paths.transcripts_dir().glob("*.json"))
check("disk üzerinde 1 kayıt", len(files) == 1, f"{len(files)} dosya")

print("\n" + "=" * 70)
print("2) Aynı video, FARKLI hedef dil (de) — Whisper atlanmalı")
print("=" * 70)
warm = run("de", tag="warm")
cache_hit = any("önbellekten alındı" in line for line in warm["logs"])
check("önbellekten alındı", cache_hit)
check(
    "Whisper transkripsiyonu ATLANDI",
    not any("Transkripsiyon tamamlandı" in line for line in warm["logs"]),
)
check("Almanca çıktı üretildi", Path(warm["srt"]).name.endswith("_de.srt"), Path(warm["srt"]).name)
speedup = cold["elapsed"] / warm["elapsed"] if warm["elapsed"] else 0
print(f"   soğuk: {cold['elapsed']:.1f}s | sıcak: {warm['elapsed']:.1f}s | hızlanma: {speedup:.2f}×")
check("sıcak çalıştırma daha hızlı", warm["elapsed"] < cold["elapsed"], f"{speedup:.2f}×")

if cache_hit:
    for line in warm["logs"]:
        if "önbellekten alındı" in line:
            print(f"   LOG: {line}")

print("\n" + "=" * 70)
print("3) Önbellek devre dışı — Whisper yeniden çalışmalı")
print("=" * 70)
nocache = run("fr", cache=False, tag="nocache")
check(
    "transkripsiyon yeniden yapıldı",
    any("Transkripsiyon tamamlandı" in line for line in nocache["logs"]),
)

print("\n" + "=" * 70)
print("4) Dosya değişince önbellek geçersizleşmeli")
print("=" * 70)
import shutil
import os

copy = PROJECT / "test" / "_cache_probe.mp4"
shutil.copy2(VIDEO, copy)
k1 = transcript_cache.cache_key(copy, "tiny", True)
# Boyutu değiştir (sonuna bayt ekle) -> mtime + size değişir
with open(copy, "ab") as handle:
    handle.write(b"\x00" * 2048)
os.utime(copy, None)
k2 = transcript_cache.cache_key(copy, "tiny", True)
check("anahtar dosya değişince farklı", k1 != k2, f"{k1[:8]} vs {k2[:8]}")
copy.unlink(missing_ok=True)

print("\n" + "=" * 70)
print("5) Model boyutu anahtarda — farklı model farklı önbellek")
print("=" * 70)
k_tiny = transcript_cache.cache_key(VIDEO, "tiny", True)
k_small = transcript_cache.cache_key(VIDEO, "small", True)
k_nowt = transcript_cache.cache_key(VIDEO, "tiny", False)
check("model boyutu anahtarda", k_tiny != k_small)
check("kelime damgası anahtarda", k_tiny != k_nowt)

print("\n" + "=" * 70)
print("6) Batch modu transkripsiyon (batch_size=8)")
print("=" * 70)
transcript_cache.clear(app_paths.transcripts_dir())
batched = run("es", batch=8, tag="batch")
check("batch ile çıktı üretildi", Path(batched["srt"]).exists())
srt_text = Path(batched["srt"]).read_text(encoding="utf-8")
check("içerik boş değil", len(srt_text) > 50, f"{len(srt_text)} karakter")
first = [line for line in srt_text.splitlines() if line and "-->" not in line and not line.isdigit()]
print(f"   ilk satır: {first[0] if first else '(boş)'}")
check("İspanyolca metin var", bool(first), first[0][:50] if first else "")

print("\n" + "=" * 70)
print("7) Batch anahtarı ayrı (aynı video, farklı batch)")
print("=" * 70)
k_plain = transcript_cache.cache_key(VIDEO, "tiny", True, extra="plain")
k_batch = transcript_cache.cache_key(VIDEO, "tiny", True, extra="batch")
check("batch/plain anahtarları ayrı", k_plain != k_batch)

failed = [label for label, ok in checks if not ok]
print("\n" + "=" * 70)
print(f"{len(checks) - len(failed)}/{len(checks)} kontrol geçti")
print("P1 TESTİ: " + ("GEÇTİ" if not failed else f"BAŞARISIZ -> {failed}"))
sys.exit(0 if not failed else 1)
