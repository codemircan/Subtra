"""Transkripsiyon + cumle callback testi."""

import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import app_paths  # noqa: E402
import ffmpeg_utils as fu  # noqa: E402
import fixtures  # noqa: E402
from transcriber import load_whisper_model, transcribe_audio  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
root = app_paths.resolve_models_dir()
print("models:", root)

if not (root / "faster-whisper-tiny").exists():
    raise SystemExit(fixtures.skip("Whisper 'tiny' modeli indirilmemiş"))

VIDEO = fixtures.require_video()
duration = fu.media_duration(fixtures._ffprobe(), VIDEO)

ffmpeg = fixtures._ffmpeg()
wav = str(PROJECT / "test" / "_t.wav")
fu.extract_audio(ffmpeg, str(VIDEO), wav, duration)

model = load_whisper_model(root / "faster-whisper-tiny", cpu_threads=2)

sentences = []
meta, segments = transcribe_audio(model, wav, duration, sentence_cb=sentences.append)

print("dil:", meta["language"], round(meta["language_probability"], 3))
print("segment:", len(segments), "kelime:", sum(len(s["words"]) for s in segments))
print("cumle callback:", len(sentences))
for sentence in sentences:
    print(f"   [{sentence['start']:.2f}-{sentence['end']:.2f}] {sentence['text']}")

os.remove(wav)

# Kucuk dilimleme testi: 5 saniyelik dilimlerle ayni metni vermeli
print("\nKucuk dilim (5 sn) ile tekrar:")
wav2 = str(PROJECT / "test" / "_t2.wav")
fu.extract_audio(ffmpeg, str(VIDEO), wav2, duration)
meta2, segs2 = transcribe_audio(model, wav2, duration, chunk_seconds=5.0)
print("dil:", meta2["language"], "segment:", len(segs2))
combined = " ".join(
    " ".join(w["text"] for w in s["words"]) if s["words"] else s["text"] for s in segs2
)
print("metin:", combined)
os.remove(wav2)

assert meta["language"] == "en", f"dil tespiti yanlis: {meta['language']}"
assert "quick brown fox" in combined.lower(), "dilimleme metni bozdu"
assert combined.lower().count("machine") <= 1, "kelime tekrarı temizlenmedi"
assert combined.lower().count("thank") <= 2, "kelime tekrarı temizlenmedi"
assert len(sentences) >= 2, "cumle callback calismadi"
print("\nTRANSKRIPSİYON TESTLERİ GEÇTI")
