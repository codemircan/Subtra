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
        try:
            import ctypes

            # GetLogicalProcessorInformationEx(RelationProcessorCore)
            # araciligiyla gercek cekirdek sayisi.
            relation_processor_core = 0
            length = ctypes.wintypes.DWORD(0)
            kernel32 = ctypes.windll.kernel32
            kernel32.GetLogicalProcessorInformationEx(
                relation_processor_core, None, ctypes.byref(length)
            )
            if length.value:
                buffer = ctypes.create_string_buffer(length.value)
                if kernel32.GetLogicalProcessorInformationEx(
                    relation_processor_core, buffer, ctypes.byref(length)
                ):
                    return _count_cores_in_buffer(bytes(buffer.raw[: length.value]))
        except Exception:
            pass

    logical = _logical_cores()
    return max(1, logical // 2) if logical > 2 else logical


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
