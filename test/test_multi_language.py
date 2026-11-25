"""Coklu hedef dil + dosya adi cakismasi testi (gercek ceviri)."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import app_paths  # noqa: E402
from ffmpeg_utils import SubtitleStyle  # noqa: E402
from worker import JobHooks, JobRunner, JobSettings, ModelCache  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
WORK = PROJECT / "test" / "_langs"
WORK.mkdir(parents=True, exist_ok=True)

# Kaynak: test videosu + mevcut Ingilizce SRT
SOURCE_VIDEO = PROJECT / "test" / "konusma ingilizce.mp4"
SOURCE_SRT = PROJECT / "test" / "konusma ingilizce_tr.srt"

# Temiz bir SRT (Ingilizce kaynak metin) hazirla
EN_SRT = WORK / "konusma ingilizce.srt"
EN_SRT.write_text(
    "1\n00:00:00,180 --> 00:00:04,400\n"
    "Hello and welcome. This is a test of the automatic subtitle system.\n\n"
    "2\n00:00:05,380 --> 00:00:08,200\n"
    "The quick brown fox jumps over the lazy dog.\n\n"
    "3\n00:00:08,800 --> 00:00:11,900\n"
    "Machine translation should handle these sentences correctly.\n\n"
    "4\n00:00:12,760 --> 00:00:14,300\n"
    "Thank you for watching.\n",
    encoding="utf-8",
)
VIDEO_COPY = WORK / "konusma ingilizce.mp4"
if not VIDEO_COPY.exists():
    import shutil

    shutil.copy2(SOURCE_VIDEO, VIDEO_COPY)

cache = ModelCache(app_paths.resolve_models_dir(), log_cb=lambda m: None)
results: dict[str, str] = {}
failures: list[str] = []


def run(language: str, label: str) -> Path | None:
    settings = JobSettings(
        input_path="",
        input_srt=str(EN_SRT),
        target_lang=language,
        output_mode="srt",
        style=SubtitleStyle(),
        ffmpeg_path=str(PROJECT / "ffmpeg" / "bin" / "ffmpeg.exe"),
        models_dir=str(app_paths.resolve_models_dir()),
        pipeline_mode="off",
        source_lang="en",
    )
    hooks = JobHooks(log=lambda m: None)
    runner = JobRunner(settings, cache, hooks)
    try:
        _, srt, _ = runner.run()
    except Exception as exc:  # noqa: BLE001
        failures.append(f"{label}: {exc}")
        print(f"  {label:10s} HATA: {exc}")
        return None
    path = Path(srt)
    results[language] = path.name
    first = [
        line for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().isdigit() and "-->" not in line
    ]
    print(f"  {label:10s} -> {path.name}")
    print(f"             {first[0] if first else '(bos)'}")
    return path


print("=" * 74)
print("COKLU HEDEF DIL (SRT cevirisi)")
print("=" * 74)

for code, label in (
    ("tr", "Türkçe"),
    ("en", "İngilizce"),
    ("de", "Almanca"),
    ("fr", "Fransızca"),
    ("es", "İspanyolca"),
    ("ru", "Rusça"),
    ("ja", "Japonca"),
    ("ar", "Arapça"),
    ("zh", "Çince"),
    ("hi", "Hintçe"),
):
    run(code, label)

print("\n" + "=" * 74)
print("DOSYA ADLARI — cakisma kontrolu")
print("=" * 74)
for code, name in results.items():
    print(f"  {code:3s} -> {name}")
unique = len(set(results.values()))
print(f"\n  {unique} tekil dosya / {len(results)} dil  -> "
      f"{'CAKISMA YOK' if unique == len(results) else 'CAKISMA VAR!'}")

print("\n" + "=" * 74)
print("ICERIK DOGRULAMASI (her dil farkli mi?)")
print("=" * 74)
texts = {}
for code, name in results.items():
    path = WORK / name
    body = " ".join(
        line.strip() for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().isdigit() and "-->" not in line
    )
    texts[code] = body

for code, body in texts.items():
    print(f"  {code:3s} {body[:70]}")

distinct = len(set(texts.values()))
print(f"\n  {distinct} farkli metin / {len(texts)} dil")
all_distinct = distinct == len(texts)
print(f"  TUM DILLER FARKLI: {all_distinct}")

if failures:
    print("\nHATALAR:")
    for item in failures:
        print(" ", item)

cache.release_all()
print("\n" + ("COKLU DIL TESTI GECTI" if all_distinct and not failures else "TEST BASARISIZ"))
sys.exit(0 if all_distinct and not failures else 1)
