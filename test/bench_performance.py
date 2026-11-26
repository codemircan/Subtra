"""Performans ölçümü: model yükleme, transkripsiyon hızı, bellek."""

import io
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import psutil

import app_paths
import fixtures  # noqa: E402
import ffmpeg_utils as fu
from transcriber import load_whisper_model, transcribe_audio, wav_duration
from translator import NllbTranslator, ensure_nllb_model

PROJECT = Path(__file__).resolve().parent.parent
VIDEO = fixtures.require_video()
WAV = PROJECT / "test" / "_bench.wav"
MODELS = app_paths.resolve_models_dir()

process = psutil.Process()
base_mem = process.memory_info().rss / (1024 ** 2)

print("=" * 74)
print("PERFORMANS ÖLÇÜMÜ")
print("=" * 74)
print(f"Başlangıç bellek: {base_mem:.0f} MB")
cpu = psutil.cpu_count(logical=False), psutil.cpu_count()
ram = psutil.virtual_memory().total / (1024 ** 3)
print(f"Donanım: {cpu[0]} fiziksel / {cpu[1]} mantıksal çekirdek, {ram:.1f} GB RAM")
print()

# Ses çıkar (ölçüm dışı)
if not WAV.exists():
    fu.extract_audio(
        fixtures._ffmpeg(), VIDEO, WAV, 14.6
    )
duration = wav_duration(WAV)
print(f"Test sesi: {duration:.1f} saniye konuşma\n")

results = []

for size in ("tiny", "small"):
    model_dir = MODELS / f"faster-whisper-{size}"
    if not model_dir.exists():
        print(f"[{size}] model yok, atlandı")
        continue

    t0 = time.time()
    model = load_whisper_model(model_dir, cpu_threads=cpu[0])
    load_time = time.time() - t0
    mem_after_load = process.memory_info().rss / (1024 ** 2)

    t0 = time.time()
    meta, segments = transcribe_audio(
        model, WAV, duration, word_timestamps=True, chunk_seconds=600
    )
    transcribe_time = time.time() - t0
    rtf = transcribe_time / duration

    words = sum(len(s["words"]) for s in segments)
    results.append(
        {
            "model": size,
            "load": load_time,
            "transcribe": transcribe_time,
            "rtf": rtf,
            "mem": mem_after_load - base_mem,
            "segments": len(segments),
            "words": words,
        }
    )

    print(f"[{size}]")
    print(f"  Yükleme        : {load_time:6.2f} s")
    print(f"  Transkripsiyon : {transcribe_time:6.2f} s  (RTF {rtf:.2f}×)")
    print(f"  Bellek artışı  : {mem_after_load - base_mem:6.0f} MB")
    print(f"  Segment/kelime : {len(segments)} / {words}")

    del model
    import gc

    gc.collect()

# NLLB
print()
t0 = time.time()
nllb_dir = ensure_nllb_model(MODELS)
translator = NllbTranslator(nllb_dir, intra_threads=cpu[0])
load_time = time.time() - t0
mem_after = process.memory_info().rss / (1024 ** 2)

sentences = [
    "Hello and welcome to this test.",
    "The quick brown fox jumps over the lazy dog.",
    "Machine translation should handle these sentences correctly.",
    "Thank you for watching.",
    "This is a longer sentence that checks how the batch behaves with more text.",
] * 4

t0 = time.time()
translator.translate_batch(sentences, "eng_Latn", "tur_Latn")
translate_time = time.time() - t0

print("[NLLB 600M int8]")
print(f"  Yükleme        : {load_time:6.2f} s")
print(f"  Bellek artışı  : {mem_after - base_mem:6.0f} MB")
print(f"  20 cümle       : {translate_time:6.2f} s  ({translate_time/len(sentences)*1000:.0f} ms/cümle)")

print()
print("=" * 74)
print(f"{'Model':8s} {'Yükleme':>9s} {'RTF':>7s} {'Bellek':>9s}")
print("=" * 74)
for r in results:
    print(f"{r['model']:8s} {r['load']:8.2f}s {r['rtf']:6.2f}× {r['mem']:8.0f} MB")

print()
print("=" * 74)
print("1 SAATLİK VİDEO TAHMİNİ (bu donanımda)")
print("=" * 74)
for r in results:
    hour_transcribe = r["rtf"] * 3600
    translate = 3600 * 1.6 / 1000 * 6  # kaba: 3600s konuşma ≈ 1.6 karakter/s * ...
    print(f"  {r['model']:6s}: transkripsiyon {hour_transcribe/60:5.1f} dk  "
          f"(+ yükleme {r['load']:.0f}s)")
print(f"  NLLB : {translate_time / len(sentences) * 1000:.0f} ms/cümle "
      f"(~{translate_time / len(sentences) * 100:.0f} sn/100 cümle)")

WAV.unlink(missing_ok=True)
