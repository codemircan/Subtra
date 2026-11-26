"""Arka plan is akisi: model onbellegi, tek is calistirici ve kuyruk.

Mimari:
  * `ModelCache`  — Whisper ve NLLB modellerini yukler ve isler arasinda
                    bellekte tutar (kuyrukta en buyuk hiz kazanci).
  * `JobRunner`   — tek bir video/SRT isini uctan uca yurutur.
  * `VideoWorker` — tek is icin QThread sarmalayici (arayuz sinyalleri).
  * `BatchWorker` — sirali kuyruk isleyicisi, ayni modelleri paylasir.

Tum agir islemler QThread icinde calisir; arayuz donmaz.
"""

from __future__ import annotations

import errno
import os
import shutil
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Signal

import app_paths
import ffmpeg_utils
import subtitles as subtitles_mod
import transcript_cache
from errors import (
    CancelledError,
    FFmpegError,
    ModelDownloadError,
    NoSpeechError,
    TranslationError,
    SubtraError,
)
from ffmpeg_utils import SubtitleStyle
from hardware import hardware_info
from languages import TARGET_LANGUAGES, language_label, whisper_to_nllb
from transcriber import (
    cached_whisper_models,
    ensure_whisper_model,
    flatten_words,
    load_whisper_model,
    transcribe_audio,
)
from translator import (
    NllbTranslator,
    TranslationPipeline,
    ensure_nllb_model,
    is_nllb_cached,
    resolve_languages,
    translate_sentences,
)

SUPPORTED_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}

# Asama yuzdeleri
P_PREPARE_END = 3
P_AUDIO_END = 8
P_WHISPER_MODEL_END = 12
P_TRANSCRIBE_END = 55
P_NLLB_MODEL_END = 60
P_TRANSLATE_END = 78
P_SRT_END = 81
P_RENDER_END = 100


# --------------------------------------------------------------------------
# Ayarlar
# --------------------------------------------------------------------------

@dataclass
class JobSettings:
    input_path: str
    model_size: str = "small"
    target_lang: str = "tr"
    output_mode: str = "burn"  # burn | soft | srt
    style: SubtitleStyle = field(default_factory=SubtitleStyle)
    ffmpeg_path: str = ""
    models_dir: str = ""
    keep_temp: bool = False
    max_cps: float = 18.0
    word_timestamps: bool = True
    pipeline_mode: str = "auto"       # auto | on | off
    cpu_threads: int = 0              # 0 = otomatik
    num_workers: int = 1
    burn_crf: int = 18                # burn-in kalite (dusuk = daha iyi/buyuk)
    batch_size: int = 0               # Whisper batched inference (0/1 = kapali)
    use_transcript_cache: bool = True  # transkript onbellegi kullan
    input_srt: str = ""               # dolu ise transkripsiyon atlanir
    source_lang: str = ""             # SRT ice aktarmada kaynak dil (bos = tahmin)
    output_stem: str = ""             # dolu ise cikti adi bu tabandan uretilir
    overwrite: bool = True            # var olan ciktinin uzerine yazilsin mi

    def resolved_pipeline(self) -> bool:
        if self.pipeline_mode == "on":
            return True
        if self.pipeline_mode == "off":
            return False
        return hardware_info().pipeline_worthwhile

    def thread_budget(self) -> tuple[int, int]:
        info = hardware_info()
        if self.cpu_threads and self.cpu_threads > 0:
            whisper = max(1, int(self.cpu_threads))
            nllb = max(1, int(round(whisper * 0.6)))
            return whisper, nllb
        return info.thread_budget(self.resolved_pipeline())

    def base_path(self) -> Path:
        if self.input_srt:
            return Path(self.input_srt).with_suffix("")
        return Path(self.input_path).with_suffix("")

    def output_base(self) -> Path:
        """Cikti dosya adi tabani: <ad>_<hedef_dil>.

        Hedef dil eki dile gore degisir (or. _tr, _en, _de). Boylece ayni
        video farkli dillere cevrilirken dosyalar birbirinin uzerine yazmaz.
        Onceki calistirmadan kalan dil eki temizlenir; "_tr_tr" olusmaz.
        """
        from languages import known_suffixes, target_suffix

        source = Path(self.input_path) if self.input_path else Path(self.input_srt)
        suffix = target_suffix(self.target_lang)
        stem = source.stem

        base = stem
        for candidate in known_suffixes():
            if base.lower().endswith(candidate.lower()) and len(base) > len(candidate):
                base = base[: -len(candidate)]
                break

        name = base + suffix

        # Cikti hicbir zaman kaynak dosyanin kendisi olmamali (veri kaybi).
        # Or. film_tr.srt -> Turkce, veya film_en.mp4 -> Ingilizce.
        if name.lower() == stem.lower():
            name = base + suffix + "_2"

        return source.with_name(name)


# --------------------------------------------------------------------------
# Model onbellegi
# --------------------------------------------------------------------------

class ModelCache:
    """Whisper ve NLLB modellerini yukler ve yeniden kullanir."""

    def __init__(self, models_root: str | Path, log_cb: Callable[[str], None] | None = None) -> None:
        self.models_root = Path(models_root)
        self._log = log_cb or (lambda message: None)
        self._whisper = None
        self._whisper_key: tuple[str, int, int] | None = None
        self._nllb: NllbTranslator | None = None
        self._nllb_threads: int | None = None
        self._lock = threading.Lock()

    # -- whisper -----------------------------------------------------------
    def whisper(self, size: str, threads: int, num_workers: int = 1, progress_cb=None, log_cb=None, cancel_event=None):
        key = (size, int(threads), int(num_workers))
        with self._lock:
            if self._whisper is not None and self._whisper_key == key:
                self._log("Whisper modeli önbellekten kullanılıyor.")
                if progress_cb:
                    progress_cb(1.0)
                return self._whisper

            directory = ensure_whisper_model(
                size,
                self.models_root,
                progress_cb=progress_cb,
                log_cb=log_cb or self._log,
                cancel_event=cancel_event,
            )
            self.release_whisper()
            model = load_whisper_model(directory, cpu_threads=threads, num_workers=num_workers)
            self._whisper = model
            self._whisper_key = key
            return model

    def release_whisper(self) -> None:
        self._whisper = None
        self._whisper_key = None

    # -- nllb --------------------------------------------------------------
    def nllb(self, threads: int, progress_cb=None, log_cb=None, cancel_event=None) -> NllbTranslator:
        with self._lock:
            if self._nllb is not None and self._nllb_threads == int(threads):
                self._log("Çeviri modeli önbellekten kullanılıyor.")
                if progress_cb:
                    progress_cb(1.0)
                return self._nllb

            directory = ensure_nllb_model(
                self.models_root,
                progress_cb=progress_cb,
                log_cb=log_cb or self._log,
                cancel_event=cancel_event,
            )
            self.release_nllb()
            translator = NllbTranslator(directory, intra_threads=threads)
            self._nllb = translator
            self._nllb_threads = int(threads)
            return translator

    def release_nllb(self) -> None:
        self._nllb = None
        self._nllb_threads = None

    def release_all(self) -> None:
        self.release_whisper()
        self.release_nllb()

    # -- bilgi -------------------------------------------------------------
    def inventory(self) -> list[dict]:
        """Onbellekteki modelleri boyutlariyla listeler."""
        items: list[dict] = []
        for size in ("tiny", "base", "small", "medium"):
            directory = self.models_root / f"faster-whisper-{size}"
            if directory.exists() and any(directory.iterdir()):
                items.append(
                    {
                        "key": f"whisper:{size}",
                        "label": f"Whisper {size}",
                        "path": directory,
                        "size": _dir_size(directory),
                    }
                )
        nllb_dir = self.models_root / "nllb-200-distilled-600M-ct2-int8"
        if nllb_dir.exists() and any(nllb_dir.iterdir()):
            items.append(
                {
                    "key": "nllb",
                    "label": "NLLB-200 600M int8 (çeviri)",
                    "path": nllb_dir,
                    "size": _dir_size(nllb_dir),
                }
            )
        return items

    def delete(self, key: str) -> tuple[bool, str]:
        """Belirtilen modeli siler."""
        if key.startswith("whisper:"):
            size = key.split(":", 1)[1]
            directory = self.models_root / f"faster-whisper-{size}"
            with self._lock:
                if self._whisper_key and self._whisper_key[0] == size:
                    self.release_whisper()
        elif key == "nllb":
            directory = self.models_root / "nllb-200-distilled-600M-ct2-int8"
            with self._lock:
                self.release_nllb()
        else:
            return False, f"Bilinmeyen model anahtarı: {key}"

        if not directory.exists():
            return False, "Klasör bulunamadı."
        try:
            shutil.rmtree(directory)
            return True, f"Silindi: {directory.name}"
        except OSError as exc:
            return False, f"Silinemedi: {exc}"


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
    except OSError:
        pass
    return total


# --------------------------------------------------------------------------
# Tek is calistirici
# --------------------------------------------------------------------------

@dataclass
class JobHooks:
    """JobRunner'in arayuze konusma bicimi."""

    log: Callable[[str], None] = lambda message: None
    stage: Callable[[str, int], None] = lambda text, percent: None
    progress: Callable[[int], None] = lambda percent: None
    language: Callable[[str, str, float], None] = lambda code, label, conf: None


class JobRunner:
    """Tek bir isi uctan uca yurutur (QThread icinden cagrilir)."""

    def __init__(
        self,
        settings: JobSettings,
        models: ModelCache,
        hooks: JobHooks | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self.settings = settings
        self.models = models
        self.hooks = hooks or JobHooks()
        self._cancel = cancel_event or threading.Event()
        self._temp_dir: Path | None = None
        self._started_at = 0.0
        self._pipeline_results: list[dict] | None = None
        self._video_width = 0
        self._video_height = 0
        self._video_fps = 0.0

    # -- dis API -----------------------------------------------------------
    def cancel(self) -> None:
        self._cancel.set()
        self.hooks.log("İptal isteği alındı, işlem durduruluyor…")

    def run(self) -> tuple[str, str, str]:
        """Isi calistirir; (video, srt, ozet) dondurur."""
        self._started_at = time.time()
        try:
            return self._execute()
        finally:
            self._cleanup()

    # -- yardimcilar -------------------------------------------------------
    def _stage(self, text: str, percent: int) -> None:
        self.hooks.stage(text, percent)
        self.hooks.progress(max(0, min(100, int(percent))))

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise CancelledError("İşlem iptal edildi.")

    @staticmethod
    def _map(fraction: float, start: float, end: float) -> int:
        fraction = max(0.0, min(1.0, fraction))
        return int(round(start + (end - start) * fraction))

    # -- ana akis ----------------------------------------------------------
    def _execute(self) -> tuple[str, str, str]:
        settings = self.settings
        self._stage("Hazırlanıyor", 0)

        ffmpeg_location = self._prepare_ffmpeg()
        ffmpeg = ffmpeg_location.ffmpeg
        ffprobe = ffmpeg_location.ffprobe
        self.hooks.log(f"FFmpeg: {ffmpeg} ({ffmpeg_location.source})")

        source_video: Path | None = None
        duration = 0.0
        if settings.input_path:
            source_video = Path(settings.input_path)
            if not source_video.exists():
                raise FFmpegError(f"Video dosyası bulunamadı:\n{source_video}")
            if source_video.suffix.lower() not in SUPPORTED_EXTENSIONS:
                supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
                raise FFmpegError(
                    f"Desteklenmeyen dosya türü: {source_video.suffix}\nDesteklenen: {supported}"
                )
            duration = ffmpeg_utils.media_duration(ffprobe, source_video)
            if duration <= 0:
                raise FFmpegError("Video süresi okunamadı. Dosya bozuk olabilir.")
            self._video_width, self._video_height, self._video_fps = ffmpeg_utils.media_size(
                ffprobe, source_video
            )
            self.hooks.log(f"Video süresi: {_format_duration(duration)}")
            if self._video_width and self._video_height:
                self.hooks.log(
                    f"Video boyutu: {self._video_width}x{self._video_height}"
                    + (f" @ {self._video_fps:.2f} fps" if self._video_fps else "")
                )

        self._stage("Hazırlanıyor", P_PREPARE_END)
        self._check_cancel()

        detected = ""
        confidence = 0.0
        words: list[dict] = []

        # --- 1) Metin kaynagi ---------------------------------------------
        if settings.input_srt:
            detected, confidence, words = self._load_srt_source()
        else:
            if source_video is None:
                raise FFmpegError("Ne video ne de SRT dosyası seçildi.")
            if not ffmpeg_utils.has_audio_stream(ffprobe, source_video):
                raise FFmpegError(
                    "Bu videoda ses kanalı bulunamadı.\n"
                    "Altyazı üretmek için ses içeren bir video seçin."
                )
            detected, confidence, words = self._transcribe(source_video, ffmpeg, duration)

        if not words:
            raise NoSpeechError(
                "Videoda konuşma bulunamadı.\n"
                "Ses kanalı boş olabilir veya konuşma çok kısık olabilir."
            )

        self.hooks.language(detected, language_label(detected), confidence)
        self.hooks.log(
            f"Tespit edilen dil: {language_label(detected)} ({detected or '?'}) "
            f"— güven: %{confidence * 100:.1f}"
        )

        # --- 2) Ceviri -----------------------------------------------------
        sentences = subtitles_mod.group_sentences(words)
        if not sentences:
            raise NoSpeechError("Metin cümlelere bölünemedi; altyazı üretilemiyor.")

        self._check_cancel()
        sentences = self._translate(sentences, detected)

        # --- 3) Altyazi ----------------------------------------------------
        self._stage("Altyazı oluşturuluyor", P_TRANSLATE_END)
        translated_flag = self._is_translated(sentences, detected)
        cues = subtitles_mod.sentences_to_cues(
            sentences,
            translated=translated_flag,
        )
        final_cues = subtitles_mod.finalize_segments(
            cues,
            max_cps=settings.max_cps,
        )
        if not final_cues:
            raise SubtraError("Altyazı oluşturulamadı: işlenebilir metin kalmadı.")

        srt_path = settings.output_base().with_suffix(".srt")
        subtitles_mod.write_srt(srt_path, final_cues)
        report = subtitles_mod.cps_report(final_cues, settings.max_cps)
        self.hooks.log(f"SRT yazıldı: {srt_path}")
        self.hooks.log(
            f"Altyazı kalitesi: {report['total']} satır, "
            f"en yüksek {report['max_cps']} CPS (sınır {report['limit']:.0f}), "
            f"sınırı aşan {report['over_cps']} satır"
        )
        self._stage("SRT hazır", P_SRT_END)
        self._check_cancel()

        # --- 4) Video cikisi ----------------------------------------------
        summary = _summary(final_cues, detected, settings.target_lang, report, time.time() - self._started_at)
        mode = settings.output_mode

        if mode == "srt" or source_video is None:
            if mode != "srt" and source_video is None:
                self.hooks.log("Video seçilmedi: yalnızca SRT üretildi.")
            self._stage("Tamamlandı", P_RENDER_END)
            return "", str(srt_path), summary

        video_out = settings.output_base().with_suffix(".mp4")
        self._ensure_output_space(source_video, mode)

        if mode == "burn":
            self._stage("Altyazı videoya yakılıyor (yeniden kodlama)", P_SRT_END)
            try:
                ffmpeg_utils.burn_in_subtitles(
                    ffmpeg,
                    source_video,
                    srt_path,
                    video_out,
                    settings.style,
                    duration,
                    progress_cb=lambda f: self.hooks.progress(
                        self._map(f, P_SRT_END, P_RENDER_END)
                    ),
                    cancel_event=self._cancel,
                    video_width=self._video_width,
                    video_height=self._video_height,
                    fps=self._video_fps,
                    crf=settings.burn_crf,
                )
            except CancelledError:
                _safe_unlink(video_out)
                raise
            self.hooks.log(f"Video oluşturuldu: {video_out}")
        else:
            video_out = self._render_soft(ffmpeg, source_video, srt_path, video_out, duration)

        self._stage("Tamamlandı", P_RENDER_END)
        return str(video_out), str(srt_path), summary

    # -- adimlar -----------------------------------------------------------
    def _prepare_ffmpeg(self):
        import ffmpeg_bootstrap

        explicit = self.settings.ffmpeg_path or None
        existing = ffmpeg_bootstrap.find_existing(explicit)
        if existing is not None:
            return existing

        self._stage("FFmpeg indiriliyor", 0)
        self.hooks.log("FFmpeg bulunamadı; otomatik indiriliyor…")
        return ffmpeg_bootstrap.download_ffmpeg(
            progress_cb=lambda fraction, label: self.hooks.progress(
                self._map(fraction, 0, P_PREPARE_END)
            ),
            log_cb=self.hooks.log,
            cancel_event=self._cancel,
        )

    def _load_srt_source(self) -> tuple[str, float, list[dict]]:
        srt = Path(self.settings.input_srt)
        if not srt.exists():
            raise SubtraError(f"SRT dosyası bulunamadı:\n{srt}")
        self._stage("SRT okunuyor", P_PREPARE_END)
        entries = subtitles_mod.read_srt(srt)
        if not entries:
            raise SubtraError(
                "SRT dosyası okunamadı veya boş.\n"
                "Dosyanın geçerli bir altyazı olduğundan emin olun."
            )
        self.hooks.log(f"SRT okundu: {len(entries)} satır")

        detected = (self.settings.source_lang or "").strip().lower()
        confidence = 1.0 if detected else 0.0
        if not detected:
            detected, confidence = _guess_language_from_text(
                " ".join(entry["text"] for entry in entries)
            )
            self.hooks.log(
                f"Kaynak dil metinden tahmin edildi: {language_label(detected)} "
                f"(güven: %{confidence * 100:.0f})"
            )
        words = subtitles_mod.segments_to_words(entries)
        self._stage("SRT hazır", P_TRANSCRIBE_END)
        return detected, confidence, words

    def _transcribe(self, source: Path, ffmpeg: str, duration: float) -> tuple[str, float, list[dict]]:
        settings = self.settings

        # --- Transkript önbelleği (1. aşama: kontrol) ---------------------
        # Ses çıkarmadan ÖNCE bakılır: isabet varsa ffmpeg'e hiç gidilmez.
        cache_key = ""
        if settings.use_transcript_cache and not settings.input_srt:
            cache_key = transcript_cache.cache_key(
                source,
                settings.model_size,
                settings.word_timestamps,
                extra=("batch" if settings.batch_size > 1 else "plain"),
            )
            cached = transcript_cache.load(cache_key, app_paths.transcripts_dir())
            if cached is not None:
                words = cached.get("words", [])
                meta = {
                    "language": cached.get("language", ""),
                    "language_probability": float(cached.get("language_probability", 0.0) or 0.0),
                    "duration": cached.get("duration", duration),
                }
                if transcript_cache.is_usable(cached, settings.word_timestamps):
                    info = transcript_cache.info(cache_key, app_paths.transcripts_dir()) or {}
                    self.hooks.log(
                        f"Transkript önbellekten alındı — transkripsiyon atlandı "
                        f"({len(words)} kelime, kaynak: {cached.get('created', '?')}, "
                        f"önceki süre: {cached.get('transcribe_seconds', 0):.0f}s)"
                    )
                    self._stage("Transkripsiyon (önbellek)", P_TRANSCRIBE_END)
                    self.hooks.progress(P_TRANSCRIBE_END)
                    return (
                        meta["language"],
                        meta["language_probability"],
                        words,
                    )

        self._temp_dir = Path(tempfile.mkdtemp(prefix="subtra_", dir=str(app_paths.temp_dir())))
        self.hooks.log(f"Geçici klasör: {self._temp_dir}")

        wav_path = self._temp_dir / "audio.wav"
        self._stage("Ses çıkarılıyor", P_PREPARE_END)
        ffmpeg_utils.extract_audio(
            ffmpeg,
            source,
            wav_path,
            duration,
            progress_cb=lambda f: self.hooks.progress(self._map(f, P_PREPARE_END, P_AUDIO_END)),
            cancel_event=self._cancel,
        )
        self.hooks.log(
            f"Ses çıkarıldı: {wav_path.name} ({wav_path.stat().st_size / 1024 / 1024:.1f} MB)"
        )
        self._stage("Ses çıkarıldı", P_AUDIO_END)

        whisper_threads, nllb_threads = settings.thread_budget()
        pipeline = settings.resolved_pipeline()
        self.hooks.log(
            f"Thread bütçesi: Whisper {whisper_threads}, NLLB {nllb_threads} "
            f"({'pipeline açık' if pipeline else 'pipeline kapalı'})"
        )

        self._stage(f"Whisper '{settings.model_size}' modeli hazırlanıyor", P_AUDIO_END)
        model = self.models.whisper(
            settings.model_size,
            whisper_threads,
            settings.num_workers,
            progress_cb=lambda f: self.hooks.progress(
                self._map(f, P_AUDIO_END, P_WHISPER_MODEL_END)
            ),
            log_cb=self.hooks.log,
            cancel_event=self._cancel,
        )
        self._check_cancel()

        # Pipeline: cumle olustukca ceviriye ver.
        detected_box: dict = {"language": "", "probability": 0.0}
        pipeline_obj: TranslationPipeline | None = None
        pending_error: list[str] = []

        def start_pipeline(language: str) -> TranslationPipeline | None:
            src_nllb, tgt_nllb = resolve_languages(language, settings.target_lang)
            if src_nllb is None or src_nllb == tgt_nllb:
                return None
            translator = self.models.nllb(
                nllb_threads,
                progress_cb=lambda f: self.hooks.progress(
                    self._map(f, P_TRANSCRIBE_END, P_NLLB_MODEL_END)
                ),
                log_cb=self.hooks.log,
                cancel_event=self._cancel,
            )
            return TranslationPipeline(
                translator,
                src_nllb,
                tgt_nllb,
                max_pending=8,
                cancel_event=self._cancel,
            )

        def on_sentence(sentence: dict) -> None:
            nonlocal pipeline_obj
            if not pipeline:
                return
            if pipeline_obj is None:
                language = detected_box["language"]
                if not language:
                    return
                pipeline_obj = start_pipeline(language)
                if pipeline_obj is None:
                    return
            try:
                pipeline_obj.submit(sentence)
            except CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                pending_error.append(str(exc))

        transcribe_end = P_TRANSLATE_END if pipeline else P_TRANSCRIBE_END

        def on_language(code: str, probability: float) -> None:
            detected_box["language"] = code
            detected_box["probability"] = probability

        transcribe_started = time.time()
        self._stage("Konuşma metne çevriliyor", P_WHISPER_MODEL_END)
        meta, segments = transcribe_audio(
            model,
            wav_path,
            duration,
            progress_cb=lambda f: self.hooks.progress(
                self._map(f, P_WHISPER_MODEL_END, transcribe_end)
            ),
            cancel_event=self._cancel,
            word_timestamps=settings.word_timestamps,
            sentence_cb=on_sentence if pipeline else None,
            language_cb=on_language,
            batch_size=settings.batch_size,
        )

        detected = meta["language"]
        confidence = meta["language_probability"]
        detected_box["language"] = detected
        detected_box["probability"] = confidence
        if pending_error:
            raise TranslationError(pending_error[0])

        self.hooks.log(f"Transkripsiyon tamamlandı: {len(segments)} segment")

        words = flatten_words(segments)

        # --- Transkript önbelleği (2. aşama: kaydet) ----------------------
        if cache_key and words:
            saved = transcript_cache.save(
                cache_key,
                app_paths.transcripts_dir(),
                meta={
                    "language": detected,
                    "language_probability": confidence,
                    "duration": duration,
                    "model": settings.model_size,
                    "word_timestamps": settings.word_timestamps,
                },
                words=words,
                source_name=source.name,
                elapsed=time.time() - transcribe_started,
            )
            if saved is not None:
                self.hooks.log(
                    f"Transkript önbelleğe yazıldı ({saved.name}); "
                    "aynı video tekrar işlenirse transkripsiyon atlanır"
                )
            else:
                self.hooks.log("Transkript önbelleğe yazılamadı (önemli değil, iş sürüyor)")

        if pipeline and pipeline_obj is not None:
            # Pipeline cevirisi transkripsiyon sirasinda bitti; sonuclari sakla.
            self._pipeline_results = pipeline_obj.finish()
            self.hooks.log(
                f"Paralel çeviri tamamlandı: {len(self._pipeline_results)} cümle "
                f"({pipeline_obj.stats.batches} batch)"
            )
        else:
            self._pipeline_results = None

        self._stage("Transkripsiyon tamamlandı", transcribe_end)
        return detected, confidence, words

    def _translate(self, sentences: list[dict], detected: str) -> list[dict]:
        settings = self.settings
        target = settings.target_lang
        if target not in TARGET_LANGUAGES:
            raise TranslationError(f"Desteklenmeyen hedef dil: {target}")

        src_nllb, tgt_nllb = resolve_languages(detected, target)

        if src_nllb is None:
            self.hooks.log(
                f"UYARI: '{language_label(detected)}' dili için çeviri desteği yok. "
                "Altyazı özgün dilde üretilecek."
            )
            for sentence in sentences:
                sentence["translated"] = sentence.get("text", "")
            self._stage("Çeviri desteği yok (özgün metin)", P_TRANSLATE_END)
            return sentences

        if src_nllb == tgt_nllb:
            self.hooks.log(
                f"Kaynak dil hedef dil ile aynı ({language_label(detected)}); çeviri atlandı."
            )
            for sentence in sentences:
                sentence["translated"] = sentence.get("text", "")
            self._stage("Çeviri gerekmiyor", P_TRANSLATE_END)
            return sentences

        # Pipeline sonucu varsa kullan.
        cached = getattr(self, "_pipeline_results", None)
        if cached is not None:
            self._pipeline_results = None
            if len(cached) == len(sentences):
                for sentence, result in zip(sentences, cached):
                    sentence["translated"] = result.get("translated") or sentence.get("text", "")
                self._stage("Çeviri tamamlandı", P_TRANSLATE_END)
                return sentences
            # Sayilar tutmuyorsa yeniden cevir.

        _, nllb_threads = settings.thread_budget()
        translator = self.models.nllb(
            nllb_threads,
            progress_cb=lambda f: self.hooks.progress(
                self._map(f, P_TRANSCRIBE_END, P_NLLB_MODEL_END)
            ),
            log_cb=self.hooks.log,
            cancel_event=self._cancel,
        )
        self._check_cancel()

        self._stage(f"{TARGET_LANGUAGES[target]['label']} diline çevriliyor", P_NLLB_MODEL_END)
        result = translate_sentences(
            translator,
            sentences,
            src_nllb,
            tgt_nllb,
            progress_cb=lambda f: self.hooks.progress(
                self._map(f, P_NLLB_MODEL_END, P_TRANSLATE_END)
            ),
            cancel_event=self._cancel,
        )
        self.hooks.log(f"Çeviri tamamlandı: {len(result)} cümle")
        return result

    def _is_translated(self, sentences: list[dict], detected: str) -> bool:
        try:
            src_nllb, tgt_nllb = resolve_languages(detected, self.settings.target_lang)
        except TranslationError:
            return False
        return src_nllb is not None and src_nllb != tgt_nllb

    def _ensure_output_space(self, source: Path, mode: str) -> None:
        try:
            source_size = source.stat().st_size
        except OSError:
            source_size = 0
        if mode == "burn":
            needed = int(source_size * 1.15) + 200 * 1024 * 1024
        else:
            needed = int(source_size * 0.2) + 50 * 1024 * 1024
        ffmpeg_utils.ensure_free_space(source.parent, needed)

    def _render_soft(self, ffmpeg: str, source: Path, srt_path: Path, video_out: Path, duration: float) -> Path:
        settings = self.settings
        tag = TARGET_LANGUAGES[settings.target_lang]["subtitle_tag"]
        self._stage("Altyazı videoya gömülüyor (yeniden kodlama yok)", P_SRT_END)
        try:
            ffmpeg_utils.add_soft_subtitles(
                ffmpeg,
                source,
                srt_path,
                video_out,
                language_tag=tag,
                duration=duration,
                progress_cb=lambda f: self.hooks.progress(self._map(f, P_SRT_END, P_RENDER_END)),
                cancel_event=self._cancel,
            )
        except CancelledError:
            _safe_unlink(video_out)
            raise
        except FFmpegError as exc:
            self.hooks.log(f"MP4 gömme başarısız, MKV deneniyor: {exc}")
            alt_out = video_out.with_suffix(".mkv")
            ffmpeg_utils.add_soft_subtitles(
                ffmpeg,
                source,
                srt_path,
                alt_out,
                language_tag=tag,
                duration=duration,
                progress_cb=lambda f: self.hooks.progress(self._map(f, P_SRT_END, P_RENDER_END)),
                cancel_event=self._cancel,
            )
            video_out = alt_out
        self.hooks.log(f"Video oluşturuldu: {video_out}")
        return video_out

    # -- temizlik ----------------------------------------------------------
    def _cleanup(self) -> None:
        if self._temp_dir and self._temp_dir.exists() and not self.settings.keep_temp:
            shutil.rmtree(self._temp_dir, ignore_errors=True)


# --------------------------------------------------------------------------
# QThread sarmalayicilari
# --------------------------------------------------------------------------

class VideoWorker(QThread):
    """Tek is icin QThread."""

    log = Signal(str)
    stage_changed = Signal(str)
    progress_changed = Signal(int)
    language_detected = Signal(str, str, float)  # kod, ad, guven
    finished_ok = Signal(str, str, str)          # video, srt, ozet
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, settings: JobSettings, parent=None, models: ModelCache | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._models = models
        self._owns_models = models is None
        self._runner: JobRunner | None = None
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()
        if self._runner is not None:
            self._runner.cancel()

    def _hooks(self) -> JobHooks:
        return JobHooks(
            log=lambda message: self.log.emit(message),
            stage=lambda text, percent: self.stage_changed.emit(text),
            progress=lambda percent: self.progress_changed.emit(percent),
            language=lambda code, label, conf: self.language_detected.emit(code, label, conf),
        )

    def run(self) -> None:
        models = self._models
        if models is None:
            models = ModelCache(self._models_root(), log_cb=lambda m: self.log.emit(m))
        try:
            self._runner = JobRunner(self.settings, models, self._hooks(), self._cancel_event)
            video, srt, summary = self._runner.run()
            self.finished_ok.emit(video, srt, summary)
        except CancelledError:
            self.log.emit("İşlem iptal edildi.")
            self.cancelled.emit()
        except (FFmpegError, ModelDownloadError, TranslationError, NoSpeechError, SubtraError) as exc:
            self.failed.emit(str(exc))
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                self.failed.emit(
                    f"Disk dolu.\n\n{exc.strerror or ''}\n"
                    "Geçici dosyalar ve çıktı için boş alan açıp tekrar deneyin."
                )
            else:
                self.failed.emit(f"Dosya sistemi hatası.\n\n{exc}")
        except MemoryError:
            self.failed.emit(
                "Bellek yetersiz. Daha küçük bir Whisper modeli (tiny/base) "
                "seçin ve diğer programları kapatın."
            )
        except Exception as exc:  # noqa: BLE001
            self.log.emit(traceback.format_exc())
            self.failed.emit(f"Beklenmeyen hata.\n\n{type(exc).__name__}: {exc}")
        finally:
            if self._owns_models:
                models.release_all()

    def _models_root(self) -> Path:
        return app_paths.resolve_models_dir(self.settings.models_dir or None)


class BatchWorker(QThread):
    """Kuyruktaki isleri sirayla calistirir; modelleri paylasir."""

    log = Signal(str)
    stage_changed = Signal(str)
    progress_changed = Signal(int)
    language_detected = Signal(str, str, float)

    item_started = Signal(int, str)             # indeks, yol
    item_finished = Signal(int, str, str, str)  # indeks, video, srt, ozet
    item_failed = Signal(int, str)              # indeks, mesaj
    item_cancelled = Signal(int)                # indeks
    batch_finished = Signal(int, int, str)      # basarili, hatali, sure
    all_cancelled = Signal()

    def __init__(self, jobs: list[JobSettings], parent=None, models: ModelCache | None = None) -> None:
        super().__init__(parent)
        self.jobs = jobs
        self._models = models
        self._owns_models = models is None
        self._cancel_event = threading.Event()
        self._current_index = -1

    def cancel(self) -> None:
        self._cancel_event.set()

    def cancel_all(self) -> None:
        self._cancel_event.set()

    def _hooks(self) -> JobHooks:
        return JobHooks(
            log=lambda message: self.log.emit(message),
            stage=lambda text, percent: self.stage_changed.emit(text),
            progress=lambda percent: self.progress_changed.emit(percent),
            language=lambda code, label, conf: self.language_detected.emit(code, label, conf),
        )

    def run(self) -> None:
        started = time.time()
        ok = 0
        failed = 0
        models = self._models
        if models is None:
            models = ModelCache(app_paths.resolve_models_dir(), log_cb=lambda m: self.log.emit(m))

        try:
            for index, job in enumerate(self.jobs):
                if self._cancel_event.is_set():
                    break
                self._current_index = index
                self.item_started.emit(index, job.input_path or job.input_srt)
                runner = JobRunner(job, models, self._hooks(), self._cancel_event)
                try:
                    video, srt, summary = runner.run()
                    ok += 1
                    self.item_finished.emit(index, video, srt, summary)
                except CancelledError:
                    self.item_cancelled.emit(index)
                    break
                except (FFmpegError, ModelDownloadError, TranslationError, NoSpeechError, SubtraError) as exc:
                    failed += 1
                    self.item_failed.emit(index, str(exc))
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    self.log.emit(traceback.format_exc())
                    self.item_failed.emit(index, f"Beklenmeyen hata: {type(exc).__name__}: {exc}")
        finally:
            elapsed = _format_duration(time.time() - started)
            if self._owns_models:
                models.release_all()
            if self._cancel_event.is_set() and ok == 0:
                self.all_cancelled.emit()
            else:
                self.batch_finished.emit(ok, failed, elapsed)


# --------------------------------------------------------------------------
# Yardimcilar
# --------------------------------------------------------------------------

def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _format_duration(seconds: float) -> str:
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours} sa {minutes} dk {secs} sn"
    if minutes:
        return f"{minutes} dk {secs} sn"
    return f"{secs} sn"


def _summary(
    segments: list[dict],
    detected: str,
    target: str,
    report: dict,
    elapsed: float,
) -> str:
    return (
        f"Altyazı: {len(segments)} satır\n"
        f"Kaynak dil: {language_label(detected)}\n"
        f"Hedef dil: {TARGET_LANGUAGES[target]['label']}\n"
        f"Karakter: {subtitles_mod.total_characters(segments)}\n"
        f"En yüksek okuma hızı: {report['max_cps']} CPS (sınır {report['limit']:.0f})\n"
        f"Süre: {_format_duration(elapsed)}"
    )


def _guess_language_from_text(text: str) -> tuple[str, float]:
    """SRT ice aktarmada kaynak dili kabaca tahmin eder.

    Harici bagimlilik yok; yalnizca karakter kumesi ve yaygin kelimelere
    bakar. Sonuc yalnizca on secim icindir, kullanici degistirebilir.
    """
    sample = (text or "").lower()[:4000]
    if not sample.strip():
        return "", 0.0

    scripts = {
        "ru": set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя"),
        "el": set("αβγδεζηθικλμνξοπρστυφχψω"),
        "ar": set("ابتثجحخدذرزسشصضطظعغفقكلمنهوي"),
        "he": set("אבגדהוזחטיכלמנסעפצקרשת"),
        "ja": set("あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほ"),
        "ko": set("가나다라마바사아자차카타파하"),
        "zh": set("的一是不了人我在有他这中大来上国"),
        "th": set("กขคงจฉชซญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮ"),
        "hi": set("अआइईउऊएऐओऔकखगघचछजझटठडढतथदधनपफबभमयरलवशषसह"),
    }
    core = [ch for ch in sample if ch.isalpha()]
    if core:
        for code, charset in scripts.items():
            hits = sum(1 for ch in core if ch in charset)
            ratio = hits / len(core)
            if ratio > 0.35:
                return code, min(0.95, 0.5 + ratio)

    turkish_specific = set("ğışçöüİ")
    turkish_hits = sum(1 for ch in sample if ch in turkish_specific)
    words = set(sample.split())
    if turkish_hits > 2:
        return "tr", min(0.9, 0.5 + turkish_hits / max(1, len(core)))

    german_words = {"der", "die", "das", "und", "ist", "nicht", "ich", "sie", "mit", "ein"}
    french_words = {"les", "des", "est", "une", "dans", "pour", "que", "qui", "pas", "vous"}
    spanish_words = {"los", "las", "que", "una", "para", "con", "por", "como", "pero", "más"}
    english_words = {"the", "and", "is", "that", "this", "with", "for", "you", "not", "have"}

    latin_core = [ch for ch in core if ch.isascii()]
    if latin_core and len(latin_core) / max(1, len(core)) > 0.6:
        scores = {
            "en": len(words & english_words),
            "de": len(words & german_words),
            "fr": len(words & french_words),
            "es": len(words & spanish_words),
        }
        best = max(scores, key=scores.get)
        if scores[best] >= 2:
            return best, min(0.85, 0.4 + scores[best] / 20)
        return "en", 0.3

    return "", 0.0
