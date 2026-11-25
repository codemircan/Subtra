"""faster-whisper model indirme, yukleme ve parcali transkripsiyon.

Uzun videolarda bellek kullanimini sabit tutmak icin ses, 16 kHz mono WAV
uzerinden 10 dakikalik dilimler halinde okunur. Her dilimde iptal kontrolu
yapilir; boylece iptal cok daha hizli sonuclanir.

Dil, ilk dilimde otomatik tespit edilir ve kalan dilimlerde sabitlenir.
Baglam, `initial_prompt` ile dilimler arasinda tasinir.
"""

from __future__ import annotations

import os
import shutil
import threading
import wave
from pathlib import Path
from typing import Callable, Iterator, Optional

from errors import CancelledError, ModelDownloadError

WHISPER_REPOS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
}

# faster-whisper'in ihtiyac duydugu dosyalar.
WHISPER_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
MANDATORY_FILES = ("config.json", "model.bin")

MODEL_APPROX_MB = {
    "tiny": 75,
    "base": 145,
    "small": 484,
    "medium": 1530,
}

SAMPLE_RATE = 16000
CHUNK_SECONDS = 600.0      # 10 dakika
OVERLAP_SECONDS = 1.0
SKIP_AFTER_OVERLAP = 0.5   # yeni dilimde bu kadar erken kelimeler atilir

HF_RESOLVE = "https://huggingface.co/{repo}/resolve/main/{name}"

ProgressCB = Optional[Callable[[float], None]]
LogCB = Optional[Callable[[str], None]]


# --------------------------------------------------------------------------
# Genel Hugging Face indirici (translator.py de kullanir)
# --------------------------------------------------------------------------

def download_repo_files(
    repo_id: str,
    files: tuple[str, ...] | list[str],
    dest_dir: str | Path,
    progress_cb: ProgressCB = None,
    log_cb: LogCB = None,
    cancel_event: threading.Event | None = None,
    mandatory: tuple[str, ...] = MANDATORY_FILES,
) -> Path:
    """Belirtilen dosyalari Hugging Face deposundan indirir.

    Ilerleme 0..1 araliginda bildirilir. Var olan ve boyutu dogru dosyalar
    yeniden indirilmez.
    """
    try:
        import requests
    except ImportError as exc:  # pragma: no cover
        raise ModelDownloadError(
            "İndirme için 'requests' paketi gerekli. "
            "Kurulum: py -m pip install requests"
        ) from exc

    dest = Path(dest_dir)
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ModelDownloadError(
            f"Model klasörü oluşturulamadı:\n{dest}\n{exc}"
        ) from exc

    session = requests.Session()
    session.headers.update({"User-Agent": "Subtra/2.0"})

    entries: list[tuple[str, str, int]] = []
    total_bytes = 0
    for name in files:
        url = HF_RESOLVE.format(repo=repo_id, name=name)
        try:
            head = session.head(url, allow_redirects=True, timeout=45)
        except requests.RequestException as exc:
            raise ModelDownloadError(
                "Model sunucusuna ulaşılamadı. İnternet bağlantınızı kontrol edin.\n"
                f"Depo: {repo_id}\n{exc}"
            ) from exc

        if head.status_code == 404:
            if name in mandatory:
                raise ModelDownloadError(
                    f"Model deposunda '{name}' dosyası bulunamadı.\nDepo: {repo_id}"
                )
            continue
        if head.status_code >= 400:
            raise ModelDownloadError(
                f"Model dosyası alınamadı: {name} (HTTP {head.status_code})\nDepo: {repo_id}"
            )

        try:
            size = int(head.headers.get("Content-Length") or 0)
        except ValueError:
            size = 0
        entries.append((name, url, size))
        total_bytes += size

    if not entries:
        raise ModelDownloadError(f"Model deposunda indirilecek dosya yok: {repo_id}")

    if log_cb:
        log_cb(f"Model indiriliyor: {repo_id} (~{total_bytes / (1024 ** 2):.0f} MB)")

    done_bytes = 0
    for name, url, size in entries:
        target = dest / name
        if target.exists() and size and target.stat().st_size == size:
            done_bytes += size
            if progress_cb and total_bytes:
                progress_cb(min(1.0, done_bytes / total_bytes))
            continue

        part = dest / (name + ".part")
        if log_cb:
            log_cb(f"  indiriliyor: {name}")
        written = 0
        try:
            with session.get(url, stream=True, timeout=120) as response:
                response.raise_for_status()
                with open(part, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if cancel_event is not None and cancel_event.is_set():
                            raise CancelledError("İndirme iptal edildi.")
                        if not chunk:
                            continue
                        handle.write(chunk)
                        written += len(chunk)
                        if progress_cb and total_bytes:
                            progress_cb(min(0.99, (done_bytes + written) / total_bytes))
        except CancelledError:
            _safe_unlink(part)
            raise
        except OSError:
            _safe_unlink(part)
            raise
        except Exception as exc:
            _safe_unlink(part)
            raise ModelDownloadError(
                f"'{name}' indirilirken hata oluştu.\n{exc}"
            ) from exc

        try:
            if target.exists():
                target.unlink()
            part.replace(target)
        except OSError as exc:
            _safe_unlink(part)
            raise ModelDownloadError(
                f"'{name}' dosyası yazılamadı (disk dolu veya izin yok).\n{exc}"
            ) from exc

        done_bytes += written or size
        if progress_cb and total_bytes:
            progress_cb(min(1.0, done_bytes / total_bytes))

    if progress_cb:
        progress_cb(1.0)
    return dest


def _normalise_token(text: str) -> str:
    return (text or "").strip().strip(".,!?…。！？؟।;:—–\"'()").lower()


def _duplicate_prefix_len(new_words: list[dict], recent: list[dict], max_check: int = 10) -> int:
    """Yeni dilimin basindaki, onceki dilimin sonuyla ayni olan kelime sayisi."""
    if not new_words or not recent:
        return 0
    limit = min(max_check, len(new_words), len(recent))
    for size in range(limit, 0, -1):
        tail = [_normalise_token(w["text"]) for w in recent[-size:]]
        head = [_normalise_token(w["text"]) for w in new_words[:size]]
        if tail == head and any(tail):
            return size
    return 0


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass



# --------------------------------------------------------------------------
# Whisper modeli
# --------------------------------------------------------------------------

def whisper_model_dir(models_root: str | Path, size: str) -> Path:
    return Path(models_root) / f"faster-whisper-{size}"


def is_whisper_cached(models_root: str | Path, size: str) -> bool:
    directory = whisper_model_dir(models_root, size)
    model_bin = directory / "model.bin"
    return (
        (directory / "config.json").exists()
        and (directory / "tokenizer.json").exists()
        and model_bin.exists()
        and model_bin.stat().st_size > 1024 * 1024
    )


def cached_whisper_models(models_root: str | Path) -> list[str]:
    return [size for size in WHISPER_REPOS if is_whisper_cached(models_root, size)]


def ensure_whisper_model(
    size: str,
    models_root: str | Path,
    progress_cb: ProgressCB = None,
    log_cb: LogCB = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Model cache'te varsa yolunu dondurur, yoksa indirir."""
    if size not in WHISPER_REPOS:
        raise ModelDownloadError(f"Bilinmeyen Whisper modeli: {size}")

    directory = whisper_model_dir(models_root, size)
    if is_whisper_cached(models_root, size):
        if log_cb:
            log_cb(f"Whisper '{size}' modeli önbellekte bulundu (offline).")
        if progress_cb:
            progress_cb(1.0)
        return directory

    if log_cb:
        log_cb(f"Whisper '{size}' modeli indirilecek (yalnızca ilk kullanım).")

    download_repo_files(
        WHISPER_REPOS[size],
        WHISPER_FILES,
        directory,
        progress_cb=progress_cb,
        log_cb=log_cb,
        cancel_event=cancel_event,
        mandatory=MANDATORY_FILES,
    )

    if not is_whisper_cached(models_root, size):
        raise ModelDownloadError(
            "Whisper modeli indirildi ancak doğrulanamadı.\n"
            f"Klasör: {directory}"
        )
    return directory


def load_whisper_model(
    model_dir: str | Path,
    cpu_threads: int | None = None,
    num_workers: int = 1,
):
    """Modeli CPU + int8 olarak yukler (tamamen offline)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "faster-whisper kurulu değil. Kurulum: py -m pip install faster-whisper"
        ) from exc

    directory = Path(model_dir)
    if not directory.exists():
        raise RuntimeError(f"Whisper model klasörü yok: {directory}")

    if cpu_threads is None:
        from hardware import hardware_info

        cpu_threads = hardware_info().thread_budget(False)[0]
    cpu_threads = max(1, int(cpu_threads))
    num_workers = max(1, int(num_workers))

    try:
        return WhisperModel(
            str(directory),
            device="cpu",
            compute_type="int8",
            cpu_threads=cpu_threads,
            num_workers=num_workers,
            local_files_only=True,
        )
    except Exception as exc:
        raise RuntimeError(
            "Whisper modeli yüklenemedi. Model dosyaları bozuk olabilir; "
            f"'{directory}' klasörünü silip tekrar deneyin.\n{exc}"
        ) from exc


# --------------------------------------------------------------------------
# Ses okuma
# --------------------------------------------------------------------------

def _open_wav(wav_path: str | Path) -> wave.Wave_read:
    handle = wave.open(str(wav_path), "rb")
    channels = handle.getnchannels()
    width = handle.getsampwidth()
    rate = handle.getframerate()
    if channels != 1 or width != 2 or rate != SAMPLE_RATE:
        handle.close()
        raise RuntimeError(
            "Geçici ses dosyası beklenen biçimde değil "
            f"(kanal={channels}, genişlik={width * 8} bit, hız={rate} Hz)."
        )
    return handle


def wav_duration(wav_path: str | Path) -> float:
    with _open_wav(wav_path) as handle:
        return handle.getnframes() / float(handle.getframerate())


def iter_audio_chunks(
    wav_path: str | Path,
    chunk_seconds: float = CHUNK_SECONDS,
    overlap_seconds: float = OVERLAP_SECONDS,
) -> Iterator[tuple[float, object, float]]:
    """WAV dosyasini float32 dilimler halinde uretir.

    (offset_saniye, numpy_dizi, dilim_suresi) dondurur.
    """
    import numpy as np

    with _open_wav(wav_path) as handle:
        rate = handle.getframerate()
        total_frames = handle.getnframes()
        chunk_frames = max(1, int(chunk_seconds * rate))
        overlap_frames = max(0, int(overlap_seconds * rate))
        step = max(1, chunk_frames - overlap_frames)

        position = 0
        while position < total_frames:
            handle.setpos(position)
            frames = handle.readframes(chunk_frames)
            samples = np.frombuffer(frames, dtype=np.int16)
            if samples.size == 0:
                break
            audio = samples.astype(np.float32) / 32768.0
            offset = position / float(rate)
            yield offset, audio, len(audio) / float(rate)
            if position + chunk_frames >= total_frames:
                break
            position += step


def load_wav_as_float32(wav_path: str | Path):
    """WAV dosyasini tek parca float32 dizisine cevirir (kucuk dosyalar)."""
    import numpy as np

    with _open_wav(wav_path) as handle:
        frames = handle.readframes(handle.getnframes())
    samples = np.frombuffer(frames, dtype=np.int16)
    if samples.size == 0:
        raise RuntimeError("Geçici ses dosyası boş.")
    return samples.astype(np.float32) / 32768.0


# --------------------------------------------------------------------------
# Transkripsiyon
# --------------------------------------------------------------------------

def transcribe_audio(
    model,
    wav_path: str | Path,
    duration: float,
    progress_cb: ProgressCB = None,
    cancel_event: threading.Event | None = None,
    word_timestamps: bool = True,
    beam_size: int = 5,
    chunk_seconds: float = CHUNK_SECONDS,
    sentence_cb: Callable[[dict], None] | None = None,
    language_cb: Callable[[str, float], None] | None = None,
) -> tuple[dict, list[dict]]:
    """Ses dosyasini parcali olarak metne cevirir.

    (meta, segments) dondurur. Her segment `words` anahtari tasir; bu
    alan kelime zaman damgalarini icerir.

    `sentence_cb` verilirse cumleler olustukca bu fonksiyona iletilir; boylece
    ceviri transkripsiyon surerken baslayabilir (pipeline).
    """
    total = float(duration or wav_duration(wav_path) or 0.0)
    segments: list[dict] = []
    detected_language: str | None = None
    language_probability = 0.0
    prompt: str | None = None
    last_reported = -1

    sentence_buffer: list[dict] = []
    sentence_start = 1.0
    recent_words: list[dict] = []
    max_sentence_chars = 400
    max_sentence_seconds = 20.0
    max_sentence_words = 60

    def emit_sentence(force: bool = False) -> None:
        nonlocal sentence_buffer, sentence_start
        if not sentence_buffer:
            return
        text = " ".join(item["text"] for item in sentence_buffer).strip()
        if not text:
            sentence_buffer = []
            return
        if sentence_cb is not None:
            sentence_cb(
                {
                    "text": text,
                    "start": float(sentence_buffer[0]["start"]),
                    "end": float(sentence_buffer[-1]["end"]),
                    "words": list(sentence_buffer),
                }
            )
        sentence_buffer = []

    def feed_words(words: list[dict]) -> None:
        nonlocal sentence_buffer, sentence_start
        for word in words:
            if not sentence_buffer:
                sentence_start = float(word["start"])
            sentence_buffer.append(word)
            joined = len(" ".join(item["text"] for item in sentence_buffer))
            ended = (word["text"] or "").strip()[-1:] in ".!?…。！？؟।"
            if (
                ended
                or joined >= max_sentence_chars
                or (word["end"] - sentence_start) >= max_sentence_seconds
                or len(sentence_buffer) >= max_sentence_words
            ):
                emit_sentence()


    def report(fraction: float) -> None:
        nonlocal last_reported
        if progress_cb is None:
            return
        value = max(0, min(99, int(fraction * 100)))
        if value != last_reported:
            last_reported = value
            progress_cb(min(0.99, max(0.0, fraction)))

    for offset, audio, chunk_length in iter_audio_chunks(wav_path, chunk_seconds):
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("Transkripsiyon iptal edildi.")

        kwargs = dict(
            task="transcribe",
            language=detected_language,   # ilk dilimde None -> otomatik tespit
            beam_size=beam_size,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 200},
            condition_on_previous_text=False,
            word_timestamps=word_timestamps,
        )
        if prompt:
            kwargs["initial_prompt"] = prompt

        try:
            segment_iter, info = model.transcribe(audio, **kwargs)
        except Exception as exc:
            raise RuntimeError(f"Transkripsiyon başlatılamadı: {exc}") from exc

        if detected_language is None:
            detected_language = str(getattr(info, "language", "") or "") or None
            language_probability = float(getattr(info, "language_probability", 0.0) or 0.0)
            if language_cb is not None and detected_language:
                language_cb(detected_language, language_probability)

        chunk_start = offset
        chunk_words: list[dict] = []

        for segment in segment_iter:
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError("Transkripsiyon iptal edildi.")

            words: list[dict] = []
            raw_words = getattr(segment, "words", None) or []
            for word in raw_words:
                word_text = (getattr(word, "word", "") or "").strip()
                if not word_text:
                    continue
                start = offset + float(getattr(word, "start", 0.0))
                end = offset + float(getattr(word, "end", start))
                words.append(
                    {
                        "text": word_text,
                        "start": start,
                        "end": max(end, start + 0.02),
                        "probability": float(getattr(word, "probability", 0.0) or 0.0),
                    }
                )

            text = (segment.text or "").strip()
            if not text and not words:
                continue

            start = offset + float(segment.start)
            end = offset + float(segment.end)
            chunk_words.append(
                {
                    "start": start,
                    "end": end,
                    "text": text,
                    "words": words,
                }
            )

        # Dilim sinirinda tekrar eden kelimeleri at.
        words_flat = [word for segment in chunk_words for word in segment["words"]]
        if offset > 0 and words_flat:
            drop = _duplicate_prefix_len(words_flat, recent_words)
            if drop:
                drop_ids = {id(word) for word in words_flat[:drop]}
                for segment in chunk_words:
                    kept = [w for w in segment["words"] if id(w) not in drop_ids]
                    if len(kept) != len(segment["words"]):
                        segment["words"] = kept
                        segment["text"] = " ".join(w["text"] for w in kept).strip()
                # Basindaki bos segmentleri temizle.
                chunk_words = [
                    segment for segment in chunk_words
                    if segment["words"] or segment["text"]
                ]

        for segment in chunk_words:
            if not segment["text"] and not segment["words"]:
                continue
            segments.append(segment)
            feed_words(segment["words"])
            recent_words.extend(segment["words"])
            if len(recent_words) > 40:
                del recent_words[:-40]
            prompt = " ".join(item["text"] for item in segment["words"][-12:]) or segment["text"] or prompt

        report(min(1.0, (offset + chunk_length) / total) if total else 0.0)

    emit_sentence(force=True)

    if progress_cb:
        progress_cb(1.0)

    meta = {
        "language": detected_language or "",
        "language_probability": language_probability,
        "duration": total,
        "chunk_seconds": chunk_seconds,
    }
    return meta, segments


def flatten_words(segments: list[dict]) -> list[dict]:
    """Segmentlerdeki kelimeleri tek listeye indirger (sirali, tekrarsiz)."""
    words: list[dict] = []
    for segment in segments:
        for word in segment.get("words") or []:
            text = (word.get("text") or "").strip()
            if not text:
                continue
            entry = {
                "text": text,
                "start": float(word.get("start", 0.0)),
                "end": float(word.get("end", 0.0)),
            }
            if words and entry["start"] < words[-1]["end"] - 0.25:
                continue  # ortusme kaynakli tekrar
            words.append(entry)
    return words


def clear_model_cache(models_root: str | Path) -> None:
    """Tum modelleri siler."""
    root = Path(models_root)
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
