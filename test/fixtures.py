"""Test fixture'ları — gerekirse otomatik üretilir.

Neden: video/ses dosyaları .gitignore'da (repoya girmiyor). Temiz bir klonda
testlerin çalışması için fixture'ı yerelde üretiyoruz.

Üretim sırası:
  1. Windows SAPI (PowerShell) ile İngilizce konuşma WAV'ı
  2. ffmpeg ile o WAV'ı 854x480 videoya çevir
  3. ffmpeg yoksa/başarısızsa: sessiz + ton karışımı (dil tespiti çalışmaz,
     testler SKIP verir)

Kullanım:
    from fixtures import require_video
    VIDEO = require_video()        # yoksa FixtureMissing fırlatır
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
PROJECT = TEST_DIR.parent

# Testler asla model indirmesin (yüzlerce MB sessizce inmesin).
# Model yoksa testler SKIP verir.
os.environ.setdefault("SUBTRA_NO_DOWNLOAD", "1")

VIDEO_NAME = "konusma ingilizce.mp4"
WAV_NAME = "_fixture_speech.wav"

SPEECH_TEXT = (
    "Hello and welcome. This is a test of the automatic subtitle system. "
    "The quick brown fox jumps over the lazy dog. "
    "Machine translation should handle these sentences correctly. "
    "Thank you for watching."
)

SKIP_CODE = 77


class FixtureMissing(RuntimeError):
    """Fixture üretilemedi; test atlanmalı."""


def video_path() -> Path:
    return TEST_DIR / VIDEO_NAME


def _ffmpeg() -> str | None:
    """Projede veya PATH'te ffmpeg arar."""
    import ffmpeg_bootstrap

    location = ffmpeg_bootstrap.find_existing()
    return location.ffmpeg if location else None


def _ffprobe() -> str | None:
    import ffmpeg_bootstrap

    location = ffmpeg_bootstrap.find_existing()
    return location.ffprobe if location else None


def _generate_speech_wav(target: Path) -> bool:
    """Windows SAPI ile İngilizce konuşma üretir."""
    if os.name != "nt":
        return False

    text = SPEECH_TEXT.replace("'", "''")
    script = f"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -like 'en-*' }}
if ($voices) {{ $s.SelectVoice($voices[0].VoiceInfo.Name) }}
$s.Rate = 0
$s.SetOutputToWaveFile('{target}')
$s.Speak('{text}')
$s.Dispose()
Write-Output 'OK'
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=180,
            creationflags=0x08000000,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    return result.returncode == 0 and target.exists() and target.stat().st_size > 10_000


def _build_video(ffmpeg: str, wav: Path, target: Path) -> bool:
    """WAV'ı sabit renkli videoya çevirir."""
    ffprobe = _ffprobe()
    duration = 15.0
    if ffprobe:
        try:
            out = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(wav)],
                capture_output=True, text=True, timeout=60,
                creationflags=0x08000000,
            )
            duration = float((out.stdout or "15").strip() or 15)
        except (OSError, subprocess.SubprocessError, ValueError):
            duration = 15.0

    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=0x202A44:s=854x480:d={duration:.2f}",
        "-i", str(wav),
        "-shortest",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        str(target),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            creationflags=0x08000000,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    return result.returncode == 0 and target.exists() and target.stat().st_size > 20_000


def ensure_video(force: bool = False, log=print) -> Path | None:
    """Test videosunu döndürür; yoksa üretmeye çalışır.

    Üretilemezse None döner (testler SKIP vermeli).
    """
    target = video_path()
    if target.exists() and not force and target.stat().st_size > 20_000:
        return target

    ffmpeg = _ffmpeg()
    if ffmpeg is None:
        log("  [fixture] ffmpeg bulunamadı; test videosu üretilemiyor.")
        return None

    wav = TEST_DIR / WAV_NAME
    log("  [fixture] konuşma üretiliyor (Windows SAPI)…")
    if not _generate_speech_wav(wav):
        log("  [fixture] SAPI ile konuşma üretilemedi (İngilizce ses yok?).")
        wav.unlink(missing_ok=True)
        return None

    log(f"  [fixture] video oluşturuluyor: {target.name}")
    ok = _build_video(ffmpeg, wav, target)
    wav.unlink(missing_ok=True)

    if not ok:
        log("  [fixture] video oluşturulamadı.")
        return None

    log(f"  [fixture] hazır: {target} ({target.stat().st_size / 1024:.0f} KB)")
    return target


def require_video(log=print) -> Path:
    """Video yolu veya FixtureMissing."""
    path = ensure_video(log=log)
    if path is None:
        raise FixtureMissing(
            "Test videosu yok ve üretilemedi.\n"
            "Üretmek için: py test/make_fixture.py"
        )
    return path


def require_srt(log=print) -> Path:
    """Basit bir SRT fixture'ı (video gerekmez)."""
    target = TEST_DIR / "_fixture.srt"
    if target.exists() and target.stat().st_size > 50:
        return target
    target.write_text(
        "1\n00:00:00,180 --> 00:00:04,400\n"
        "Hello and welcome. This is a test of the automatic subtitle system.\n\n"
        "2\n00:00:05,380 --> 00:00:08,200\n"
        "The quick brown fox jumps over the lazy dog.\n\n"
        "3\n00:00:08,800 --> 00:00:11,900\n"
        "Machine translation should handle these sentences correctly.\n\n"
        "4\n00:00:12,760 --> 00:00:14,300\n"
        "Thank you for watching.\n",
        encoding="utf-8",
    )
    return target


def skip(reason: str) -> int:
    """Testi SKIP olarak bitirir (exit 77)."""
    print(f"\n  SKIP: {reason}")
    print("  (test atlandı, hata değil)")
    return SKIP_CODE


def guard(callable_fn, *args, **kwargs):
    """FixtureMissing'i SKIP'e çeviren sarmalayıcı."""
    try:
        return callable_fn(*args, **kwargs)
    except FixtureMissing as exc:
        raise SystemExit(skip(str(exc)))
