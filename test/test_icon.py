"""Simge testi — assets/app.ico gecerli mi, uygulamaya bagli mi."""

import io
import os
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "assets" / "app.ico"
checks: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


print("=" * 66)
print("UYGULAMA SIMGESI")
print("=" * 66)

print("\n1) ICO dosyasi")
check("assets/app.ico var", ICON.exists())
if ICON.exists():
    raw = ICON.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", raw[:6])
    check("ICO basligi", (reserved, kind) == (0, 1), f"{reserved},{kind}")
    sizes = []
    png_ok = True
    for index in range(count):
        entry = raw[6 + 16 * index : 6 + 16 * (index + 1)]
        width, height, _c, _r, _p, bpp, length, offset = struct.unpack("<BBBBHHII", entry)
        sizes.append(width or 256)
        png_ok = png_ok and raw[offset : offset + 8] == b"\x89PNG\r\n\x1a\n"
        png_ok = png_ok and bpp == 32 and length > 0
    check("7 boyut (16..256)", sizes == [16, 24, 32, 48, 64, 128, 256], str(sizes))
    check("PNG girisleri 32bpp", png_ok)

print("\n2) Qt simgeyi okuyabiliyor")
from PySide6.QtGui import QGuiApplication, QIcon  # noqa: E402

app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
icon = QIcon(str(ICON))
check("bos degil", not icon.isNull())
sizes = sorted({size.width() for size in icon.availableSizes()})
check("Qt boyutlari", 16 in sizes and 256 in sizes, str(sizes))
pixmap = icon.pixmap(256, 256)
check("piksel uretildi", not pixmap.isNull() and pixmap.width() == 256, str(pixmap.width()))

print("\n3) Uygulama kablolamasi")
import main as main_mod  # noqa: E402

loaded = main_mod._app_icon()
check("main._app_icon yukluyor", loaded is not None and not loaded.isNull())
check("main.py setWindowIcon cagiriyor", "setWindowIcon" in (ROOT / "main.py").read_text(encoding="utf-8"))
spec = (ROOT / "Subtra.spec").read_text(encoding="utf-8")
check("spec assets kopyaliyor", "assets" in spec and "datas.append" in spec)
check("spec exe ikonu", 'icon = str(icon_path)' in spec)
print("\n4) Uretici betik")
result = subprocess.run(
    [sys.executable, "tools/make_icon.py", "--check"],
    cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
)
check("make_icon --check gecti", result.returncode == 0, (result.stdout or "").strip()[:80])

failed = [label for label, ok, _ in checks if not ok]
print()
if failed:
    print(f"SIMGE TESTI BASARISIZ: {failed}")
    sys.exit(1)
print(f"{len(checks)} kontrol gecti")
print("SIMGE TESTI: GECTI")
