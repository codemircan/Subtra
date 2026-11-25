"""FFmpeg bulma ve otomatik indirme.

Oncelik sirasi:
  1. Kullanicinin elle sectigi yol (ayar)
  2. Exe'ye gomulu `ffmpeg/bin` (PyInstaller ile paketlenmisse)
  3. Uygulama klasorundeki `ffmpeg/bin`
  4. Daha once otomatik indirilen `%LOCALAPPDATA%\\Subtra\\tools\\ffmpeg\\bin`
  5. PATH
  6. Otomatik indirme (ilk kullanimda)
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import app_paths

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

EXE_NAME = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
PROBE_NAME = "ffprobe.exe" if os.name == "nt" else "ffprobe"

DOWNLOAD_PAGE = "https://www.gyan.dev/ffmpeg/builds/"

# (ad, url) — ilki denenir, olmazsa ikinciye gecilir.
DOWNLOAD_MIRRORS: tuple[tuple[str, str], ...] = (
    (
        "gyan.dev essentials",
        "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    ),
    (
        "BtbN latest win64",
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
        "ffmpeg-master-latest-win64-gpl.zip",
    ),
)

ProgressCB = Optional[Callable[[float, str], None]]
LogCB = Optional[Callable[[str], None]]


class FFmpegError(RuntimeError):
    """FFmpeg/ffprobe ile ilgili hatalar (ffmpeg_utils ile ayni)."""


class CancelledError(RuntimeError):
    """Kullanici islemi iptal etti."""


class FFmpegNotFound(FFmpegError):
    """FFmpeg hicbir yerde bulunamadi."""


class FFmpegDownloadError(FFmpegError):
    """Otomatik indirme basarisiz oldu."""


@dataclass(frozen=True)
class FFmpegLocation:
    ffmpeg: str
    ffprobe: str
    source: str

    def as_tuple(self) -> tuple[str, str]:
        return self.ffmpeg, self.ffprobe


# --------------------------------------------------------------------------
# Yardimcilar
# --------------------------------------------------------------------------

def _verify(exe: str) -> bool:
    try:
        result = subprocess.run(
            [exe, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            timeout=25,
            creationflags=CREATE_NO_WINDOW,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return False
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0 and "ffmpeg version" in output.lower()


def _candidate_dirs(explicit: str | None) -> list[tuple[str, Path | None]]:
    """(kaynak etiketi, bin klasoru) listesi; PATH icin None."""
    items: list[tuple[str, Path | None]] = []

    if explicit:
        path = Path(explicit)
        directory = path if path.is_dir() else path.parent
        items.append(("elle seçildi", directory))

    # Exe'ye gomulu
    bundled = app_paths.bundled_root() / "ffmpeg" / "bin"
    items.append(("gömülü", bundled))

    # Uygulama klasoru
    local = app_paths.app_root() / "ffmpeg" / "bin"
    items.append(("uygulama klasörü", local))

    # Otomatik indirilen
    downloaded = app_paths.ffmpeg_dir() / "bin"
    items.append(("otomatik indirildi", downloaded))

    items.append(("PATH", None))
    return items


def find_existing(explicit: str | None = None) -> FFmpegLocation | None:
    """Kurulu bir FFmpeg varsa dondurur, yoksa None."""
    for label, directory in _candidate_dirs(explicit):
        if directory is None:
            exe = shutil.which("ffmpeg")
            if not exe:
                continue
            probe = shutil.which("ffprobe")
            if not probe:
                continue
            if _verify(exe):
                return FFmpegLocation(exe, probe, label)
            continue

        exe_path = directory / EXE_NAME
        probe_path = directory / PROBE_NAME
        if not exe_path.exists():
            continue
        if not probe_path.exists():
            continue
        if _verify(str(exe_path)):
            return FFmpegLocation(str(exe_path), str(probe_path), label)
    return None


def describe_ffmpeg() -> str:
    """Hata raporu icin kisa ozet."""
    location = find_existing()
    if location is None:
        return "FFmpeg bulunamadı"
    try:
        result = subprocess.run(
            [location.ffmpeg, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=20,
            creationflags=CREATE_NO_WINDOW,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        first = (result.stdout or "").splitlines()[0] if result.stdout else "?"
    except Exception:
        first = "(sürüm okunamadı)"
    return f"Kaynak: {location.source}\n{first}\nYol: {location.ffmpeg}"


# --------------------------------------------------------------------------
# Indirme
# --------------------------------------------------------------------------

def _free_bytes(path: Path) -> int:
    try:
        return shutil.disk_usage(str(path)).free
    except OSError:
        return 0


def _download_to_file(
    url: str,
    target: Path,
    progress_cb: ProgressCB = None,
    cancel_event: threading.Event | None = None,
) -> None:
    import requests

    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")

    with requests.get(url, stream=True, timeout=120, allow_redirects=True) as response:
        response.raise_for_status()
        try:
            total = int(response.headers.get("Content-Length") or 0)
        except ValueError:
            total = 0

        if total and _free_bytes(target.parent) < total * 2:
            raise FFmpegDownloadError(
                "FFmpeg indirmek için yeterli disk alanı yok.\n"
                f"Gereken: yaklaşık {total * 2 / (1024 ** 3):.2f} GB"
            )

        written = 0
        with open(part, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if cancel_event is not None and cancel_event.is_set():
                    raise CancelledError("FFmpeg indirmesi iptal edildi.")
                if not chunk:
                    continue
                handle.write(chunk)
                written += len(chunk)
                if progress_cb and total:
                    progress_cb(min(0.99, written / total), "İndiriliyor")

    if part.stat().st_size < 1024 * 1024:
        part.unlink(missing_ok=True)
        raise FFmpegDownloadError("İndirilen dosya çok küçük; bağlantı kesilmiş olabilir.")

    if target.exists():
        target.unlink(missing_ok=True)
    part.replace(target)


def _extract_binaries(
    archive: Path,
    destination: Path,
    progress_cb: ProgressCB = None,
    log_cb: LogCB = None,
) -> tuple[Path, Path]:
    """Zip icinden ffmpeg.exe ve ffprobe.exe'yi cikarir."""
    destination.mkdir(parents=True, exist_ok=True)
    if log_cb:
        log_cb("Arşiv açılıyor…")

    try:
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            wanted: dict[str, str] = {}
            for name in names:
                base = os.path.basename(name).lower()
                if base == EXE_NAME.lower():
                    wanted["ffmpeg"] = name
                elif base == PROBE_NAME.lower():
                    wanted["ffprobe"] = name

            if "ffmpeg" not in wanted or "ffprobe" not in wanted:
                raise FFmpegDownloadError(
                    "İndirilen arşivde ffmpeg.exe veya ffprobe.exe bulunamadı."
                )

            members = list(wanted.items())
            for index, (key, member) in enumerate(members):
                filename = EXE_NAME if key == "ffmpeg" else PROBE_NAME
                target = destination / filename
                with bundle.open(member) as source, open(target, "wb") as handle:
                    shutil.copyfileobj(source, handle, length=1024 * 512)
                if progress_cb:
                    progress_cb(0.9 + 0.1 * (index + 1) / len(members), "Arşiv açılıyor")
    except zipfile.BadZipFile as exc:
        raise FFmpegDownloadError(
            "İndirilen arşiv bozuk. İndirmeyi tekrar deneyin."
        ) from exc

    ffmpeg = destination / EXE_NAME
    probe = destination / PROBE_NAME
    for exe in (ffmpeg, probe):
        try:
            os.chmod(exe, 0o755)
        except OSError:
            pass
    return ffmpeg, probe


def download_ffmpeg(
    progress_cb: ProgressCB = None,
    log_cb: LogCB = None,
    cancel_event: threading.Event | None = None,
) -> FFmpegLocation:
    """FFmpeg'i indirir ve ffmpeg_utils icin hazir hale getirir."""
    destination = app_paths.ffmpeg_dir() / "bin"
    existing = find_existing()
    if existing is not None:
        return existing

    errors: list[str] = []
    for label, url in DOWNLOAD_MIRRORS:
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("İndirme iptal edildi.")
        if log_cb:
            log_cb(f"FFmpeg indiriliyor ({label})…")

        archive = Path(tempfile.mkdtemp(prefix="ffmpeg_dl_")) / "ffmpeg.zip"
        try:
            _download_to_file(url, archive, progress_cb, cancel_event)
            if log_cb:
                log_cb(f"İndirme tamamlandı ({archive.stat().st_size / (1024 ** 2):.1f} MB)")
            ffmpeg_exe, probe_exe = _extract_binaries(
                archive, destination, progress_cb, log_cb
            )
            if not _verify(str(ffmpeg_exe)):
                errors.append(f"{label}: çıkarılan ffmpeg çalıştırılamadı")
                continue
            if log_cb:
                log_cb(f"FFmpeg hazır: {ffmpeg_exe}")
            if progress_cb:
                progress_cb(1.0, "Hazır")
            return FFmpegLocation(str(ffmpeg_exe), str(probe_exe), f"otomatik indirildi ({label})")
        except CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: {exc}")
            if log_cb:
                log_cb(f"Bu kaynak başarısız: {label} — {exc}")
        finally:
            shutil.rmtree(archive.parent, ignore_errors=True)

    detail = "\n".join(f"  - {item}" for item in errors) or "  (bilinmeyen hata)"
    raise FFmpegDownloadError(
        "FFmpeg otomatik olarak indirilemedi.\n\n"
        f"Denenen kaynaklar:\n{detail}\n\n"
        "İnternet bağlantınızı kontrol edin veya FFmpeg'i elle kurun:\n"
        f"{DOWNLOAD_PAGE}\n\n"
        "Kurduktan sonra ayarlardan 'ffmpeg.exe Yolu Seç…' ile gösterebilirsiniz."
    )


def ensure_ffmpeg(
    explicit: str | None = None,
    allow_download: bool = True,
    progress_cb: ProgressCB = None,
    log_cb: LogCB = None,
    cancel_event: threading.Event | None = None,
) -> FFmpegLocation:
    """FFmpeg'i bulur; yoksa ve izin varsa indirir."""
    location = find_existing(explicit)
    if location is not None:
        return location

    if not allow_download:
        raise FFmpegNotFound(
            "FFmpeg bulunamadı.\n"
            f"İndirme sayfası: {DOWNLOAD_PAGE}"
        )

    return download_ffmpeg(progress_cb, log_cb, cancel_event)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
