"""Hata raporu olusturma: kullanici tek tusla kopyalayip paylasabilsin.

Rapora hassas bilgi konmaz: dosya yollari kullanici adini icerebilir, bu
yuzden yol bilgisi ayri ve istege bagli bir bolumde verilir.
"""

from __future__ import annotations

import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path

import app_paths
import logging_setup
from hardware import hardware_info

APP_VERSION = "2.0.0"
SEPARATOR = "=" * 70


def _safe(value, default: str = "?") -> str:
    try:
        text = str(value).strip()
        return text or default
    except Exception:
        return default


def app_version() -> str:
    return APP_VERSION


def _python_version() -> str:
    return f"{platform.python_version()} ({platform.architecture()[0]})"


def _windows_version() -> str:
    try:
        release = platform.release()
        version = platform.version()
        build = sys.getwindowsversion()
        return f"Windows {release} {version} (build {build.build})"
    except Exception:
        return "Windows (bilinmiyor)"


def _ffmpeg_summary() -> str:
    try:
        import ffmpeg_bootstrap

        return ffmpeg_bootstrap.describe_ffmpeg()
    except Exception as exc:
        return f"FFmpeg bilgisi alınamadı: {exc}"


def _models_summary() -> str:
    try:
        import transcriber
        import translator

        lines: list[str] = []
        root = app_paths.resolve_models_dir()
        lines.append(f"Klasör: {root}")
        for size in ("tiny", "base", "small", "medium"):
            if transcriber.is_whisper_cached(root, size):
                lines.append(f"  Whisper {size}: var")
        if translator.is_nllb_cached(root):
            lines.append("  NLLB 600M int8: var")
        if len(lines) == 1:
            lines.append("  (önbellekte model yok)")
        return "\n".join(lines)
    except Exception as exc:
        return f"Model bilgisi alınamadı: {exc}"


def _settings_summary(settings) -> str:
    if settings is None:
        return "(ayar bilgisi yok)"
    keys = [
        "model_size",
        "target_lang",
        "output_mode",
        "font_size",
        "subtitle_position",
        "max_cps",
        "word_timestamps",
        "pipeline_mode",
        "cpu_threads",
    ]
    lines = []
    for key in keys:
        try:
            value = settings.value(key, None)
        except Exception:
            value = None
        if value is not None:
            lines.append(f"  {key} = {value}")
    return "\n".join(lines) or "(kayıtlı ayar yok)"


def build_report(
    error_text: str | None = None,
    settings=None,
    extra: str | None = None,
    include_paths: bool = False,
) -> str:
    """Metin formatinda hata raporu uretir."""
    info = hardware_info()
    lines: list[str] = []

    lines.append(SEPARATOR)
    lines.append(f"Subtra Hata Raporu — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(SEPARATOR)
    lines.append("")
    lines.append("[Sürüm]")
    lines.append(f"  Uygulama: {app_version()}")
    lines.append(f"  Çalışma biçimi: {'exe (frozen)' if app_paths.is_frozen() else 'kaynak kod'}")
    lines.append("")
    lines.append("[Sistem]")
    lines.append(f"  İşletim sistemi: {_windows_version()}")
    lines.append(f"  Python: {_python_version()}")
    lines.append(f"  Donanım: {info.describe()}")
    lines.append(f"  Pipeline uygun: {'evet' if info.pipeline_worthwhile else 'hayır'}")
    lines.append(f"  Thread bütçesi (tek): {info.thread_budget(False)}")
    lines.append(f"  Thread bütçesi (pipeline): {info.thread_budget(True)}")
    lines.append("")
    lines.append("[FFmpeg]")
    for line in _ffmpeg_summary().splitlines():
        lines.append(f"  {line}")
    lines.append("")
    lines.append("[Modeller]")
    for line in _models_summary().splitlines():
        lines.append(f"  {line}")
    lines.append("")
    lines.append("[Ayarlar]")
    lines.append(_settings_summary(settings))
    lines.append("")

    if error_text:
        lines.append("[Hata]")
        lines.append(error_text.strip())
        lines.append("")

    if extra:
        lines.append("[Ek bilgi]")
        lines.append(extra.strip())
        lines.append("")

    if include_paths:
        lines.append("[Yollar]")
        lines.append(f"  Veri: {app_paths.data_dir()}")
        lines.append(f"  Log: {logging_setup.log_file_path()}")
        lines.append("")

    lines.append("[Son log satırları]")
    lines.append(logging_setup.read_log_tail(200))
    lines.append("")
    lines.append(SEPARATOR)
    return "\n".join(lines)


def format_exception(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def save_report(text: str, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target
