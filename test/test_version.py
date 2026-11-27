"""Sürüm tek kaynak testi.

Sürüm yalnızca version.py'de tanımlı olmalı ve git etiketiyle uyuşmalı.
"""

import io
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import version  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
checks: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


print("=" * 66)
print("SÜRÜM TEK KAYNAK")
print("=" * 66)
print(f"version.__version__ = {version.__version__}")
print(f"version.tag_name()  = {version.tag_name()}")
print()

check("SemVer biçimi (X.Y.Z)", bool(re.fullmatch(r"\d+\.\d+\.\d+", version.__version__)), version.__version__)
check("version_tuple() doğru", version.version_tuple() == tuple(int(p) for p in version.__version__.split(".")))

# error_report aynı sürümü kullanmalı
import error_report  # noqa: E402

check(
    "error_report aynı sürümü kullanıyor",
    error_report.app_version() == version.__version__,
    error_report.app_version(),
)

# Kaynakta başka yerde sabit sürüm tanımı olmamalı
print("\n  Sabit sürüm tanımı taraması:")
pattern = re.compile(r'^(APP_VERSION|__version__|VERSION)\s*=\s*["\']', re.M)
offenders = []
for path in ROOT.glob("*.py"):
    if path.name == "version.py":
        continue
    text = path.read_text(encoding="utf-8", errors="replace")
    for match in pattern.finditer(text):
        offenders.append(f"{path.name}:{match.group(1)}")

check("tek tanım (version.py)", not offenders, ", ".join(offenders) or "temiz")

# Git etiketi (varsa) ile uyuşmalı — yalnızca bu commit etiketliyse.
# Geliştirme sırasında sürüm yükseltilip henüz etiketlenmemiş olabilir;
# o durumda kontrol bilgi olarak geçer, hata vermez.
tag_ok = True
tag_detail = "git yok / etiket yok (atlandı)"
try:
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
    ).stdout.strip()

    # Yalnızca HEAD'in kendi etiketi bağlayıcıdır. `git describe --tags`
    # eski bir sürümün etiketini döndürüp yeni sürümü yanlışlıkla
    # "uyumsuz" gösteriyordu (CI'da her sürüm yükseltmesinde).
    result = subprocess.run(
        ["git", "describe", "--tags", "--exact-match", "HEAD"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
    )
    if result.returncode == 0 and result.stdout.strip():
        tag = result.stdout.strip()
        if dirty:
            tag_detail = f"etiket {tag}; ağaç kirli, kontrol atlandı"
        else:
            tag_detail = f"etiket {tag}"
            tag_ok = tag == version.tag_name()
    else:
        tag_detail = "bu commit etiketli değil (kontrol atlandı)"
except (OSError, subprocess.SubprocessError) as exc:
    tag_detail = f"git okunamadı: {exc}"

check("git etiketi sürümle uyumlu", tag_ok, tag_detail)

failed = [label for label, ok, _ in checks if not ok]
print()
if failed:
    print(f"SÜRÜM TESTİ BAŞARISIZ: {failed}")
    sys.exit(1)
print("SÜRÜM TESTİ GEÇTİ")
