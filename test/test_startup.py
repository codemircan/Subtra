"""Başlatma testi: DPI uyarısı ve konsol penceresi regresyonu.

Neden: eski `main.py` elle `SetProcessDpiAwareness(1)` çağırıyordu. Qt 6
varsayılan olarak `PER_MONITOR_AWARE_V2` ister; süreç zaten SYSTEM_DPI_AWARE
olduğu için Qt'nin çağrısı "Erişim engellendi" ile başarısız oluyor ve
konsola şu uyarı düşüyordu:

    qt.qpa.window: SetProcessDpiAwarenessContext() failed: Erişim engellendi.

Ayrıca çoklu monitörde metin bulanıklaşıyordu. Bu test iki şeyi kilitler:
  1. main.py DPI'ya dokunmaz
  2. QApplication sonrası süreç PER_MONITOR_AWARE olur
"""

import io
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
checks: list[tuple[str, bool]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


print("=" * 66)
print("BAŞLATMA (DPI / konsol) TESTİ")
print("=" * 66)

# 1) Kaynakta elle DPI çağrısı olmamalı (yalnızca GERÇEK kod; yorum ve
#    docstring'lerde adın geçmesi sorun değil — AST ile ayrıştırıyoruz).
import ast  # noqa: E402

print("\n1) main.py DPI'ya dokunmuyor")
FORBIDDEN = {
    "SetProcessDpiAwareness",
    "SetProcessDPIAware",
    "SetProcessDpiAwarenessContext",
    "AA_EnableHighDpiScaling",
}


def dpi_calls(source: str) -> list[str]:
    """Kodda gerçekten çağrılan yasaklı DPI adlarını döndürür."""
    hits: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ["<sözdizimi hatası>"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN:
            hits.append(node.attr)
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN:
            hits.append(node.id)
    return hits


main_src = (ROOT / "main.py").read_text(encoding="utf-8")
found = dpi_calls(main_src)
check("elle DPI çağrısı yok", not found, ", ".join(found) or "temiz")

# 2) Diğer modüllerde de olmamalı (gui.py dahil)
others: list[str] = []
for path in ROOT.glob("*.py"):
    if path.name == "main.py":
        continue
    text = path.read_text(encoding="utf-8", errors="replace")
    for name in dpi_calls(text):
        others.append(f"{path.name}:{name}")
check("diğer modüllerde de yok", not others, ", ".join(others) or "temiz")

# 3) calistir.bat konsolsuz başlatıyor
print("\n2) calistir.bat konsolsuz (pyw)")
bat = ROOT / "calistir.bat"
if bat.exists():
    raw = bat.read_bytes()
    check("pyw kullanıyor", b"pyw" in raw)
    check("CRLF", raw.count(b"\r\n") > 0 and raw.count(b"\n") == raw.count(b"\r\n"))
    check("BOM yok", not raw.startswith(b"\xef\xbb\xbf"))
else:
    check("calistir.bat var", False)

# 4) Gerçek DPI durumu (Qt sonrası)
print("\n3) QApplication sonrası DPI farkındalığı")
offscreen = os.environ.get("QT_QPA_PLATFORM", "").lower() in {
    "offscreen",
    "minimal",
    "vnc",
}
if os.name != "nt":
    check("Windows DPI kontrolü", True, "atlandı (Windows değil)")
elif offscreen:
    # Offscreen/minimal platform eklentisi pencere sistemi açmadığı için
    # DPI farkındalığı ayarlamaz. Bu bir ürün hatası değil, ortam farkı:
    # CI bu değişkenle çalışır. Elle doğrulama: değişken olmadan çalıştırın.
    check(
        "DPI kontrolü",
        True,
        "atlandı (QT_QPA_PLATFORM="
        + os.environ.get("QT_QPA_PLATFORM", "")
        + "; gerçek pencere sistemi gerekir)",
    )
else:
    import ctypes

    names = {0: "UNAWARE", 1: "SYSTEM_DPI_AWARE", 2: "PER_MONITOR_AWARE"}

    def awareness() -> int:
        value = ctypes.c_int(-1)
        ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(value))
        return value.value

    before = awareness()

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])
    after = awareness()
    print(f"   Qt öncesi: {before} ({names.get(before)})")
    print(f"   Qt sonrası: {after} ({names.get(after)})")
    check(
        "PER_MONITOR_AWARE(2) uygulandı",
        after == 2,
        f"{after} ({names.get(after)}) — uyarının nedeni buydu",
    )
    QTimer.singleShot(100, app.quit)
    app.exec()

failed = [label for label, ok in checks if not ok]
print()
if failed:
    print(f"BAŞLATMA TESTİ BAŞARISIZ: {failed}")
    sys.exit(1)
print("BAŞLATMA TESTİ GEÇTİ")
