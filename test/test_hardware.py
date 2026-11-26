"""Donanım/bellek testleri: psutil'siz çekirdek sayısı, RAM kontrolü."""

import io
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
checks = []


def check(label, ok, detail=""):
    checks.append((label, ok))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


print("=" * 68)
print("1) Fiziksel çekirdek: psutil VAR / YOK (aynı sonuç olmalı)")
print("=" * 68)

script = """
import builtins, json, sys
real = builtins.__import__
def fake(name, *a, **k):
    if name == 'psutil':
        raise ImportError('psutil yok')
    return real(name, *a, **k)
if sys.argv[1] == 'nopsutil':
    builtins.__import__ = fake
    sys.modules.pop('psutil', None)
import hardware
h = hardware.hardware_info(refresh=True)
print(json.dumps({'physical': h.physical_cores, 'logical': h.logical_cores}))
"""

results = {}
for mode in ("with", "nopsutil"):
    proc = subprocess.run(
        [sys.executable, "-c", script, sys.argv[0] if False else mode],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    import json

    try:
        results[mode] = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        results[mode] = {"error": (proc.stderr or proc.stdout)[-300:]}

for mode, data in results.items():
    print(f"   {mode:10s}: {data}")

with_p = results.get("with", {})
no_p = results.get("nopsutil", {})
check("her iki durumda sonuç alındı", "physical" in with_p and "physical" in no_p)
check(
    "psutil'siz de doğru fiziksel çekirdek",
    with_p.get("physical") == no_p.get("physical"),
    f"{with_p.get('physical')} vs {no_p.get('physical')}",
)
check(
    "fiziksel <= mantıksal",
    0 < no_p.get("physical", 0) <= no_p.get("logical", 0),
    f"{no_p.get('physical')}/{no_p.get('logical')}",
)

print("\n" + "=" * 68)
print("2) ctypes.wintypes kullanılmıyor")
print("=" * 68)
source = (ROOT / "hardware.py").read_text(encoding="utf-8")
import ast

has_wintypes = False
for node in ast.walk(ast.parse(source)):
    if isinstance(node, ast.Attribute) and node.attr == "wintypes":
        has_wintypes = True
check("ctypes.wintypes referansı yok", not has_wintypes)

print("\n" + "=" * 68)
print("3) RAM kontrolü (check_memory)")
print("=" * 68)
import hardware

available = hardware.available_ram_mb()
print(f"   boş RAM: {available} MB")
check("boş RAM okunabildi", available > 0, f"{available} MB")

ok_small, msg_small = hardware.check_memory("tiny", with_translation=True)
check("tiny kabul edilir", ok_small, msg_small.splitlines()[0])

ok_medium, msg_medium = hardware.check_memory("medium", with_translation=True)
print(f"   medium: {msg_medium.splitlines()[0]}")
# Bu makinede 6 GB: medium ya reddedilmeli ya da yeterli olmalı (tutarlı)
need_medium = hardware.MODEL_RAM_MB["medium"] + hardware.NLLB_RAM_MB + hardware.OVERHEAD_RAM_MB
expected = available >= need_medium
check("medium kararı tutarlı", ok_medium == expected, f"beklenen={expected}")

check(
    "reddedilince mesaj açıklayıcı",
    ok_medium or ("Bellek yetersiz" in msg_medium and "tiny" in msg_medium),
)

print("\n" + "=" * 68)
print("4) Model başına RAM tahminleri artan sırada")
print("=" * 68)
sizes = ["tiny", "base", "small", "medium"]
values = [hardware.MODEL_RAM_MB[s] for s in sizes]
print(f"   {dict(zip(sizes, values))}")
check("tiny < base < small < medium", values == sorted(values))

print("\n" + "=" * 68)
print("5) memory_warning: medium için uyarı üretir")
print("=" * 68)
warning = hardware.memory_warning("medium")
if available >= need_medium:
    check("yeterli RAM'de uyarı yok", warning == "", warning[:60])
else:
    check("yetersiz RAM'de uyarı var", bool(warning), warning.splitlines()[0][:70])
    check("uyarı medium'a özgü", "medium" in warning.lower())

failed = [label for label, ok in checks if not ok]
print("\n" + "=" * 68)
print(f"{len(checks) - len(failed)}/{len(checks)} kontrol geçti")
print("DONANIM/BELLEK TESTİ: " + ("GEÇTİ" if not failed else f"BAŞARISIZ -> {failed}"))
sys.exit(0 if not failed else 1)
