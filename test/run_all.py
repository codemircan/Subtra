# -*- coding: utf-8 -*-
"""Tüm testleri sırayla çalıştırır.

Çıkış kodları:
  0  -> hepsi geçti (veya SKIP)
  1  -> en az bir test başarısız
  77 -> hiçbir test çalışmadı / hepsi SKIP

Testler fixture yoksa 77 döner (SKIP). `--strict` ile SKIP'ler hata sayılır.
"""

import io
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
SKIP_CODE = 77

TESTS = [
    # (ad, argümanlar, ağ/model gerektirir mi)
    ("Sürüm tutarlılığı", ["test/test_version.py"], False),
    ("Başlatma (DPI / konsol)", ["test/test_startup.py"], False),
    ("Altyazı birim testleri", ["test/test_subtitles.py"], False),
    ("İndirme devam ettirme (Range)", ["test/test_download_resume.py"], False),
    ("Log dosyası", ["test/test_logging.py"], False),
    ("Transkripsiyon + dilimleme", ["test/test_transcribe.py"], True),
    ("Transkript önbelleği + batch", ["test/test_cache_and_batch.py"], True),
    ("Kuyruk: dosya başına dil", ["test/test_queue_languages.py"], True),
    ("Çoklu hedef dil + dosya adı", ["test/test_multi_language.py"], True),
    ("SRT hedef dil bağımsızlığı", ["test/test_srt_target_lang.py"], True),
    ("Uçtan uca iş akışı", ["test/test_runner.py"], True),
    ("Kuyruk + model önbelleği", ["test/test_queue.py"], True),
    ("İptal + temizlik", ["test/run_cancel_test.py", "2500"], True),
    ("Arayüz akışı", ["test/test_gui_flow.py"], True),
]

strict = "--strict" in sys.argv

print("=" * 70)
print("Subtra test paketi")
print("=" * 70)

# Fixture hazırlığı (yoksa üretmeyi dene)
fixture_note = ""
try:
    import fixtures

    if not fixtures.video_path().exists():
        print("\nFixture yok; üretim deneniyor…")
        result = fixtures.ensure_video()
        fixture_note = (
            "fixture üretildi" if result else "fixture üretilemedi (model testleri SKIP olur)"
        )
        print(f"  -> {fixture_note}")
except Exception as exc:  # noqa: BLE001
    print(f"  fixture hazırlığı atlandı: {exc}")

results = []
for name, args, needs_models in TESTS:
    print("\n" + "=" * 70)
    print(f">>> {name}")
    print("=" * 70, flush=True)
    started = time.time()
    process = subprocess.run(
        [PY] + args,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.time() - started
    code = process.returncode

    if code == 0:
        status = "GECTI"
    elif code == SKIP_CODE:
        status = "SKIP"
    else:
        status = "BASARISIZ"

    tail = (process.stdout or "").strip().splitlines()[-4:]
    for line in tail:
        print("   ", line)
    if status == "BASARISIZ":
        print("   --- hata çıktısı ---")
        for line in (process.stderr or "").strip().splitlines()[-14:]:
            print("   ", line)
    print(f"   {status} ({elapsed:.1f}s, kod={code})")
    results.append((name, status, elapsed))

print("\n" + "=" * 70)
print("ÖZET")
print("=" * 70)
symbols = {"GECTI": "[OK]  ", "SKIP": "[SKIP]", "BASARISIZ": "[FAIL]"}
for name, status, elapsed in results:
    print(f"  {symbols[status]} {name} — {elapsed:.1f}s" + (" (model gerekli)" if status == "SKIP" else ""))

passed = sum(1 for _, s, _ in results if s == "GECTI")
skipped = sum(1 for _, s, _ in results if s == "SKIP")
failed = sum(1 for _, s, _ in results if s == "BASARISIZ")

print()
print(f"{passed} geçti, {skipped} atlandı, {failed} başarısız "
      f"(toplam {len(results)})")
if fixture_note:
    print(f"Not: {fixture_note}")

if failed:
    sys.exit(1)
if strict and skipped:
    print("--strict: SKIP'ler hata sayıldı.")
    sys.exit(1)
if passed == 0:
    sys.exit(SKIP_CODE)
sys.exit(0)
