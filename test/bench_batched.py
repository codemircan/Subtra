"""BatchedInferencePipeline hız kazancını ölçer (mevcut yönteme karşı)."""

import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from faster_whisper import BatchedInferencePipeline, WhisperModel

import app_paths
import fixtures  # noqa: E402
import ffmpeg_utils as fu
from transcriber import load_wav_as_float32, wav_duration

PROJECT = Path(__file__).resolve().parent.parent
VIDEO = fixtures.require_video()
WAV = PROJECT / "test" / "_batch.wav"
MODELS = app_paths.resolve_models_dir()

if not WAV.exists():
    fu.extract_audio(fixtures._ffmpeg(), VIDEO, WAV, 14.6)

duration = wav_duration(WAV)
audio = load_wav_as_float32(WAV)
print(f"Ses: {duration:.1f} s\n")

for size in ("tiny", "small"):
    model_dir = MODELS / f"faster-whisper-{size}"
    if not model_dir.exists():
        continue

    print("=" * 66)
    print(f"[{size}]")
    print("=" * 66)

    # 1) Mevcut yöntem: tek tek, kelime damgalı
    model = WhisperModel(str(model_dir), device="cpu", compute_type="int8", cpu_threads=4)
    t0 = time.time()
    segs, info = model.transcribe(
        audio, language="en", beam_size=5, vad_filter=True,
        word_timestamps=True, condition_on_previous_text=False,
    )
    plain = list(segs)
    t_plain = time.time() - t0
    print(f"  Mevcut (beam=5, kelime damgalı) : {t_plain:6.2f}s  RTF {t_plain/duration:.2f}×")

    # 2) Batch, kelime damgasız
    batch = BatchedInferencePipeline(model=model)
    t0 = time.time()
    segs, info = batch.transcribe(
        audio, language="en", batch_size=8, beam_size=5, vad_filter=True,
        word_timestamps=False,
    )
    out = list(segs)
    t_batch = time.time() - t0
    print(f"  Batch (batch_size=8)            : {t_batch:6.2f}s  RTF {t_batch/duration:.2f}×")

    # 3) Batch, kelime damgalı
    try:
        t0 = time.time()
        segs, info = batch.transcribe(
            audio, language="en", batch_size=8, beam_size=5, vad_filter=True,
            word_timestamps=True,
        )
        out2 = list(segs)
        t_batch_words = time.time() - t0
        print(f"  Batch (kelime damgalı)           : {t_batch_words:6.2f}s  RTF {t_batch_words/duration:.2f}×")
    except Exception as exc:  # noqa: BLE001
        t_batch_words = None
        print(f"  Batch + kelime damgası           : DESTEKLENMİYOR ({type(exc).__name__})")

    # 4) Batch, daha büyük batch
    t0 = time.time()
    segs, info = batch.transcribe(
        audio, language="en", batch_size=16, beam_size=5, vad_filter=True,
        word_timestamps=False,
    )
    list(segs)
    t_big = time.time() - t0
    print(f"  Batch (batch_size=16)           : {t_big:6.2f}s  RTF {t_big/duration:.2f}×")

    speedup = t_plain / t_batch
    print(f"  --> Kazanç (batch_size=8)       : {speedup:.2f}× hızlı")
    print(f"  --> 1 saatlik video tahmini     : {t_plain/duration*60:.0f} dk -> {t_batch/duration*60:.0f} dk")
    print()

    del model, batch
    import gc

    gc.collect()

WAV.unlink(missing_ok=True)
