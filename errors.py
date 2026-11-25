"""Paylasilan istisna tipleri (dongusel import'u onlemek icin ayri modul)."""

from __future__ import annotations


class SubtraError(RuntimeError):
    """Uygulamaya ozgu tum hatalarin tabani."""


class FFmpegError(SubtraError):
    """FFmpeg/ffprobe ile ilgili hatalar."""


class FFmpegNotFound(FFmpegError):
    """FFmpeg hicbir yerde bulunamadi."""


class FFmpegDownloadError(FFmpegError):
    """Otomatik indirme basarisiz oldu."""


class CancelledError(SubtraError):
    """Kullanici islemi iptal etti."""


class ModelDownloadError(SubtraError):
    """Model indirilemediginde firlatilir."""


class TranslationError(SubtraError):
    """Ceviri ile ilgili hatalar."""


class NoSpeechError(SubtraError):
    """Videoda konusma bulunamadi."""
