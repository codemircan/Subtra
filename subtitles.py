"""SRT uretimi, kelime tabanli altyazi bolme ve okunabilirlik kontrolu.

Bolme mantigi artik karakter sayisina gore degil:
  1. Whisper kelime zaman damgalari (word_timestamps) kullanilir.
  2. Kume (cue) sinirlari noktalama, sessizlik, satir ve sure sinirlarina gore
     belirlenir; kelime asla ortadan kesilmez.
  3. Ceviri sonrasi saniyedeki karakter (CPS) kurali uygulanir; asan kumeler
     bolunur veya suresi uzatilir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# --- Ayarlanabilir sinirlar -------------------------------------------------
MIN_CUE_DURATION = 1.0          # saniye
MAX_LINE_CHARS = 42
MAX_LINES = 2
MAX_CUE_DURATION = 7.0          # saniye
MAX_GAP = 0.7                   # kelimeler arasi sessizlik: yeni kume
TARGET_MAX_CPS = 18.0           # saniyedeki karakter ust siniri
MAX_EXTEND = 2.5                # CPS icin en fazla sure uzatma (saniye)
MIN_CPS_SPLIT_CHARS = 12        # bundan kisa metin CPS icin bolunmez

SENTENCE_END_CHARS = ".!?…。！？؟।"
SOFT_BREAK_CHARS = ",;:،؛—–"

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…。！？؟।])\s+")
_HTML_TAG = re.compile(r"<[^>]+>")
_ASS_TAG = re.compile(r"\{\\[^}]*\}")


# --------------------------------------------------------------------------
# Kucuk yardimcilar
# --------------------------------------------------------------------------

def _clean(text: str) -> str:
    return " ".join((text or "").split())


def _format_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    millis_total = int(round(seconds * 1000))
    hours, remainder = divmod(millis_total, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _parse_timestamp(value: str) -> float:
    text = value.strip().replace(".", ",")
    match = re.match(r"(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})", text)
    if not match:
        match = re.match(r"(\d+):(\d{1,2})[,.](\d{1,3})", text)
        if not match:
            return 0.0
        minutes, secs, millis = match.groups()
        return int(minutes) * 60 + int(secs) + int(millis.ljust(3, "0")) / 1000
    hours, minutes, secs, millis = match.groups()
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(secs)
        + int(millis.ljust(3, "0")) / 1000
    )


def strip_markup(text: str) -> str:
    """HTML/ASS etiketlerini kaldirir (SRT ice aktarma icin)."""
    return _clean(_ASS_TAG.sub("", _HTML_TAG.sub("", text or "")))


def cue_char_count(text: str) -> int:
    return len(text.replace("\n", " "))


def cps(text: str, duration: float) -> float:
    if duration <= 0:
        return 0.0
    return cue_char_count(text) / duration


def _ends_sentence(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(stripped) and stripped[-1] in SENTENCE_END_CHARS


def _ends_soft(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(stripped) and stripped[-1] in SOFT_BREAK_CHARS


def _sentence_completeness(text: str) -> bool:
    """Metin noktalama ile bitiyor ve makul uzunlukta mi?"""
    stripped = (text or "").strip()
    return _ends_sentence(stripped) and len(stripped) >= 8


# --------------------------------------------------------------------------
# Metin sarma
# --------------------------------------------------------------------------

def wrap_text(
    text: str,
    max_line_chars: int = MAX_LINE_CHARS,
    max_lines: int = MAX_LINES,
) -> str:
    """Metni en fazla `max_lines` satira boler.

    Once `max_line_chars` genisliginde acgozlu bolme denenir. Satir sayisi
    siniri asarsa satirlar dengeli olacak sekilde yeniden akitilir; boylece
    tek bir dev satir yerine iki esit parca cikar.
    """
    words = _clean(text).split()
    if not words:
        return ""

    def greedy(width: int) -> list[str]:
        out: list[str] = []
        current = ""
        for word in words:
            if not current:
                current = word
            elif len(current) + 1 + len(word) <= width:
                current = current + " " + word
            else:
                out.append(current)
                current = word
        if current:
            out.append(current)
        return out

    lines = greedy(max_line_chars)
    if len(lines) <= max_lines:
        return "\n".join(lines)

    total = len(" ".join(words))
    balanced_width = max(max_line_chars, -(-total // max_lines) + 6)
    lines = greedy(balanced_width)
    if len(lines) <= max_lines:
        return "\n".join(lines)

    head = lines[: max_lines - 1]
    tail = " ".join(lines[max_lines - 1 :])
    return "\n".join(head + [tail])


def _pack_words(text: str, max_chars: int) -> list[str]:
    """Kelimeleri, hicbiri `max_chars`'i asmayacak sekilde parcalara boler."""
    chunks: list[str] = []
    current = ""
    for word in _clean(text).split():
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= max_chars:
            current = current + " " + word
        else:
            chunks.append(current)
            current = word
    if current:
        chunks.append(current)
    return chunks


def chunk_text(text: str, max_chars: int) -> list[str]:
    """Metni once cumle sinirlarindan, gerekirse kelimelerden boler."""
    cleaned = _clean(text)
    if len(cleaned) <= max_chars:
        return [cleaned]

    sentences = [part for part in _SENTENCE_SPLIT.split(cleaned) if part.strip()]
    if len(sentences) <= 1:
        return _pack_words(cleaned, max_chars)

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current = current + " " + sentence
        else:
            chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)

    expanded: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            expanded.append(chunk)
        else:
            expanded.extend(_pack_words(chunk, max_chars))
    return expanded


# --------------------------------------------------------------------------
# Kelime -> cumle gruplama (ceviri baglami icin)
# --------------------------------------------------------------------------

def group_sentences(
    words: list[dict],
    max_chars: int = 400,
    max_duration: float = 20.0,
    max_words: int = 60,
) -> list[dict]:
    """Kelime listesini ceviri icin cumlelere gruplar."""
    sentences: list[dict] = []
    current: list[dict] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        text = _clean(" ".join(item["text"] for item in current))
        if text:
            sentences.append(
                {
                    "text": text,
                    "start": float(current[0]["start"]),
                    "end": float(current[-1]["end"]),
                    "words": list(current),
                }
            )
        current = []

    for word in words:
        text = (word.get("text") or "").strip()
        if not text:
            continue
        entry = {
            "text": text,
            "start": float(word.get("start", 0.0)),
            "end": float(word.get("end", 0.0)),
        }
        if current and entry["end"] <= current[-1]["start"]:
            continue  # bozuk/sirali olmayan zaman damgasi

        current.append(entry)
        joined = " ".join(item["text"] for item in current)
        if (
            _ends_sentence(text)
            or len(joined) >= max_chars
            or (entry["end"] - current[0]["start"]) >= max_duration
            or len(current) >= max_words
        ):
            flush()

    flush()
    return sentences


def sentences_to_cues(
    sentences: list[dict],
    max_chars: int = MAX_LINE_CHARS * MAX_LINES,
    max_duration: float = MAX_CUE_DURATION,
    translated: bool = True,
) -> list[dict]:
    """Cumleleri altyazi kumelerine boler.

    Cevrilmemis metinde gercek kelime zaman damgalari kullanilir (en dogru
    sonuc). Cevrilmis metinde zaman, parca uzunluguna gore oransal dagitilir.
    """
    cues: list[dict] = []

    for sentence in sentences:
        raw_text = sentence.get("translated") if translated else sentence.get("text", "")
        text = _clean(raw_text or "")
        if not text:
            continue
        start = float(sentence["start"])
        end = float(sentence["end"])
        if end <= start:
            end = start + 0.5
        words = sentence.get("words") or []

        if not translated and words:
            cues.extend(_cues_from_word_timings(words, max_chars, max_duration))
            continue

        chunks = chunk_text(text, max_chars)
        if not chunks:
            continue
        if len(chunks) == 1 and (end - start) <= max_duration:
            cues.append({"start": start, "end": end, "text": chunks[0]})
            continue

        span = end - start
        total_chars = sum(len(chunk) for chunk in chunks) or 1
        cursor = start
        for position, chunk in enumerate(chunks):
            if position == len(chunks) - 1:
                chunk_end = end
            else:
                share = len(chunk) / total_chars
                chunk_end = min(end, cursor + span * share)
            if chunk_end <= cursor:
                chunk_end = min(end, cursor + 0.4)
            cues.append({"start": cursor, "end": chunk_end, "text": chunk})
            cursor = chunk_end

    return cues


def _cues_from_word_timings(
    words: list[dict],
    max_chars: int,
    max_duration: float,
) -> list[dict]:
    """Kelime zaman damgalarina gore kume olusturur (ceviri yoksa)."""
    cues: list[dict] = []
    current: list[dict] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        cues.append(
            {
                "start": float(current[0]["start"]),
                "end": float(current[-1]["end"]),
                "text": _clean(" ".join(item["text"] for item in current)),
            }
        )
        current = []

    for word in words:
        text = (word.get("text") or "").strip()
        if not text:
            continue
        if current:
            gap = float(word["start"]) - float(current[-1]["end"])
            joined = len(" ".join(item["text"] for item in current)) + 1 + len(text)
            too_long = joined > max_chars
            too_slow = (float(word["end"]) - float(current[0]["start"])) > max_duration
            if gap > MAX_GAP or too_long or too_slow:
                flush()
        current.append({"text": text, "start": word["start"], "end": word["end"]})
        if _ends_sentence(text):
            flush()

    flush()
    return cues


# --------------------------------------------------------------------------
# Bolme / birlestirme / CPS
# --------------------------------------------------------------------------

def split_oversized(
    segments: list[dict],
    max_chars: int,
    min_cue: float = 0.9,
) -> list[dict]:
    """2 satira sigmayan altyazilari birden fazla altyaziye boler."""
    output: list[dict] = []
    for segment in segments:
        text = _clean(segment["text"])
        if len(text) <= max_chars:
            output.append(dict(segment, text=text))
            continue

        chunks = chunk_text(text, max_chars)
        if len(chunks) <= 1:
            output.append(dict(segment, text=text))
            continue

        total_chars = sum(len(chunk) for chunk in chunks) or 1
        start = float(segment["start"])
        end = float(segment["end"])
        if end <= start:
            end = start + 0.6
        span = end - start
        cursor = start

        for position, chunk in enumerate(chunks):
            if position == len(chunks) - 1:
                chunk_end = end
            else:
                share = len(chunk) / total_chars
                chunk_end = min(end, cursor + span * share)
                chunk_end = max(chunk_end, cursor + min_cue)
                if chunk_end >= end:
                    chunk_end = cursor + (end - cursor) * 0.6
            output.append({"start": cursor, "end": chunk_end, "text": chunk})
            cursor = chunk_end

    return output


def merge_short_cues(
    segments: list[dict],
    min_duration: float = MIN_CUE_DURATION,
    max_chars: int = MAX_LINE_CHARS * MAX_LINES,
    merge_gap: float = 0.8,
) -> list[dict]:
    """Cok kisa suren altyazilari komsulariyla birlestirir veya uzatir."""
    items = sorted(segments, key=lambda entry: entry["start"])
    result: list[dict] = []
    index = 0

    while index < len(items):
        current = dict(items[index])
        duration = current["end"] - current["start"]
        next_item = items[index + 1] if index + 1 < len(items) else None

        if duration < min_duration:
            previous = result[-1] if result else None
            can_next = (
                next_item is not None
                and len(current["text"]) + 1 + len(next_item["text"]) <= max_chars
                and (next_item["start"] - current["end"]) <= merge_gap
            )
            can_prev = (
                previous is not None
                and len(previous["text"]) + 1 + len(current["text"]) <= max_chars
                and (current["start"] - previous["end"]) <= merge_gap
            )
            if can_next:
                current["text"] = current["text"] + " " + next_item["text"]
                current["end"] = max(current["end"], next_item["end"])
                result.append(current)
                index += 2
                continue
            if can_prev:
                previous["text"] = previous["text"] + " " + current["text"]
                previous["end"] = max(previous["end"], current["end"])
                index += 1
                continue

            current["end"] = current["start"] + min_duration
            if next_item is not None:
                current["end"] = min(current["end"], max(current["start"] + 0.3, next_item["start"] - 0.04))

        if current["end"] <= current["start"]:
            current["end"] = current["start"] + 0.4
        result.append(current)
        index += 1

    return result


def apply_cps(
    segments: list[dict],
    max_cps: float = TARGET_MAX_CPS,
    max_chars: int = MAX_LINE_CHARS * MAX_LINES,
    max_extend: float = MAX_EXTEND,
    min_chars_to_split: int = MIN_CPS_SPLIT_CHARS,
) -> tuple[list[dict], int]:
    """Saniyedeki karakter (CPS) sinirini uygular.

    Yalnizca sureyi uzatir; altyaziyi bolmez. Nedeni: bir altyaziyi ayni
    zaman araliginda parcalara bolmek CPS'i degistirmez (toplam karakter /
    toplam sure aynidir), sadece gereksiz parcalanma yaratir. Uzatma,
    sonraki altyaziya kadar olan sessizlikle sinirlidir.

    `min_chars_to_split` ve `max_chars` geriye donuk uyumluluk icin durur.

    (yeni_segmentler, degistirilen_sayisi) dondurur.
    """
    if max_cps <= 0:
        return list(segments), 0

    ordered = sorted(segments, key=lambda entry: entry["start"])
    output: list[dict] = []
    changed = 0
    tolerance = max_cps + 0.6

    for position, segment in enumerate(ordered):
        start = float(segment["start"])
        end = float(segment["end"])
        text = _clean(segment["text"])
        if not text:
            continue
        if end <= start:
            end = start + 0.5

        hard_limit = (
            float(ordered[position + 1]["start"]) - 0.04
            if position + 1 < len(ordered)
            else None
        )
        duration = end - start
        needed = cue_char_count(text) / max_cps

        if duration >= needed:
            output.append({"start": start, "end": end, "text": text})
            continue

        # Uzatma hedefi: gereken sure, en fazla max_extend kadar.
        target_end = start + min(needed, duration + max_extend)
        if hard_limit is not None:
            target_end = min(target_end, hard_limit)

        # Asla kisaltma: en az ozgun sure korunur (cakisma yoksa).
        floor_end = end if hard_limit is None else min(end, hard_limit)
        target_end = max(target_end, floor_end, start + 0.4)

        if abs(target_end - end) > 0.01:
            changed += 1
        output.append({"start": start, "end": target_end, "text": text})

    return output, changed


# --------------------------------------------------------------------------
# Ana giris noktasi
# --------------------------------------------------------------------------

def finalize_segments(
    segments: list[dict],
    max_line_chars: int = MAX_LINE_CHARS,
    max_lines: int = MAX_LINES,
    min_duration: float = MIN_CUE_DURATION,
    max_cps: float = TARGET_MAX_CPS,
    beautify: bool = True,
) -> list[dict]:
    """Segmentleri temizler, birlestirir, CPS uygular ve satirlara boler."""
    items: list[dict] = []
    for segment in segments:
        text = strip_markup(segment.get("text", ""))
        if not text:
            continue
        start = max(0.0, float(segment.get("start", 0.0)))
        end = float(segment.get("end", start))
        if end <= start:
            end = start + 0.6
        items.append({"start": start, "end": end, "text": text})

    if not items:
        return []

    items.sort(key=lambda entry: (entry["start"], entry["end"]))

    # Ayni metinli ardisik tekrarlari birlestir.
    unique: list[dict] = []
    for item in items:
        if (
            unique
            and item["text"] == unique[-1]["text"]
            and item["start"] - unique[-1]["end"] < 0.5
        ):
            unique[-1]["end"] = max(unique[-1]["end"], item["end"])
        else:
            unique.append(item)
    items = unique

    max_chars = max_line_chars * max_lines
    result = merge_short_cues(items, min_duration, max_chars)
    result = split_oversized(result, max_chars)
    result = merge_short_cues(result, min_duration, max_chars)
    result, _ = apply_cps(result, max_cps, max_chars)

    # Cakismalari kirp.
    for position in range(len(result) - 1):
        if result[position]["end"] > result[position + 1]["start"]:
            limited = result[position + 1]["start"] - 0.04
            result[position]["end"] = max(result[position]["start"] + 0.3, limited)

    if beautify:
        for entry in result:
            entry["text"] = wrap_text(entry["text"], max_line_chars, max_lines)

    return result


def cps_report(segments: list[dict], max_cps: float = TARGET_MAX_CPS) -> dict:
    """Kalite raporu: kac kume CPS sinirini asiyor."""
    over = 0
    worst = 0.0
    tolerance = max_cps + 0.6
    for segment in segments:
        duration = segment["end"] - segment["start"]
        value = cps(segment["text"], duration)
        worst = max(worst, value)
        if value > tolerance:
            over += 1
    return {
        "total": len(segments),
        "over_cps": over,
        "max_cps": round(worst, 1),
        "limit": max_cps,
    }


# --------------------------------------------------------------------------
# SRT yazma / okuma
# --------------------------------------------------------------------------

def to_srt(segments: list[dict]) -> str:
    blocks: list[str] = []
    number = 0
    for segment in segments:
        text = segment.get("text", "")
        if not text.strip():
            continue
        number += 1
        blocks.append(
            f"{number}\n"
            f"{_format_timestamp(segment['start'])} --> {_format_timestamp(segment['end'])}\n"
            f"{text}\n"
        )
    return "\n".join(blocks)


def write_srt(path: str | Path, segments: list[dict]) -> Path:
    """SRT dosyasini UTF-8 (BOM'suz) olarak yazar."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = to_srt(segments)
    if not content.strip():
        raise ValueError("Altyazı içeriği boş; SRT üretilemedi.")
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return target


def read_srt(path: str | Path) -> list[dict]:
    """SRT dosyasini okur; BOM, CRLF, HTML etiketleri ve numarasiz bloklar.

    Yaygin bozuk dosyalara dayanikli: zaman damgasi satiri bulunursa blok
    kabul edilir, numara satiri zorunlu degildir.
    """
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1254", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("{\\an8}", "").replace("{\\an7}", "")

    time_pattern = re.compile(
        r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
    )

    entries: list[dict] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines:
            continue

        time_index = None
        for index, line in enumerate(lines):
            if "-->" in line:
                time_index = index
                break
        if time_index is None:
            continue

        match = time_pattern.search(lines[time_index])
        if not match:
            continue

        body = " ".join(strip_markup(line) for line in lines[time_index + 1 :]).strip()
        if not body:
            continue

        entries.append(
            {
                "start": _parse_timestamp(match.group(1)),
                "end": _parse_timestamp(match.group(2)),
                "text": body,
            }
        )

    entries.sort(key=lambda entry: entry["start"])
    # Cakisan/geri giden zamanlari duzelt.
    for index, entry in enumerate(entries):
        if entry["end"] <= entry["start"]:
            entry["end"] = entry["start"] + 1.0
        if index + 1 < len(entries) and entry["end"] > entries[index + 1]["start"]:
            entry["end"] = max(entry["start"] + 0.3, entries[index + 1]["start"] - 0.04)
    return entries


def segments_to_words(segments: list[dict]) -> list[dict]:
    """SRT kumelerini sozde kelimelere cevirir (ceviri icin baglam).

    SRT'de kelime zaman damgasi yoktur; her kelime kume icinde esit
    paylastirilir. Ceviri sonrasi zaman dagitimi icin yeterlidir.
    """
    words: list[dict] = []
    for segment in segments:
        tokens = _clean(segment["text"]).split()
        if not tokens:
            continue
        start = float(segment["start"])
        end = float(segment["end"])
        if end <= start:
            end = start + 0.5
        step = (end - start) / len(tokens)
        for index, token in enumerate(tokens):
            words.append(
                {
                    "text": token,
                    "start": start + index * step,
                    "end": start + (index + 1) * step,
                }
            )
    return words


def total_characters(segments: list[dict]) -> int:
    return sum(len(segment.get("text", "")) for segment in segments)


def total_duration(segments: list[dict]) -> float:
    if not segments:
        return 0.0
    return max(entry["end"] for entry in segments) - min(entry["start"] for entry in segments)
