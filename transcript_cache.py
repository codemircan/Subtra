"""Transkript önbelleği.

Neden: Whisper CPU'da pahalıdır (bu makinede `small` ile 1 saatlik video
~55 dk). Aynı videoyu ikinci bir dile çevirmek transkripti yeniden çıkarmak
zorunda değil. Transkript bir kez üretilip diske yazılır, sonraki diller
doğrudan onu kullanır.

Tasarım:
  * Anahtar: dosya yolu + boyut + mtime + Whisper modeli + kelime damgası.
    Video değişirse (boyut/mtime) önbellek geçersiz olur.
  * Biçim JSON (okunabilir, sürüm alanı ile ileriye dönük).
  * Konum: çıktının yanına değil, veri klasöründe (`cache/transcripts/`),
    böylece kullanıcının video klasörü kirlenmez ve .gitignore'da kalır.
  * Yazma atomik: önce `.tmp`, sonra `replace`. Yarım dosya okunmaz.

Kullanım:
    key = cache_key(video, model_size, word_timestamps)
    hit = load(key, cache_dir)
    if hit is None: ... transkript ...
    save(key, cache_dir, meta, words)
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime
from pathlib import Path

# Şema sürümü: kelime/segment yapısı değişirse artırılır, eski önbellek yok sayılır.
SCHEMA_VERSION = 1

_LOCK = threading.Lock()


def _stat_stamp(path: Path) -> dict:
    try:
        stat = path.stat()
        return {"size": stat.st_size, "mtime": int(stat.st_mtime)}
    except OSError:
        return {"size": 0, "mtime": 0}


def cache_key(
    video: str | Path,
    model_size: str,
    word_timestamps: bool = True,
    extra: str = "",
) -> str:
    """Önbellek anahtarı (dosya adı olarak güvenli hex)."""
    path = Path(video)
    stamp = _stat_stamp(path)
    payload = "|".join(
        [
            str(path.resolve()).lower(),
            str(stamp["size"]),
            str(stamp["mtime"]),
            model_size,
            "wt" if word_timestamps else "nowt",
            extra,
            f"v{SCHEMA_VERSION}",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def cache_path(key: str, cache_dir: str | Path) -> Path:
    return Path(cache_dir) / f"{key}.json"


def load(key: str, cache_dir: str | Path) -> dict | None:
    """Önbellekten yükler; yoksa/bozuksa None."""
    path = cache_path(key, cache_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return None
    words = data.get("words")
    if not isinstance(words, list) or not words:
        return None
    return data


def save(
    key: str,
    cache_dir: str | Path,
    meta: dict,
    words: list[dict],
    source_name: str = "",
    elapsed: float = 0.0,
) -> Path | None:
    """Transkripti diske yazar (atomik). Hata durumunda None."""
    if not words:
        return None

    directory = Path(cache_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    payload = {
        "schema": SCHEMA_VERSION,
        "created": datetime.now().isoformat(timespec="seconds"),
        "source": source_name,
        "language": meta.get("language", ""),
        "language_probability": meta.get("language_probability", 0.0),
        "duration": meta.get("duration", 0.0),
        "model": meta.get("model", ""),
        "word_timestamps": bool(meta.get("word_timestamps", True)),
        "transcribe_seconds": round(float(elapsed), 2),
        "words": words,
    }

    target = cache_path(key, directory)
    tmp = target.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    return target


def is_usable(data: dict, require_word_timestamps: bool = True) -> bool:
    """Önbellek kaydı bu çalıştırma için yeterli mi?

    Kelime damgası isteniyorsa ama önbellekte yoksa kullanılamaz: bölme
    kalitesi düşer. Bu durumda transkripsiyon yeniden çalıştırılır.
    """
    if data is None:
        return False
    words = data.get("words") or []
    if not words:
        return False
    if not require_word_timestamps:
        return True
    return bool(data.get("word_timestamps")) and all(word.get("start") is not None for word in words[:5])


def info(key: str, cache_dir: str | Path) -> dict | None:
    """Önbellek kaydının özeti (log mesajı için)."""
    data = load(key, cache_dir)
    if data is None:
        return None
    return {
        "created": data.get("created", "?"),
        "language": data.get("language", "?"),
        "words": len(data.get("words", [])),
        "transcribe_seconds": data.get("transcribe_seconds", 0),
        "model": data.get("model", "?"),
    }


def clear(cache_dir: str | Path) -> int:
    """Tüm transkript önbelleğini siler; silinen dosya sayısını döndürür."""
    directory = Path(cache_dir)
    if not directory.exists():
        return 0
    removed = 0
    for path in directory.glob("*.json"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def total_size(cache_dir: str | Path) -> int:
    directory = Path(cache_dir)
    if not directory.exists():
        return 0
    total = 0
    for path in directory.glob("*.json"):
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def prune(cache_dir: str | Path, keep_newest: int = 20) -> int:
    """En yeni `keep_newest` kaydı tutar, kalanını siler."""
    directory = Path(cache_dir)
    if not directory.exists():
        return 0
    files = []
    for path in directory.glob("*.json"):
        try:
            files.append((path.stat().st_mtime, path))
        except OSError:
            continue
    files.sort(reverse=True)
    removed = 0
    for _, path in files[keep_newest:]:
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed
