# -*- coding: utf-8 -*-
"""Tum testleri sirayla calistirir."""

import io
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

TESTS = [
    ("Altyazi birim testleri", ["test/test_subtitles.py"]),
    ("Transkripsiyon + dilimleme", ["test/test_transcribe.py"]),
    ("Coklu hedef dil + dosya adi", ["test/test_multi_language.py"]),
    ("SRT hedef dil bagimsizligi", ["test/test_srt_target_lang.py"]),
    ("Uctan uca is akisi", ["test/test_runner.py"]),
    ("Kuyruk + model onbellegi", ["test/test_queue.py"]),
    ("Iptal + temizlik", ["test/run_cancel_test.py", "2500"]),
    ("Arayuz akisi", ["test/test_gui_flow.py"]),
]

results = []
for name, args in TESTS:
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
    ok = process.returncode == 0
    tail = (process.stdout or "").strip().splitlines()[-4:]
    for line in tail:
        print("   ", line)
    if not ok:
        print("   --- hata ciktisi ---")
        for line in (process.stderr or "").strip().splitlines()[-12:]:
            print("   ", line)
    print(f"   {'GECTI' if ok else 'BASARISIZ'} ({elapsed:.1f}s)")
    results.append((name, ok, elapsed))

print("\n" + "=" * 70)
print("OZET")
print("=" * 70)
for name, ok, elapsed in results:
    print(f"  {'[OK]  ' if ok else '[FAIL]'} {name} — {elapsed:.1f}s")
failed = [name for name, ok, _ in results if not ok]
print()
print(f"{len(results) - len(failed)}/{len(results)} test grubu basarili")
sys.exit(1 if failed else 0)
