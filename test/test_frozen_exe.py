"""Paketlenmis exe dogrulamasi (PyInstaller gerekir; yoksa SKIP).

Neden gerekli: bu test yokken paketlenmis exe UC gercek hata ile sessizce
bozuktu ve kimse fark etmedi:
  1. faster-whisper VAD modeli (silero_vad_v6.onnx) pakete girmiyordu ->
     HER transkripsiyon "NO_SUCHFILE" ile dusuyordu
  2. check_ctranslate2_runtime() donmus modda `Subtra.exe -c ...` cagirip
     GUI acip 60 sn zaman asimina ugruyordu -> her is "motor calismiyor"
  3. assets/ (simge) kopyalanmiyordu

Test uc asamali:
  A. build (PyInstaller, ~2-3 dk)
  B. --self-check  (moduller, DLL, simge, veri klasoru)
  C. --smoke-test  (gercek Whisper + NLLB + FFmpeg ile SRT uretimi)

Yavas oldugu icin varsayilan olarak `test/run_all.py` icinde YOKTUR:
    py test/test_frozen_exe.py
"""

import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import fixtures  # noqa: E402
import app_paths  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "Subtra"
EXE = DIST / "Subtra.exe"

checks: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


def skip(reason: str) -> int:
    print(f"\n  SKIP: {reason}")
    print("  (test atlandi, hata degil)")
    return 77


print("=" * 66)
print("PAKETLENMIS EXE DOGRULAMASI")
print("=" * 66)

try:
    import PyInstaller  # noqa: F401
except ImportError:
    sys.exit(skip("PyInstaller kurulu değil (py -m pip install pyinstaller)"))

if "--no-build" not in sys.argv:
    print("\nA) Derleme (PyInstaller)")
    started = time.time()
    build = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "Subtra.spec",
         "--noconfirm", "--clean", "--log-level", "ERROR"],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=1800,
    )
    print(f"   {time.time() - started:.0f} sn, kod={build.returncode}")
    if build.returncode != 0:
        print((build.stderr or "")[-800:])
    check("derleme basarili", build.returncode == 0, f"kod={build.returncode}")
else:
    print("\nA) Derleme atlandi (--no-build)")

check("Subtra.exe var", EXE.exists(), str(EXE))
if not EXE.exists():
    print(f"\nPAKETLEME TESTI BASARISIZ: exe yok")
    sys.exit(1)

print("\nB) Paket icerigi")
vad = list(DIST.rglob("silero_vad*.onnx"))
check("VAD modeli pakette", bool(vad), str(vad[0].relative_to(DIST)) if vad else "yok")
check("simge pakette", any(DIST.rglob("assets/app.ico")))
check("_internal var", (DIST / "_internal").is_dir())

print("\nC) --self-check (frozen)")
env = dict(os.environ)
env.pop("QT_QPA_PLATFORM", None)
report = Path(os.environ["LOCALAPPDATA"]) / "Subtra" / "selfcheck.txt"
report.unlink(missing_ok=True)

proc = subprocess.Popen(
    [str(EXE), "--self-check"], env=env, cwd=str(DIST),
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
deadline = time.time() + 300
while time.time() < deadline and proc.poll() is None:
    time.sleep(0.5)
code = proc.poll()
if code is None:
    proc.kill()
check("self-check zamaninda bitti", code is not None, f"kod={code}")
check("self-check kod=0", code == 0, f"kod={code}")
check("rapor yazildi", report.exists())

if report.exists():
    text = report.read_text(encoding="utf-8", errors="replace")
    print("\n   --- selfcheck.txt ---")
    for line in text.splitlines()[:18]:
        print("   ", line)
    check("frozen=True", "frozen      : True" in text)
    check("ctranslate2 OK", "ctranslate2 : OK" in text)
    check("tum moduller OK", "FAIL " not in text)
    check("SONUC: GECTI", "SONUC: GECTI" in text)

print("\nD) --smoke-test (gercek Whisper + NLLB + FFmpeg)")
video = fixtures.require_video()

models_dir = app_paths.resolve_models_dir()
if not (models_dir / "faster-whisper-tiny").exists():
    sys.exit(skip("whisper tiny modeli yok (testler model indirmez)"))

# exe'ye ffmpeg'i ver (build.ps1 de boyle yapar)
ffmpeg_pack = DIST / "ffmpeg" / "bin"
ffmpeg_pack.mkdir(parents=True, exist_ok=True)
import ffmpeg_bootstrap  # noqa: E402

location = ffmpeg_bootstrap.find_existing()
if location is not None:
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        source = Path(location.ffmpeg).parent / name
        if source.exists():
            shutil.copy2(source, ffmpeg_pack / name)

# Benzersiz veri klasoru: modelleri junction ile bagla (kopyalama yok)
base = Path(os.environ["TEMP"]) / "subtra_frozen_test"
if base.exists():
    shutil.rmtree(base, ignore_errors=True)
base.mkdir(parents=True)
junction = base / "models"
subprocess.run(
    ["cmd", "/c", "mklink", "/J", str(junction), str(models_dir)],
    capture_output=True, text=True,
)
check("models baglandi", junction.exists())

smoke_report = base / "smoke.txt"
srt_target = video.with_name(video.stem + "_tr.srt")
srt_target.unlink(missing_ok=True)

env_smoke = dict(env)
env_smoke["SUBTRA_DATA_DIR"] = str(base)
started = time.time()
proc = subprocess.Popen(
    [str(EXE), "--smoke-test", str(video), "tr", "tiny"],
    env=env_smoke, cwd=str(DIST),
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
deadline = time.time() + 900
while time.time() < deadline and proc.poll() is None:
    time.sleep(1)
code = proc.poll()
elapsed = time.time() - started
if code is None:
    proc.kill()
check("smoke-test zamaninda bitti", code is not None, f"{elapsed:.0f} sn")
check("smoke-test kod=0", code == 0, f"kod={code}, {elapsed:.0f} sn")

if smoke_report.exists():
    text = smoke_report.read_text(encoding="utf-8", errors="replace")
    print("\n   --- smoke.txt ---")
    for line in text.splitlines():
        if line.startswith("  ") or line.startswith("SONUC"):
            print("   ", line)
    check("frozen=True", "frozen=True" in text)
    check("transkripsiyon yapildi", "Transkripsiyon tamamlandı" in text)
    check("ceviri yapildi", "Çeviri tamamlandı" in text)
    check("VAD hatasi yok", "silero_vad" not in text)
    check("SONUC: GECTI", "SONUC: GECTI" in text)

check("SRT diske yazildi", srt_target.exists())
if srt_target.exists():
    content = srt_target.read_text(encoding="utf-8")
    check("SRT satir sayisi > 0", "-->" in content, f"{content.count('-->')} cue")
    check("Turkce cikti", "Merhaba" in content or "ve" in content, content[:60].replace("\n", " "))

# Temizlik
srt_target.unlink(missing_ok=True)
shutil.rmtree(base, ignore_errors=True)

failed = [label for label, ok, _ in checks if not ok]
print()
if failed:
    print(f"PAKETLENMIS EXE TESTI BASARISIZ: {failed}")
    sys.exit(1)
print(f"{len(checks)} kontrol gecti")
print("PAKETLENMIS EXE TESTI: GECTI")
