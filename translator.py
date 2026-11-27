"""NLLB-200 distilled 600M (CTranslate2, int8, CPU) ile ceviri.

Tasarim:
  * Whisper kelimeleri once cumlelere gruplanir (baglam korunur).
  * Cumleler batch halinde cevrilir.
  * Cevrilen cumle, kaynak kelime zaman damgalarina gore altyazi kumelerine
    dagitilir (bkz. subtitles.sentences_to_cues).

NLLB token protokolu (kritik):
  * Kaynak dizisi `[src_lang] + tokenlar + ["</s>"]` seklindedir. EOS
    eksik olursa model tekrarlayan bozuk cikti uretir.
  * Token ID sirasi `shared_vocabulary.txt` ile tanimlidir; ham
    SentencePiece ciktisi bu sirayla uyusmaz, bu yuzden `tokenizer.json`
    kullanilir ve ID -> token metni shared_vocabulary uzerinden eslesir.
"""

from __future__ import annotations

import os
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from errors import CancelledError, ModelDownloadError, TranslationError
from glossary import Glossary
from languages import TARGET_LANGUAGES, whisper_to_nllb
from transcriber import _downloads_disabled, download_repo_files

NLLB_REPO = "JustFrederik/nllb-200-distilled-600M-ct2-int8"
NLLB_DIR_NAME = "nllb-200-distilled-600M-ct2-int8"
NLLB_APPROX_MB = 615

NLLB_FILES = (
    "config.json",
    "model.bin",
    "sentencepiece.bpe.model",
    "shared_vocabulary.txt",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
)
NLLB_MANDATORY = ("config.json", "model.bin", "sentencepiece.bpe.model")

VCREDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"

ProgressCB = Optional[Callable[[float], None]]
LogCB = Optional[Callable[[str], None]]


# --------------------------------------------------------------------------
# CTranslate2 calisma kontrolu
# --------------------------------------------------------------------------

def check_ctranslate2_runtime(timeout: float = 60.0) -> str | None:
    """CTranslate2'nin bu makinede calisip calismadigini alt surecte dener.

    Eski Microsoft Visual C++ Redistributable (MSVCP140.dll < 14.30)
    kuruluysa ctranslate2 bir Translator olustururken erisim ihlali ile
    tum sureci cokertir. Bu durum Python tarafindan yakalanamaz, bu yuzden
    ayri bir alt surecte onceden test edilir.

    Sorun yoksa None, varsa kullaniciya gosterilecek Turkce mesaj doner.
    """
    import subprocess
    import sys

    script = (
        "import sys\n"
        "import ctranslate2\n"
        "try:\n"
        "    ctranslate2.Translator('__yok_boyle_bir_model__', device='cpu')\n"
        "except Exception:\n"
        "    pass\n"
        "print('CT2_RUNTIME_OK')\n"
    )

    creationflags = 0x08000000 if os.name == "nt" else 0
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=creationflags,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        # PyInstaller ile paketlenmis uygulamada sys.executable sistemde
        # bulunmayabilir; bu durumda kontrolu atla.
        return None
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Çeviri motoru (CTranslate2) kontrol edilemedi.\n{exc}"

    if result.returncode == 0 and "CT2_RUNTIME_OK" in (result.stdout or ""):
        return None

    code = result.returncode
    hex_code = f"0x{code & 0xFFFFFFFF:08X}" if code else "0"
    return (
        "Çeviri motoru (CTranslate2) bu bilgisayarda çalışmıyor.\n\n"
        f"Hata kodu: {hex_code}\n\n"
        "En yaygın nedeni eski Microsoft Visual C++ Redistributable "
        "sürümüdür (MSVCP140.dll). Aşağıdaki bağlantıdan güncel paketi "
        "kurup bilgisayarı yeniden başlatın:\n\n"
        f"{VCREDIST_URL}\n\n"
        "Kurulumdan sonra 'CTranslate2 Kontrolü' butonuyla tekrar deneyin."
    )


# --------------------------------------------------------------------------
# Model indirme / yukleme
# --------------------------------------------------------------------------

def nllb_model_dir(models_root: str | Path) -> Path:
    return Path(models_root) / NLLB_DIR_NAME


def is_nllb_cached(models_root: str | Path) -> bool:
    directory = nllb_model_dir(models_root)
    model_bin = directory / "model.bin"
    return (
        (directory / "config.json").exists()
        and (directory / "sentencepiece.bpe.model").exists()
        and model_bin.exists()
        and model_bin.stat().st_size > 1024 * 1024
    )


def ensure_nllb_model(
    models_root: str | Path,
    progress_cb: ProgressCB = None,
    log_cb: LogCB = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    directory = nllb_model_dir(models_root)
    if is_nllb_cached(models_root):
        if log_cb:
            log_cb("NLLB çeviri modeli önbellekte bulundu (offline).")
        if progress_cb:
            progress_cb(1.0)
        return directory

    if _downloads_disabled():
        raise TranslationError(
            "NLLB çeviri modeli indirilmemiş ve indirme kapalı "
            "(SUBTRA_NO_DOWNLOAD=1).\n"
            f"Beklenen klasör: {directory}"
        )

    if log_cb:
        log_cb("NLLB çeviri modeli indirilecek (yalnızca ilk kullanım).")

    download_repo_files(
        NLLB_REPO,
        NLLB_FILES,
        directory,
        progress_cb=progress_cb,
        log_cb=log_cb,
        cancel_event=cancel_event,
        mandatory=NLLB_MANDATORY,
    )
    if not is_nllb_cached(models_root):
        raise ModelDownloadError(
            "Çeviri modeli indirildi ancak doğrulanamadı.\n" f"Klasör: {directory}"
        )
    return directory


class NllbTranslator:
    """CTranslate2 uzerinde NLLB-200 ceviricisi."""

    def __init__(self, model_dir: str | Path, intra_threads: int | None = None) -> None:
        directory = Path(model_dir)
        vocab_file = directory / "shared_vocabulary.txt"
        tokenizer_file = directory / "tokenizer.json"
        if not vocab_file.exists() or not tokenizer_file.exists():
            raise TranslationError(
                "Çeviri modeli dosyaları eksik "
                f"(shared_vocabulary.txt / tokenizer.json): {directory}\n"
                "Klasörü silip programı yeniden başlatın."
            )

        try:
            import ctranslate2
            from tokenizers import Tokenizer
        except ImportError as exc:  # pragma: no cover
            raise TranslationError(
                "Çeviri bağımlılıkları eksik. Kurulum:\n"
                "py -m pip install ctranslate2 tokenizers"
            ) from exc

        self._vocab = [
            line.rstrip("\n")
            for line in vocab_file.read_text(encoding="utf-8").splitlines()
        ]
        self._token_to_id = {token: index for index, token in enumerate(self._vocab)}

        try:
            self._tokenizer = Tokenizer.from_file(str(tokenizer_file))
        except Exception as exc:
            raise TranslationError(f"Tokenizer yüklenemedi: {exc}") from exc

        if intra_threads is None:
            from hardware import ctranslate2_threads

            intra_threads = ctranslate2_threads()
        intra_threads = max(1, int(intra_threads))

        try:
            self._translator = ctranslate2.Translator(
                str(directory),
                device="cpu",
                compute_type="int8",
                inter_threads=1,
                intra_threads=intra_threads,
            )
        except Exception as exc:
            raise TranslationError(
                "Çeviri modeli yüklenemedi. Model dosyaları bozuk olabilir; "
                f"'{directory}' klasörünü silip tekrar deneyin.\n{exc}"
            ) from exc

        self.threads = intra_threads

    # -- token islemleri ---------------------------------------------------
    def _verify_language_token(self, token: str) -> None:
        if token not in self._token_to_id:
            raise TranslationError(
                f"Dil kodu çeviri modelinde bulunamadı: {token}\n"
                "Model dosyaları eksik olabilir."
            )

    def _encode(self, text: str, src_lang: str) -> list[str]:
        encoding = self._tokenizer.encode(text, add_special_tokens=False)
        tokens = [self._vocab[i] for i in encoding.ids if 0 <= i < len(self._vocab)]
        # NLLB kaynak dizisinin sonunda EOS (</s>) bekler.
        return [src_lang] + tokens + ["</s>"]

    def _decode(self, tokens: list[str]) -> str:
        ids: list[int] = []
        for token in tokens:
            if token == "</s>":
                break
            index = self._token_to_id.get(token)
            if index is not None:
                ids.append(index)
        if not ids:
            return ""
        return self._tokenizer.decode(ids, skip_special_tokens=True).strip()

    # -- ceviri ------------------------------------------------------------
    def translate_batch(
        self,
        texts: list[str],
        src_lang: str,
        tgt_lang: str,
        progress_cb: ProgressCB = None,
        cancel_event: threading.Event | None = None,
        batch_size: int = 8,
        beam_size: int = 4,
    ) -> list[str]:
        """Cumleleri batch'ler halinde cevirir."""
        self._verify_language_token(src_lang)
        self._verify_language_token(tgt_lang)

        results: list[str] = []
        total = len(texts)
        if total == 0:
            return results

        for start in range(0, total, batch_size):
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError("Çeviri iptal edildi.")
            chunk = texts[start : start + batch_size]
            encoded = [self._encode(text, src_lang) for text in chunk]
            try:
                translations = self._translator.translate_batch(
                    encoded,
                    target_prefix=[[tgt_lang] for _ in chunk],
                    beam_size=beam_size,
                    max_batch_size=32,
                    batch_type="examples",
                    max_decoding_length=512,
                    replace_unknowns=True,
                    length_penalty=1.0,
                    repetition_penalty=1.1,
                )
            except Exception as exc:
                raise TranslationError(f"Çeviri sırasında hata oluştu: {exc}") from exc

            for source_text, result in zip(chunk, translations):
                tokens = list(result.hypotheses[0]) if result.hypotheses else []
                if tokens and tokens[0] == tgt_lang:
                    tokens = tokens[1:]
                text = self._decode(tokens)
                results.append(text or source_text)

            if progress_cb:
                progress_cb(min(1.0, (start + len(chunk)) / total))

        if progress_cb:
            progress_cb(1.0)
        return results


# --------------------------------------------------------------------------
# Ceviri akislari
# --------------------------------------------------------------------------

def resolve_languages(detected: str, target: str) -> tuple[str | None, str]:
    """(kaynak_nllb, hedef_nllb) dondurur. Kaynak desteklenmiyorsa None."""
    if target not in TARGET_LANGUAGES:
        raise TranslationError(f"Desteklenmeyen hedef dil: {target}")
    return whisper_to_nllb(detected), TARGET_LANGUAGES[target]["nllb"]


def translate_sentences(
    translator: NllbTranslator,
    sentences: list[dict],
    src_nllb: str,
    tgt_nllb: str,
    progress_cb: ProgressCB = None,
    cancel_event: threading.Event | None = None,
    glossary: Glossary | None = None,
    source_lang: str = "",
    target_lang: str = "",
) -> list[dict]:
    """Cumle listesini cevirir; her cumleye `translated` anahtari ekler.

    `glossary` verilirse terimler ceviriden once yer tutucuyla korunur ve
    ceviriden sonra hedef karsiligi yazilir.
    """
    if not sentences:
        return []

    output = [dict(sentence) for sentence in sentences]
    texts = [sentence["text"] for sentence in sentences]
    if src_nllb == tgt_nllb:
        for sentence, text in zip(output, texts):
            if glossary:
                sentence["translated"] = glossary.apply(
                    text, source_lang, target_lang
                )
            else:
                sentence["translated"] = text
        if progress_cb:
            progress_cb(1.0)
        return output

    mappings: list[dict[str, str]] = []
    if glossary:
        protected: list[str] = []
        for text in texts:
            guarded, mapping = glossary.protect(text, source_lang, target_lang)
            protected.append(guarded)
            mappings.append(mapping)
        texts = protected
    else:
        mappings = [{} for _ in texts]

    translated = translator.translate_batch(
        texts, src_nllb, tgt_nllb, progress_cb=progress_cb, cancel_event=cancel_event
    )
    for index, (sentence, text) in enumerate(zip(output, translated)):
        result = text or sentence["text"]
        if glossary and mappings[index]:
            result, report = glossary.restore_full(
                result, mappings[index], source_lang, target_lang
            )
            sentence["glossary_applied"] = report.applied
            if report.unresolved:
                sentence["glossary_lost"] = list(report.unresolved)
        sentence["translated"] = result
    return output


@dataclass
class PipelineStats:
    sentences: int = 0
    batches: int = 0
    failed: bool = False
    error: str = ""


class TranslationPipeline:
    """Transkripsiyon surerken ceviriyi paralel yurutur.

    Uretici (Whisper) cumleleri `submit()` ile verir; tuketici thread
    bunlari batch'ler halinde cevirir. Sonuclar `finish()` ile sirayla
    dondurulur. Kuyruk doldugunda `submit()` bekler, boylece bellek sinirli
    kalir.
    """

    def __init__(
        self,
        translator: NllbTranslator,
        src_nllb: str,
        tgt_nllb: str,
        batch_size: int = 8,
        max_pending: int = 8,
        cancel_event: threading.Event | None = None,
        glossary: Glossary | None = None,
        source_lang: str = "",
        target_lang: str = "",
    ) -> None:
        self._translator = translator
        self._src = src_nllb
        self._tgt = tgt_nllb
        self._glossary = glossary
        self._source_lang = source_lang
        self._target_lang = target_lang
        self._batch_size = max(1, batch_size)
        self._cancel = cancel_event or threading.Event()
        self._queue: "queue.Queue[dict | None]" = queue.Queue(maxsize=max_pending)
        self._results: dict[int, dict] = {}
        self._errors: list[str] = []
        self._next_index = 0
        self.stats = PipelineStats()
        self._thread: threading.Thread | None = None
        self._pending: list[dict] = []
        self._lock = threading.Lock()
        self._finished = False
        self._same_language = src_nllb == tgt_nllb

    # -- uretici tarafi ----------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="translate-pipeline", daemon=True)
        self._thread.start()

    def submit(self, sentence: dict) -> None:
        if self._same_language:
            text = sentence.get("text", "")
            if self._glossary:
                text = self._glossary.apply(text, self._source_lang, self._target_lang)
            with self._lock:
                self._results[self._next_index] = dict(sentence, translated=text)
                self._next_index += 1
                self.stats.sentences += 1
            return
        self.start()
        with self._lock:
            index = self._next_index
            self._next_index += 1
            self.stats.sentences += 1
        payload = dict(sentence)
        payload["_index"] = index
        while True:
            if self._cancel.is_set():
                raise CancelledError("Çeviri iptal edildi.")
            try:
                self._queue.put(payload, timeout=0.2)
                return
            except queue.Full:
                continue

    # -- tuketici tarafi ---------------------------------------------------
    def _run(self) -> None:
        try:
            while True:
                try:
                    item = self._queue.get(timeout=0.2)
                except queue.Empty:
                    if self._cancel.is_set():
                        return
                    continue
                if item is None:
                    break
                self._pending.append(item)
                # Kuyrugu bosalt, batch'i doldur.
                while len(self._pending) < self._batch_size:
                    try:
                        more = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    if more is None:
                        self._queue.put(None)
                        break
                    self._pending.append(more)
                self._translate_pending()
            self._translate_pending()
        except CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            self.stats.failed = True
            self.stats.error = str(exc)
            self._errors.append(str(exc))
        finally:
            self._finished = True

    def _translate_pending(self) -> None:
        if not self._pending:
            return
        batch = self._pending
        self._pending = []
        texts = [item["text"] for item in batch]
        mappings: list[dict[str, str]] = [{} for _ in texts]
        if self._glossary:
            protected: list[str] = []
            for index, text in enumerate(texts):
                guarded, mapping = self._glossary.protect(
                    text, self._source_lang, self._target_lang
                )
                protected.append(guarded)
                mappings[index] = mapping
            texts = protected
        translated = self._translator.translate_batch(
            texts,
            self._src,
            self._tgt,
            cancel_event=self._cancel,
            batch_size=self._batch_size,
        )
        self.stats.batches += 1
        with self._lock:
            for item, text, mapping in zip(batch, translated, mappings):
                index = item.pop("_index")
                result = text or item["text"]
                if self._glossary and mapping:
                    result, report = self._glossary.restore_full(
                        result, mapping, self._source_lang, self._target_lang
                    )
                    item["glossary_applied"] = report.applied
                    if report.unresolved:
                        item["glossary_lost"] = list(report.unresolved)
                self._results[index] = dict(item, translated=result)

    def finish(self) -> list[dict]:
        if self._thread is not None:
            try:
                self._queue.put(None, timeout=1.0)
            except queue.Full:
                pass
            self._thread.join(timeout=900)
        if self.stats.failed:
            raise TranslationError(self.stats.error or "Çeviri başarısız.")
        with self._lock:
            results = [self._results[idx] for idx in sorted(self._results)]
        return results


# --------------------------------------------------------------------------
# Toplu (pipeline'siz) yardimci
# --------------------------------------------------------------------------

def translate_all(
    translator: NllbTranslator,
    sentences: list[dict],
    detected_language: str,
    target_language: str,
    progress_cb: ProgressCB = None,
    cancel_event: threading.Event | None = None,
    glossary: Glossary | None = None,
) -> list[dict]:
    """Tek seferde cevirir (pipeline yok)."""
    src_nllb, tgt_nllb = resolve_languages(detected_language, target_language)
    if src_nllb is None:
        for sentence in sentences:
            text = sentence.get("text", "")
            if glossary:
                text = glossary.apply(text, detected_language, target_language)
            sentence["translated"] = text
        if progress_cb:
            progress_cb(1.0)
        return sentences
    return translate_sentences(
        translator,
        sentences,
        src_nllb,
        tgt_nllb,
        progress_cb,
        cancel_event,
        glossary=glossary,
        source_lang=detected_language,
        target_lang=target_language,
    )
