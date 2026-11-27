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

failed = [label for label, ok, _ in checks if not ok]
print()
if failed:
    print(f"MODEL KORUMASI BASARISIZ: {failed}")
    sys.exit(1)
print(f"{len(checks)} kontrol gecti")
print("MODEL KORUMASI: GECTI")
