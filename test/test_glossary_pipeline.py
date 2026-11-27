"""Sozluk + ceviri akisi (sahte translator) — model gerekmez.

Gercek NLLB'ye bagimli olmadan koruma/geri yazma akisini ve pipeline
sirasini dogrular. Gercek model testi: test/test_glossary_real.py
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from glossary import Glossary, GlossaryEntry  # noqa: E402
from translator import TranslationPipeline, translate_sentences  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


class FakeTranslator:
    """translate_batch cagrisini taklit eder; donusumu test belirler."""

    def __init__(self, transform) -> None:
        self.transform = transform
        self.seen: list[list[str]] = []

    def translate_batch(
        self,
        texts,
        src_lang,
        tgt_lang,
        progress_cb=None,
        cancel_event=None,
        batch_size=None,
    ):
        self.seen.append(list(texts))
        if progress_cb:
            progress_cb(1.0)
        return [self.transform(text) for text in texts]


def sentences(*texts: str) -> list[dict]:
    return [{"text": text, "start": i, "end": i + 1} for i, text in enumerate(texts)]


print("=" * 66)
print("SOZLUK + CEVIRI AKISI (sahte translator)")
print("=" * 66)

# --- 1) Yer tutucu translator'a gidiyor, hedef terim ciktiya geliyor -------
print("\n1) Koruma -> ceviri -> geri yazma")
gloss = Glossary((GlossaryEntry("OpenAI", "OpenAI"), GlossaryEntry("prompt", "komut")))
fake = FakeTranslator(lambda text: text.replace(" is ", " ").replace(" the ", " "))
result = translate_sentences(
    fake,
    sentences("The prompt for OpenAI is short."),
    "eng_Latn",
    "tur_Latn",
    glossary=gloss,
    source_lang="en",
    target_lang="tr",
)
check("translator yer tutucu gordu", "[[G" in fake.seen[0][0], fake.seen[0][0])
check("hedef terim yazildi", "komut" in result[0]["translated"], result[0]["translated"])
check("marka korundu", "OpenAI" in result[0]["translated"], result[0]["translated"])
check("uygulanan sayisi", result[0].get("glossary_applied") == 2, str(result[0]))
check("yer tutucu sizmadi", "[[" not in result[0]["translated"], result[0]["translated"])

# --- 2) Yer tutucu kaybolursa dogrudan degistirme -------------------------
print("\n2) Yer tutucu kayboldu (translator metni yeniden yazdi)")
gloss = Glossary((GlossaryEntry("OpenAI", "OpenAI"),))
fake = FakeTranslator(lambda text: "OpenAI hizli bir sirkettir.")
result = translate_sentences(
    fake,
    sentences("OpenAI is a fast company."),
    "eng_Latn",
    "tur_Latn",
    glossary=gloss,
    source_lang="en",
    target_lang="tr",
)
check("dogrudan degistirme", result[0]["translated"] == "OpenAI hizli bir sirkettir.", result[0]["translated"])
check("kayip yok", not result[0].get("glossary_lost"), str(result[0]))

# --- 3) Cozulemeyen terim raporlaniyor -----------------------------------
print("\n3) Terim ne yer tutucuda ne ciktida")
fake = FakeTranslator(lambda text: "Tamamen farkli bir cumle.")
result = translate_sentences(
    fake,
    sentences("OpenAI is fast."),
    "eng_Latn",
    "tur_Latn",
    glossary=gloss,
    source_lang="en",
    target_lang="tr",
)
check("kayip listelendi", result[0].get("glossary_lost") == ["OpenAI"], str(result[0]))
check("altyazi metni temiz", "[[" not in result[0]["translated"], result[0]["translated"])

# --- 4) Ayni dil: dogrudan degistirme ------------------------------------
print("\n4) Kaynak = hedef dil")
gloss = Glossary((GlossaryEntry("prompt", "komut"),))
fake = FakeTranslator(lambda text: "cagrilmamali")
result = translate_sentences(
    fake,
    sentences("Bu prompt iyi."),
    "tur_Latn",
    "tur_Latn",
    glossary=gloss,
    source_lang="tr",
    target_lang="tr",
)
check("translator cagrilmadi", fake.seen == [], str(fake.seen))
check("terim degisti", result[0]["translated"] == "Bu komut iyi.", result[0]["translated"])

# --- 5) Dil cifti eslesmiyorsa dokunma -----------------------------------
print("\n5) Dil cifti filtresi akista")
gloss = Glossary((GlossaryEntry("prompt", "komut", "en>de"),))
fake = FakeTranslator(lambda text: text)
result = translate_sentences(
    fake,
    sentences("The prompt is here."),
    "eng_Latn",
    "tur_Latn",
    glossary=gloss,
    source_lang="en",
    target_lang="tr",
)
check("en>de terimi uygulanmadi", "prompt" in result[0]["translated"], result[0]["translated"])

# --- 6) Pipeline: sira korunur, terim uygulanir --------------------------
print("\n6) TranslationPipeline")
gloss = Glossary((GlossaryEntry("GPU", "grafik islemcisi"),))
fake = FakeTranslator(lambda text: text.replace("The ", ""))
pipeline = TranslationPipeline(
    fake,
    "eng_Latn",
    "tur_Latn",
    batch_size=2,
    glossary=gloss,
    source_lang="en",
    target_lang="tr",
)
for sentence in sentences("The GPU is fast.", "The GPU is new.", "The GPU is cool."):
    pipeline.submit(sentence)
output = pipeline.finish()
check("3 sonuc", len(output) == 3, str(len(output)))
check("sira korundu", [s["text"] for s in output] == [
    "The GPU is fast.", "The GPU is new.", "The GPU is cool."
], str([s["text"] for s in output]))
check("terim her cumlede", all("grafik islemcisi" in s["translated"] for s in output), str([s["translated"] for s in output]))
check("yer tutucu yok", all("[[" not in s["translated"] for s in output))

# --- 7) Sozluk yoksa davranis degismez -----------------------------------
print("\n7) Sozluk yok")
fake = FakeTranslator(lambda text: text.upper())
result = translate_sentences(fake, sentences("hello"), "eng_Latn", "tur_Latn")
check("ceviri normal", result[0]["translated"] == "HELLO", result[0]["translated"])
check("ekstra anahtar yok", "glossary_applied" not in result[0], str(result[0]))

failed = [label for label, ok, _ in checks if not ok]
print()
if failed:
    print(f"SOZLUK AKISI BASARISIZ: {failed}")
    sys.exit(1)
print(f"{len(checks)} kontrol gecti")
print("SOZLUK AKISI: GECTI")
