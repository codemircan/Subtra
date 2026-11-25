"""FFmpeg otomatik indirme testi (temiz veri klasoru)."""

import io
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

temp_root = Path(tempfile.mkdtemp(prefix="vc_test_"))
os.environ["VIDEOCEVIRI_DATA_DIR"] = str(temp_root)
print("Test veri klasörü:", temp_root)

import app_paths  # noqa: E402
import ffmpeg_bootstrap  # noqa: E402

print("Veri klasörü:", app_paths.data_dir())
print("FFmpeg hedef:", app_paths.ffmpeg_dir())

# Proje/uygulama klasorundeki hazir FFmpeg'i test sirasinda gizle;
# boylece gercek indirme yolu denenir.
_real_candidates = ffmpeg_bootstrap._candidate_dirs


def _patched(explicit):
    items = []
    for label, directory in _real_candidates(explicit):
        if label in ("gömülü", "uygulama klasörü", "PATH"):
            continue
        items.append((label, directory))
    return items


ffmpeg_bootstrap._candidate_dirs = _patched

existing = ffmpeg_bootstrap.find_existing()
print("Mevcut bulunan:", existing.source if existing else "yok (beklenen)")

started = time.time()
last = {"pct": -1, "label": ""}


def on_progress(fraction, label):
    pct = int(fraction * 100)
    if pct >= last["pct"] + 5 or label != last["label"]:
        print(f"  %{pct:3d} {label}")
        last["pct"] = pct
        last["label"] = label


location = ffmpeg_bootstrap.download_ffmpeg(progress_cb=on_progress, log_cb=lambda m: print("  LOG", m))

print(f"Süre: {time.time()-started:.1f}s")
print("İndirilen:", location.ffmpeg)
print("Kaynak:", location.source)
print("Dosya var mı:", Path(location.ffmpeg).exists())
print("Boyut MB:", round(Path(location.ffmpeg).stat().st_size / (1024**2), 1))
print("ffprobe var mı:", Path(location.ffprobe).exists())
print("Doğrulama:", ffmpeg_bootstrap._verify(location.ffmpeg))

assert Path(location.ffmpeg).exists(), "ffmpeg indirilemedi"
assert Path(location.ffprobe).exists(), "ffprobe indirilemedi"
assert location.ffmpeg.startswith(str(temp_root)), "yanlış konuma indi"
assert "otomatik" in location.source, "indirme kaynağı doğrulanamadı"
print("\nFFMPEG INDIRME TESTI GECTI")
