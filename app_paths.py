"""Uygulama yollari: veri, modeller, loglar, onbellek, ffmpeg.

Tum yazilabilir veriler `%LOCALAPPDATA%\\Subtra` altinda tutulur.
Program Files gibi korumali klasorlere kurulumda bile yazma izni gerekmez.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "Subtra"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """Uygulamanin (exe veya kaynak) bulundugu klasor."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundled_root() -> Path:
    """PyInstaller'in gecici/extract klasoru."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return app_root()


def _local_app_data() -> Path:
    for name in ("LOCALAPPDATA", "APPDATA"):
        value = os.environ.get(name)
        if value:
            return Path(value)
    return Path.home() / "AppData" / "Local"


def data_dir() -> Path:
    """Kalici veri klasoru (modeller, loglar, ffmpeg, ayarlar).

    Onceki surumlerde (`VideoCeviri`) indirilmis modeller varsa yeni klasore
    tasinir; boylece 1.6 GB model yeniden indirilmez.
    """
    override = os.environ.get("SUBTRA_DATA_DIR") or os.environ.get("VIDEOCEVIRI_DATA_DIR")
    base = Path(override) if override else _local_app_data() / APP_DIR_NAME
    if not override:
        _migrate_legacy_data_dir(base)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _migrate_legacy_data_dir(target: Path) -> None:
    """Eski `VideoCeviri` veri klasorunu `Subtra` altina tasir (tek seferlik).

    Yalnizca hedef klasor bossa calisir. Hata durumunda sessizce gecer:
    kullanici en kotu ihtimalle modelleri yeniden indirir.
    """
    if target.exists() and any(target.iterdir()):
        return

    legacy = _local_app_data() / "VideoCeviri"
    if not legacy.is_dir():
        return

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.rmdir()
        legacy.rename(target)
    except OSError:
        # Farkli surucu veya kilitli dosya: kopyalamayi dene.
        try:
            import shutil

            shutil.copytree(legacy, target, dirs_exist_ok=True)
        except OSError:
            pass


def models_dir() -> Path:
    return data_dir() / "models"


def logs_dir() -> Path:
    directory = data_dir() / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def cache_dir() -> Path:
    directory = data_dir() / "cache"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def tools_dir() -> Path:
    return data_dir() / "tools"


def ffmpeg_dir() -> Path:
    """Otomatik indirilen FFmpeg'in kok dizini (bin/ altinda exe'ler)."""
    return tools_dir() / "ffmpeg"


def temp_dir() -> Path:
    directory = cache_dir() / "temp"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def transcripts_dir() -> Path:
    """Transkript önbelleği (Whisper çıktısı, dile göre yeniden kullanılır)."""
    directory = cache_dir() / "transcripts"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def legacy_models_dir() -> Path | None:
    """Eski surumlerdeki `<proje>\\models` klasoru (varsa)."""
    candidate = app_root() / "models"
    if candidate.is_dir() and any(candidate.iterdir()):
        return candidate
    if is_frozen():
        alt = Path.cwd() / "models"
        if alt.is_dir() and any(alt.iterdir()):
            return alt
    return None


def resolve_models_dir(preferred: str | Path | None = None) -> Path:
    """Kullanilacak model klasorunu sec: ayar > yeni konum > eski konum.

    Eski `models` klasoru varsa ve yeni konum bossa orasi kullanilir; boylece
    kullanicinin indirdigi modeller yeniden indirilmez.
    """
    if preferred:
        target = Path(preferred)
        target.mkdir(parents=True, exist_ok=True)
        return target

    new = models_dir()
    new.mkdir(parents=True, exist_ok=True)
    if any(new.iterdir()):
        return new

    legacy = legacy_models_dir()
    if legacy is not None:
        return legacy
    return new

