"""Terim sozlugu (glossary): kaynak terimi ceviri boyunca korur.

Neden yer tutucu?
    NLLB bir marka/terimi kafasina gore cevirebilir ("OpenAI" -> "Yapay
    zeka"). Terimi ceviriden ONCE ``[[G0]]`` gibi bir yer tutucuyla
    degistirip ceviriden SONRA hedef karsiligini yaziyoruz. Yer tutucular
    NLLB tarafindan korunuyor (olculdu: ``[[0]]`` ve ``__0__`` aynen
    cikiyor; ``⟦0⟧`` ve ``«0»`` bozuluyor).

    Yer tutucu kaybolursa (uzun/karisik cumlede olabilir) guvenli geri
    dusus: kaynak terim cikti metninde aynen geciyorsa dogrudan degistirilir.
    Hicbiri olmazsa metin oldugu gibi kalir; altyazi asla ``[[G0]]``
    sizdirmaz.

Dosya bicimi (UTF-8):
    # yorum satiri
    kaynak<TAB>hedef
    kaynak<TAB>hedef<TAB>en>tr      # yalnizca bu dil ciftinde
    kaynak -> hedef                 # ok yazimi da kabul edilir
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "Glossary",
    "GlossaryEntry",
    "GlossaryError",
    "RestoreReport",
    "load_glossary",
]

_PLACEHOLDER_TEMPLATE = "[[G{}]]"
_PLACEHOLDER_RE = re.compile(r"\[\[G(\d+)\]\]")
_PAIR_RE = re.compile(r"^([a-z]{2,3})>([a-z]{2,3})$")

# Uzunluk koruyan harf katlama: 'İ'.lower() iki karakter urettigi icin
# ayrica eslenir. 'I' ve 'ı' da 'i' olur; eslesmede yanlis negatif yerine
# nadir yanlis pozitif tercih edilir.
_FOLD_MAP = str.maketrans({"İ": "i", "I": "i", "ı": "i"})


class GlossaryError(ValueError):
    """Sozluk dosyasi okunamadi veya bicimi bozuk."""


@dataclass(frozen=True)
class GlossaryEntry:
    source: str
    target: str
    pair: str = ""  # "" = tum diller, "en>tr" = yalniz bu cift

    def matches(self, source_lang: str, target_lang: str) -> bool:
        if not self.pair:
            return True
        src, _, tgt = self.pair.partition(">")
        return src == (source_lang or "").lower() and tgt == (target_lang or "").lower()


@dataclass(frozen=True)
class RestoreReport:
    """Geri yazma sonucu: kac terim uygulandi, hangileri kayboldu."""

    applied: int = 0
    placeholders_lost: int = 0
    fallback_used: int = 0
    unresolved: tuple[str, ...] = ()


def _fold(text: str) -> str:
    """Kucuk harfe indirger; uzunluk korunur (konumlar kaymaz)."""
    folded = text.translate(_FOLD_MAP)
    parts: list[str] = []
    for char in folded:
        low = char.lower()
        parts.append(low if len(low) == 1 else char)
    return "".join(parts)


def _split_line(line: str) -> list[str] | None:
    if "\t" in line:
        return line.split("\t")
    if " -> " in line:
        return line.split(" -> ")
    return None


def _dedupe(entries: list[GlossaryEntry]) -> list[GlossaryEntry]:
    """Ayni (terim, dil cifti) icin son satir gecerlidir; sira korunur."""
    order: list[tuple[str, str]] = []
    values: dict[tuple[str, str], GlossaryEntry] = {}
    for entry in entries:
        key = (_fold(entry.source), entry.pair)
        if key not in values:
            order.append(key)
        values[key] = entry
    return [values[key] for key in order]


def load_glossary(path: str | Path) -> Glossary:
    """TSV/ok bicimli sozluk dosyasini okur."""
    file_path = Path(path)
    if not file_path.exists():
        raise GlossaryError(f"Sozluk dosyasi bulunamadi: {file_path}")
    try:
        text = file_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise GlossaryError(f"Sozluk dosyasi okunamadi: {exc}") from exc

    entries: list[GlossaryEntry] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Ayiriciyi strip'ten ONCE ara: "OpenAI\t" satirinda bos hedef
        # sutunu vardir ve bu hata olmalidir, sessizce yutulmamalidir.
        parts = _split_line(raw)
        if parts is None:
            raise GlossaryError(
                f"Satir {number}: sutun ayirici yok (sekme veya ' -> ' bekleniyor): {line[:40]}"
            )
        parts = [part.strip() for part in parts]
        if len(parts) < 2:
            raise GlossaryError(f"Satir {number}: en az 2 sutun gerekli: {line[:40]}")
        if len(parts) > 3:
            raise GlossaryError(f"Satir {number}: en fazla 3 sutun gerekli: {line[:40]}")

        source, target = parts[0], parts[1]
        pair = parts[2] if len(parts) == 3 else ""

        # Baslik satirlari: "kaynak	hedef" / "source	target"
        if number and not entries and pair == "" and source.lower() in {
            "kaynak",
            "source",
            "term",
        } and target.lower() in {"hedef", "target", "translation"}:
            continue

        if not source:
            raise GlossaryError(f"Satir {number}: kaynak terim bos")
        if not target:
            raise GlossaryError(f"Satir {number}: hedef terim bos (kaynak: {source})")
        if pair and not _PAIR_RE.match(pair.lower()):
            raise GlossaryError(
                f"Satir {number}: dil cifti 'en>tr' biciminde olmali, bulunan: {pair}"
            )
        entries.append(
            GlossaryEntry(
                source=source,
                target=target,
                pair=pair.lower() if pair else "",
            )
        )

    if not entries:
        raise GlossaryError("Sozluk bos: en az bir terim gerekli.")
    return Glossary(entries)


class Glossary:
    """Terim listesi; koruma/geri yazma islemleri."""

    def __init__(self, entries: tuple[GlossaryEntry, ...] | list[GlossaryEntry]) -> None:
        self.entries: tuple[GlossaryEntry, ...] = tuple(_dedupe(list(entries)))
        self._patterns: dict[str, re.Pattern[str]] = {}

    # -- temel -------------------------------------------------------------
    def __len__(self) -> int:
        return len(self.entries)

    def __bool__(self) -> bool:
        return bool(self.entries)

    def entries_for(
        self, source_lang: str = "", target_lang: str = ""
    ) -> tuple[GlossaryEntry, ...]:
        return tuple(
            entry for entry in self.entries if entry.matches(source_lang, target_lang)
        )

    # -- eslesme -----------------------------------------------------------
    def _pattern(self, source: str) -> re.Pattern[str]:
        pattern = self._patterns.get(source)
        if pattern is not None:
            return pattern
        folded = _fold(source)
        expression = re.escape(folded)
        if source[:1].isalnum():
            expression = r"(?<!\w)" + expression
        if source[-1:].isalnum():
            expression = expression + r"(?!\w)"
        pattern = re.compile(expression)
        self._patterns[source] = pattern
        return pattern

    def _ordered(self, entries: tuple[GlossaryEntry, ...]) -> list[tuple[int, GlossaryEntry]]:
        """Uzun terim once; esitlikte tanim sirasi."""
        return sorted(
            enumerate(entries),
            key=lambda item: (-len(_fold(item[1].source)), item[0]),
        )

    def _replace_term(
        self, text: str, entry: GlossaryEntry, replacement: str
    ) -> tuple[str, int]:
        folded = _fold(text)
        matches = list(self._pattern(entry.source).finditer(folded))
        if not matches:
            return text, 0
        # Var olan yer tutucularin icine girme: "G0" gibi bir terim
        # "[[G0]]" metninin icinde eslesip yer tutucuyu bozabilir.
        protected_spans = [match.span() for match in _PLACEHOLDER_RE.finditer(text)]
        if protected_spans:
            matches = [
                match
                for match in matches
                if not any(
                    match.start() < end and start < match.end()
                    for start, end in protected_spans
                )
            ]
            if not matches:
                return text, 0
        pieces: list[str] = []
        last = 0
        for match in matches:
            pieces.append(text[last : match.start()])
            pieces.append(replacement)
            last = match.end()
        pieces.append(text[last:])
        return "".join(pieces), len(matches)

    # -- koruma ------------------------------------------------------------
    def protect(
        self, text: str, source_lang: str = "", target_lang: str = ""
    ) -> tuple[str, dict[str, str]]:
        """Kaynak terimleri ``[[Gn]]`` yer tutuculariyla degistirir.

        Donen sozluk: yer tutucu -> hedef terim.
        """
        entries = self.entries_for(source_lang, target_lang)
        if not text or not entries:
            return text, {}

        mapping: dict[str, str] = {}
        result = text
        for index, entry in self._ordered(entries):
            placeholder = _PLACEHOLDER_TEMPLATE.format(index)
            result, count = self._replace_term(result, entry, placeholder)
            if count:
                mapping[placeholder] = entry.target
        return result, mapping

    # -- geri yazma --------------------------------------------------------
    def restore_full(
        self,
        text: str,
        mapping: dict[str, str],
        source_lang: str = "",
        target_lang: str = "",
    ) -> tuple[str, RestoreReport]:
        """Yer tutuculari hedef terimlerle degistirir; kaybolanlari raporlar."""
        if not text or not mapping:
            return text, RestoreReport()

        applied: list[str] = []

        def replace(match: re.Match[str]) -> str:
            placeholder = match.group(0)
            target = mapping.get(placeholder)
            if target is None:
                return placeholder
            applied.append(placeholder)
            return target

        result = _PLACEHOLDER_RE.sub(replace, text)

        entries = self.entries_for(source_lang, target_lang)
        lost = 0
        fallback = 0
        unresolved: list[str] = []
        for placeholder, target in mapping.items():
            if placeholder in applied:
                continue
            lost += 1
            index_match = _PLACEHOLDER_RE.fullmatch(placeholder)
            index = int(index_match.group(1)) if index_match else -1
            entry = entries[index] if 0 <= index < len(entries) else None
            if entry is None:
                unresolved.append(placeholder)
                continue
            result, count = self._replace_term(result, entry, target)
            if count:
                fallback += count
            else:
                unresolved.append(entry.source)

        return result, RestoreReport(
            applied=len(applied) + fallback,
            placeholders_lost=lost,
            fallback_used=fallback,
            unresolved=tuple(unresolved),
        )

    def restore(
        self,
        text: str,
        mapping: dict[str, str],
        source_lang: str = "",
        target_lang: str = "",
    ) -> tuple[str, int]:
        result, report = self.restore_full(text, mapping, source_lang, target_lang)
        return result, report.applied

    def apply(self, text: str, source_lang: str = "", target_lang: str = "") -> str:
        """Ceviri yapmadan dogrudan terim degistirir (yardimci)."""
        entries = self.entries_for(source_lang, target_lang)
        if not text or not entries:
            return text
        result = text
        for _, entry in self._ordered(entries):
            result, _count = self._replace_term(result, entry, entry.target)
        return result
