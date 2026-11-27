"""Model indirme korumasi: SUBTRA_NO_DOWNLOAD=1 iken net hata, ag yok.

Regresyon: `translator.ensure_nllb_model` `_downloads_disabled()` cagiriyordu
ama fonksiyon import edilmemisti -> NameError (kullaniciya anlamsiz hata).
"""

import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import fixtures  # noqa: E402  (SUBTRA_NO_DOWNLOAD=1)
from errors import ModelDownloadError, TranslationError  # noqa: E402
from transcriber import _downloads_disabled, ensure_whisper_model  # noqa: E402
from translator import ensure_nllb_model  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


print("=" * 66)
print("MODEL INDIRME KORUMASI")
print("=" * 66)

check("SUBTRA_NO_DOWNLOAD etkin", _downloads_disabled() is True)

work = Path(tempfile.mkdtemp(prefix="subtra_guard_"))
work.mkdir(parents=True, exist_ok=True)

print("\n1) NLLB yokken indirme kapali")
try:
    ensure_nllb_model(work)
    check("hata verdi", False, "istisna beklenirdi")
except TranslationError as exc:
    check("TranslationError", True, str(exc).splitlines()[0][:60])
    check("mesaj net", "SUBTRA_NO_DOWNLOAD" in str(exc), str(exc)[:90])
except NameError as exc:
    check("NameError yok", False, f"NameError: {exc}")
except Exception as exc:  # noqa: BLE001
    check("dogru istisna turu", False, f"{type(exc).__name__}: {exc}")

print("\n2) Whisper yokken indirme kapali")
try:
    ensure_whisper_model("tiny", work)
    check("hata verdi", False, "istisna beklenirdi")
except ModelDownloadError as exc:
    check("ModelDownloadError", True, str(exc).splitlines()[0][:60])
except Exception as exc:  # noqa: BLE001
    check("dogru istisna turu", False, f"{type(exc).__name__}: {exc}")

print("\n3) Ag erisimi yok")
# Indirme fonksiyonu hic cagrilmamali: islevsel kanit -> gecen sure kisa
# ve gecici klasor bos kalmali.
check("klasor bos kaldi", not any(work.iterdir()), str(list(work.iterdir())[:3]))
import shutil  # noqa: E402

shutil.rmtree(work, ignore_errors=True)

print("\n4) CTranslate2 probu: frozen modda exe'ye ozel bayrak")
import subprocess  # noqa: E402
import sys as _sys  # noqa: E402

import translator  # noqa: E402

originals = (subprocess.run, getattr(_sys, "frozen", None), _sys.executable)
calls: list[list[str]] = []


class _Result:
    def __init__(self, code: int) -> None:
        self.returncode = code
        self.stdout = "CT2_RUNTIME_OK"
        self.stderr = ""


def patch_run(code: int) -> None:
    def fake(cmd, **kwargs):
        calls.append(list(cmd))
        return _Result(code)

    subprocess.run = fake  # type: ignore[assignment]


try:
    # frozen: sys.executable = Subtra.exe, "-c" KABUL ETMEZ
    _sys.frozen = True  # type: ignore[attr-defined]
    _sys.executable = r"C:\app\Subtra.exe"
    patch_run(0)
    error = translator.check_ctranslate2_runtime(timeout=5)
    check("frozen: hata yok", error is None, str(error))
    check("frozen: --ct2-probe kullanildi",
          bool(calls) and calls[-1][1:] == ["--ct2-probe"], str(calls[-1]))
    check("frozen: '-c' kullanilmadi", "-c" not in calls[-1], str(calls[-1]))

    patch_run(3)
    error = translator.check_ctranslate2_runtime(timeout=5)
    check("frozen: cokme kodu hata verir", bool(error) and "0x00000003" in str(error),
          str(error)[:60])

    # gelistirme modu: python -c ... (stdout kontrolu gerekir)
    del _sys.frozen
    _sys.executable = originals[2]
    patch_run(0)
    error = translator.check_ctranslate2_runtime(timeout=5)
    check("kaynak mod: hata yok", error is None, str(error))
    check("kaynak mod: '-c' kullanildi", "-c" in calls[-1], str(calls[-1]))
finally:
    subprocess.run = originals[0]  # type: ignore[assignment]
    if originals[1] is None:
        if hasattr(_sys, "frozen"):
            delattr(_sys, "frozen")
    else:
        _sys.frozen = originals[1]  # type: ignore[attr-defined]
    _sys.executable = originals[2]

print("\n5) main.py --ct2-probe gercekten calisiyor")
probe = subprocess.run(
    [sys.executable, "main.py", "--ct2-probe"],
    cwd=str(Path(__file__).resolve().parent.parent),
    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
)
check("--ct2-probe kod=0", probe.returncode == 0, f"kod={probe.returncode}")
check("--ct2-probe pencere acmadi", "Qt" not in (probe.stderr or ""), (probe.stderr or "")[:60])

failed = [label for label, ok, _ in checks if not ok]
print()
if failed:
    print(f"MODEL KORUMASI BASARISIZ: {failed}")
    sys.exit(1)
print(f"{len(checks)} kontrol gecti")
print("MODEL KORUMASI: GECTI")
