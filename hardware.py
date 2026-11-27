"""Donanim bilgisi: fiziksel cekirdek, mantiksal islemci, RAM.

Whisper ve NLLB thread sayilari fiziksel cekirdege gore secilir. Mantiksal
islemci sayisi (hyper-threading) agir matris islerinde genellikle ek kazanc
saglamaz, bu yuzden varsayilan olarak kullanilmaz.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# En fazla bu kadar thread kullanilir; cok cekirdekli sunucularda
# bellek bant genisligi doyar ve ek thread kazanc getirmez.
MAX_THREADS_PER_MODEL = 16


@dataclass(frozen=True)
class HardwareInfo:
    physical_cores: int
    logical_cores: int
    ram_gb: float

    @property
    def pipeline_worthwhile(self) -> bool:
        """Whisper + NLLB paralel calisirken gercek kazanc var mi?

        6'dan az fiziksel cekirdekte iki model birbirinin thread'lerini
        calar; toplam sure kisalmaz, hatta uzayabilir.
        """
        return self.physical_cores >= 6

    def thread_budget(self, pipeline: bool) -> tuple[int, int]:
        """(whisper_threads, nllb_threads) dondurur."""
        cores = max(1, min(self.physical_cores, MAX_THREADS_PER_MODEL))
        if not pipeline:
            return cores, max(1, min(cores, 4))
        whisper = max(1, int(round(cores * 0.6)))
        nllb = max(1, cores - whisper)
        return whisper, nllb

    def describe(self) -> str:
        return (
            f"{self.physical_cores} fiziksel çekirdek / "
            f"{self.logical_cores} mantıksal işlemci, {self.ram_gb:.1f} GB RAM"
        )


def _logical_cores() -> int:
    return int(os.cpu_count() or 1)


def _physical_cores() -> int:
    try:
        import psutil

        value = psutil.cpu_count(logical=False)
        if value:
            return int(value)
    except Exception:
        pass

    if os.name == "nt":
        count = _win32_physical_cores()
        if count:
            return count

    # Son care: mantiksal sayinin yarisi (hyper-threading varsayimi).
    # Bu yalnizca tahmindir; yukaridaki yontemler basarisiz olduysa kullanilir.
    logical = _logical_cores()
    return max(1, logical // 2) if logical > 2 else logical


def _win32_physical_cores() -> int:
    """Windows API ile gercek fiziksel cekirdek sayisi (psutil gerekmez).

    GetLogicalProcessorInformationEx(RelationProcessorCore) her cekirdek icin
    bir kayit dondurur. Kayitlar degisken uzunluktadir; `Size` alani ile
    ilerlenir.
    """
    import ctypes

    relation_processor_core = 0
    length = ctypes.c_ulong(0)
    kernel32 = ctypes.windll.kernel32

    # Ilk cagri: gereken tampon boyutunu ogren.
    kernel32.GetLogicalProcessorInformationEx(
        relation_processor_core, None, ctypes.byref(length)
    )
    if not length.value:
        return 0

    buffer = ctypes.create_string_buffer(length.value)
    ok = kernel32.GetLogicalProcessorInformationEx(
        relation_processor_core, buffer, ctypes.byref(length)
    )
    if not ok:
        return 0

    return _count_cores_in_buffer(bytes(buffer.raw[: length.value]))


def _count_cores_in_buffer(data: bytes) -> int:
    """RELATION_PROCESSOR_CORE kayitlarini sayar."""
    import struct

    offset = 0
    count = 0
    total = len(data)
    while offset + 8 <= total:
        relationship, size = struct.unpack_from("<II", data, offset)
        if size < 8:
            break
        if relationship == 0:  # RelationProcessorCore
            count += 1
        offset += size
    return count or 1


def _ram_gb() -> float:
    try:
        import psutil

        return round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except Exception:
        pass

    if os.name == "nt":
        try:
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemStatus()
            status.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return round(status.ullTotalPhys / (1024 ** 3), 1)
        except Exception:
            pass
    return 0.0


_cached: HardwareInfo | None = None


def hardware_info(refresh: bool = False) -> HardwareInfo:
    global _cached
    if _cached is None or refresh:
        _cached = HardwareInfo(
            physical_cores=_physical_cores(),
            logical_cores=_logical_cores(),
            ram_gb=_ram_gb(),
        )
    return _cached


def ctranslate2_threads() -> int:
    """CTranslate2 icin thread sayisi (tek model)."""
    info = hardware_info()
    return max(1, min(info.physical_cores, MAX_THREADS_PER_MODEL))


def recommended_model_size() -> str:
    """Donanima gore onerilen Whisper modeli."""
    info = hardware_info()
    if info.physical_cores <= 2 or (info.ram_gb and info.ram_gb < 6):
        return "tiny"
    if info.physical_cores <= 4 or (info.ram_gb and info.ram_gb < 8):
        return "base"
    if info.physical_cores >= 8 and info.ram_gb >= 16:
        return "medium"
    return "small"


# Model basina yaklasik RAM ihtiyaci (MB). NLLB ceviri de hesaba katilir.
MODEL_RAM_MB = {
    "tiny": 110,
    "base": 180,
    "small": 400,
    "medium": 1550,
}
NLLB_RAM_MB = 820
# Windows + Python + Qt + tamponlar + FFmpeg alt sureci icin pay.
#
# Olculdu (bu depoda, 2026-11):
#   * Qt GUI acik + tiny + NLLB toplam surec RSS'i: 863 MB
#     (model tahminleri 930 MB; yani model paylari zaten muhafazakar)
#   * FFmpeg burn-in tepe RSS'i (1080p, crf 18): 164 MB (ayri surec)
#   * 10 dk'lik WAV dilimi: ~38 MB
# 1500 MB pay, 8 GB'lik bir makinede 1.5 GB bosken uygulamayi gereksiz yere
# reddediyordu (gercek ihtiyac ~1 GB). 400 MB, olculenin ~2 kati: buyuk
# videolarda FFmpeg'in sisip tamponlari artirmasi icin emniyet payi kalir.
OVERHEAD_RAM_MB = 400


def available_ram_mb() -> int:
    """Kullanilabilir (bos) fiziksel bellek, MB. Bilinmiyorsa 0."""
    try:
        import psutil

        return int(psutil.virtual_memory().available / (1024 ** 2))
    except Exception:
        pass

    if os.name == "nt":
        try:
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemStatus()
            status.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullAvailPhys / (1024 ** 2))
        except Exception:
            pass
    return 0


def check_memory(
    model_size: str,
    with_translation: bool = True,
    skip_whisper: bool = False,
    skip_nllb: bool = False,
    available_mb: int | None = None,
) -> tuple[bool, str]:
    """Secilen model icin yeterli RAM var mi?

    skip_whisper/skip_nllb: model zaten bellekte (kuyrukta yeniden kullanim);
    o modelin payi tekrar sayilmaz.

    available_mb: bos RAM'i disaridan vermek icin (testler). None ise
    sistemden olculur.

    (yeterli_mi, aciklama) dondurur. RAM olculemiyorsa iyimser davranir.
    """
    available = available_ram_mb() if available_mb is None else int(available_mb)
    if available <= 0:
        return True, "Bellek durumu okunamadı; devam ediliyor."

    need = 0
    if not skip_whisper:
        need += MODEL_RAM_MB.get(model_size, 400)
    if with_translation and not skip_nllb:
        need += NLLB_RAM_MB
    need += OVERHEAD_RAM_MB

    if available >= need:
        cached = []
        if skip_whisper:
            cached.append("Whisper")
        if skip_nllb:
            cached.append("NLLB")
        suffix = f" ({', '.join(cached)} zaten bellekte)" if cached else ""
        return True, (
            f"Bellek yeterli: {available} MB boş, ~{need} MB gerekli{suffix}."
        )

    gap = need - available
    return False, (
        f"Bellek yetersiz: {available} MB boş, ~{need} MB gerekli "
        f"(eksik ~{gap} MB).\n\n"
        f"Seçilen model: {model_size}\n"
        "Öneriler:\n"
        "  • Daha küçük Whisper modeli seçin (tiny/base)\n"
        "  • Diğer uygulamaları kapatın\n"
        "  • Çeviri gerekiyorsa NLLB modeli de bellekte kalır (~820 MB)"
    )


def memory_warning(model_size: str) -> str:
    """Engellemeyen uyari metni (RAM sinirda ise)."""
    available = available_ram_mb()
    if available <= 0:
        return ""
    need = MODEL_RAM_MB.get(model_size, 400) + NLLB_RAM_MB + OVERHEAD_RAM_MB
    if available >= need:
        return ""
    if model_size == "medium":
        return (
            f"Uyarı: '{model_size}' modeli CPU'da çok yavaş ve ~1.5 GB RAM ister. "
            f"Bu makinede {available} MB boş bellek var; takas (swap) başlayabilir. "
            "small/tiny önerilir."
        )
    return (
        f"Uyarı: boş bellek {available} MB, tahmini ihtiyaç ~{need} MB. "
        "İşlem yavaşlayabilir."
    )
