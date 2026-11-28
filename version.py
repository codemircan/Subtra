"""Subtra sürüm bilgisi — TEK KAYNAK.

Sürüm yalnızca burada tanımlanır. Diğer dosyalar (error_report, spec,
build.ps1) buradan okur. Etiketleme ve kod sürümü ayrışmasın diye
`test/test_version.py` bunu kontrol eder.
"""

from __future__ import annotations

# SemVer: MAJOR.MINOR.PATCH
__version__ = "2.8.0"

APP_NAME = "Subtra"
APP_DESCRIPTION = "CPU tabanlı otomatik altyazı, dil tespiti ve çeviri"


def version_tuple() -> tuple[int, int, int]:
    parts = __version__.split(".")
    while len(parts) < 3:
        parts.append("0")
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return 0, 0, 0


def tag_name() -> str:
    """Git etiketi biçimi."""
    return f"v{__version__}"
