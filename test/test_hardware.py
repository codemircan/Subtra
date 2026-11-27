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
print("3) RAM kontrolü (check_memory) — mantık, sabit değerlerle")
print("=" * 68)
import hardware

available = hardware.available_ram_mb()
print(f"   bu makinede boş RAM: {available} MB")
check("boş RAM okunabildi", available > 0, f"{available} MB")

need_tiny = hardware.MODEL_RAM_MB["tiny"] + hardware.NLLB_RAM_MB + hardware.OVERHEAD_RAM_MB
need_medium = hardware.MODEL_RAM_MB["medium"] + hardware.NLLB_RAM_MB + hardware.OVERHEAD_RAM_MB
print(f"   hesap: tiny={need_tiny} MB, medium={need_medium} MB")

# Enjekte edilen boş RAM ile kararlar deterministik olur; makinenin
# o anki yükü testi kırmaz.
ok_rich, msg_rich = hardware.check_memory("tiny", True, available_mb=need_tiny + 500)
check("bol RAM: tiny kabul", ok_rich, msg_rich.splitlines()[0])

ok_poor, msg_poor = hardware.check_memory("tiny", True, available_mb=need_tiny - 500)
check("az RAM: tiny reddedilir", not ok_poor, msg_poor.splitlines()[0])
check("az RAM: mesaj 'Bellek yetersiz'", "Bellek yetersiz" in msg_poor)
check("az RAM: eksik miktar yazılı", "eksik" in msg_poor.lower())
check("az RAM: öneri var", "kapatın" in msg_poor)

# Tam sınırda kabul (>=)
ok_edge, _ = hardware.check_memory("tiny", True, available_mb=need_tiny)
check("tam sınırda kabul", ok_edge)

# medium daha çok ister
ok_med_poor, msg_med = hardware.check_memory("medium", True, available_mb=need_tiny + 200)
check("medium yetersizse reddedilir", not ok_med_poor, msg_med.splitlines()[0])

# Çeviri kapalı: NLLB payı sayılmaz
need_medium_notrans = hardware.MODEL_RAM_MB["medium"] + hardware.OVERHEAD_RAM_MB
ok_notrans, msg_notrans = hardware.check_memory(
    "medium", with_translation=False, available_mb=need_medium_notrans + 200
)
check("çeviri kapalı: medium kabul", ok_notrans, msg_notrans.splitlines()[0])
check(
    "çeviri kapalı: NLLB payı istenmez",
    str(hardware.NLLB_RAM_MB) not in msg_notrans,
    msg_notrans.splitlines()[0],
)

# Kuyrukta zaten yüklü modeller tekrar sayılmaz: yalnızca OVERHEAD kalır
ok_skip, msg_skip = hardware.check_memory(
    "tiny", True, skip_whisper=True, skip_nllb=True, available_mb=hardware.OVERHEAD_RAM_MB + 100
)
check("modeller bellekteyse kabul", ok_skip, msg_skip.splitlines()[0])
check("modeller bellekteyse mesaj belirtir", "bellekte" in msg_skip.lower())

# RAM okunamazsa iyimser davranır
ok_unknown, msg_unknown = hardware.check_memory("medium", True, available_mb=0)
check("RAM okunamazsa devam eder", ok_unknown, msg_unknown.splitlines()[0])

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
# Uyarı mutlaka sistemin gerçek durumuyla tutarlı olmalı (iki yönde de).
check(
    "uyarı gerçek RAM ile tutarlı",
    bool(warning) == (available < need_medium),
    f"boş={available} gerekli={need_medium}",
)

failed = [label for label, ok in checks if not ok]
print("\n" + "=" * 68)
print(f"{len(checks) - len(failed)}/{len(checks)} kontrol geçti")
print("DONANIM/BELLEK TESTİ: " + ("GEÇTİ" if not failed else f"BAŞARISIZ -> {failed}"))
sys.exit(0 if not failed else 1)
