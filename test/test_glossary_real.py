"""Sozluk + GERCEK NLLB uctan uca testi.

Model yoksa veya FFmpeg yoksa SKIP (exit 77). Indirme yapilmaz
(fixtures.SUBTRA_NO_DOWNLOAD=1).
"""

import io
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import fixtures  # noqa: E402  (SUBTRA_NO_DOWNLOAD=1)
import app_paths  # noqa: E402
import ffmpeg_bootstrap  # noqa: E402
import subtitles as subtitles_mod  # noqa: E402
from translator import is_nllb_cached  # noqa: E402
from worker import JobRunner, JobSettings, ModelCache  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


print("=" * 66)
print("SOZLUK + GERCEK NLLB (uctan uca)")
print("=" * 66)

models_dir = app_paths.resolve_models_dir()
if not is_nllb_cached(models_dir):
    print("\n  SKIP: NLLB modeli yok.")
    print("  (test atlandi, hata degil)")
    sys.exit(77)
if ffmpeg_bootstrap.find_existing() is None:
    print("\n  SKIP: FFmpeg yok (otomatik indirme testlerde kapali).")
    print("  (test atlandi, hata degil)")
    sys.exit(77)

work = Path(tempfile.mkdtemp(prefix="subtra_glossary_", dir=str(app_paths.temp_dir())))
try:
    source_srt = work / "ornek.srt"
    source_srt.write_text(
        "1\n00:00:00,200 --> 00:00:04,000\n"
        "The automatic subtitle system uses machine translation.\n\n"
        "2\n00:00:04,400 --> 00:00:08,000\n"
        "The OpenAI prompt is short. Subtra keeps the timing.\n",
        encoding="utf-8",
    )

    glossary_file = work / "sozluk.tsv"
    glossary_file.write_text(
        "OpenAI\tOpenAI\n"
        "Subtra\tSubtra\n"
        "machine translation\tMAKINE CEVIRI\n"
        "automatic subtitle system\tOTOMATIK ALTYAZI SISTEMI\n",
        encoding="utf-8",
    )

    settings = JobSettings(
        input_path="",
        input_srt=str(source_srt),
        target_lang="tr",
        output_mode="srt",
        models_dir=str(models_dir),
        skip_preview=True,
        use_transcript_cache=False,
        glossary_path=str(glossary_file),
        source_lang="en",
    )
    logs: list[str] = []
    hooks = None
    import worker as worker_mod

    hooks = worker_mod.JobHooks(log=logs.append)
    models = ModelCache(models_dir)
    video, srt, summary = JobRunner(settings, models, hooks).run()
    models.release_all()

    check("video uretilmedi (srt modu)", video == "", video)
    output = Path(srt)
    check("srt yazildi", output.exists(), srt)
    entries = subtitles_mod.read_srt(output)
    text = " ".join(entry["text"] for entry in entries)
    check("kaynak dil İngilizce", "İngilizce" in summary, summary.splitlines()[1] if summary else "")
    check("terim: MAKINE CEVIRI", "MAKINE CEVIRI" in text, text)
    check("terim: OTOMATIK ALTYAZI SISTEMI", "OTOMATIK ALTYAZI SISTEMI" in text, text)
    check("marka: OpenAI", "OpenAI" in text, text)
    check("marka: Subtra", "Subtra" in text, text)
    check("yer tutucu sizmadi", "[[" not in text, text)
    joined = "\n".join(logs)
    check("log: terim uygulandi", "terim uygulandı" in joined, joined[-300:])
    check("log: sozluk yuklendi", "Terim sözlüğü yüklendi" in joined, "")
    print("\n  --- cikti SRT ---")
    for line in text.splitlines():
        print("   ", line[:90])
finally:
    shutil.rmtree(work, ignore_errors=True)

failed = [label for label, ok, _ in checks if not ok]
print()
if failed:
    print(f"SOZLUK NLLB TESTI BASARISIZ: {failed}")
    sys.exit(1)
print(f"{len(checks)} kontrol gecti")
print("SOZLUK NLLB TESTI: GECTI")
