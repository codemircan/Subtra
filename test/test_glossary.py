"""Terim sozlugu (glossary) birim testleri — model/ffmpeg gerekmez.

Sozluk bicimi (TSV):
    # yorum
    kaynak<TAB>hedef
    kaynak<TAB>hedef<TAB>en>tr     (istege bagli dil cifti)
    kaynak -> hedef                 (ok yazimi da kabul edilir)
"""

import io
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import glossary  # noqa: E402
from glossary import Glossary, GlossaryError, GlossaryEntry, load_glossary  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


def write_temp(text: str, suffix: str = ".tsv") -> Path:
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=suffix, delete=False, newline="\n"
    )
    handle.write(text)
    handle.close()
    return Path(handle.name)


print("=" * 66)
print("TERIM SOZLUGU (GLOSSARY)")
print("=" * 66)

# --- 1) Dosya ayristirma ---------------------------------------------------
print("\n1) Dosya ayristirma")
path = write_temp(
    "\ufeff# Subtra terim sozlugu\n"
    "\n"
    "kaynak\thedef\n"
    "OpenAI\tOpenAI\n"
    "prompt\tkomut\n"
    "GPU\tgrafik islemcisi\ten>tr\n"
    "token -> jeton\n"
)
g = load_glossary(path)
check("3 sutunlu/harita basligi atlandi", len(g) == 4, str(len(g)))
check("ilk terim", g.entries[0] == GlossaryEntry("OpenAI", "OpenAI"))
check("ok yazimi", g.entries[3] == GlossaryEntry("token", "jeton"))
check("dil cifti okundu", g.entries[2].pair == "en>tr")
path.unlink(missing_ok=True)

# --- 2) Hatalar ------------------------------------------------------------
print("\n2) Hatali dosyalar net hata vermeli")
for label, text, needle in (
    ("bos hedef", "OpenAI\t\n", "hedef"),
    ("bos kaynak", "\tOpenAI\n", "kaynak"),
    ("bozuk dil cifti", "a\tb\ten-tr\n", "dil"),
    ("tek sutun", "sadece_bir_kelime\n", "sutun"),
):
    bad = write_temp(text)
    try:
        load_glossary(bad)
        check(label, False, "hata beklenirdi")
    except GlossaryError as exc:
        check(label, needle in str(exc).lower(), str(exc)[:60])
    except Exception as exc:  # noqa: BLE001
        check(label, False, f"yanlis tur: {type(exc).__name__}: {exc}")
    bad.unlink(missing_ok=True)

try:
    load_glossary(Path("olmayan_dosya_12345.tsv"))
    check("olmayan dosya", False)
except GlossaryError as exc:
    check("olmayan dosya", "bulunamadi" in str(exc).lower(), str(exc)[:50])

# --- 3) Dil filtresi -------------------------------------------------------
print("\n3) Dil cifti filtresi")
g = Glossary(
    (
        GlossaryEntry("GPU", "grafik islemcisi", "en>tr"),
        GlossaryEntry("GPU", "graphics card", "en>de"),
        GlossaryEntry("token", "jeton"),
    )
)
check("en->tr iki terim", len(g.entries_for("en", "tr")) == 2)
check("en->de iki terim", len(g.entries_for("en", "de")) == 2)
check("tr->en yalniz genel", len(g.entries_for("tr", "en")) == 1)
check("genel terim her dilde", g.entries_for("ja", "ko")[0].source == "token")

# --- 4) Koruma / geri yazma ------------------------------------------------
print("\n4) Koruma ve geri yazma")
g = Glossary((GlossaryEntry("OpenAI", "OpenAI"), GlossaryEntry("prompt", "komut")))
protected, mapping = g.protect("The prompt for OpenAI is short.", "en", "tr")
check("iki yer tutucu", len(mapping) == 2, str(mapping))
check("metinde yer tutucu var", "[[G" in protected, protected)
check("kaynak terim kalmadi", "prompt" not in protected.lower(), protected)

restored, applied = g.restore(
    "[[G0]] icin [[G1]] kisa.", mapping, "en", "tr"
)
check("hedef terimler yazildi", "komut" in restored and "OpenAI" in restored, restored)
check("uygulanan sayisi", applied == 2, str(applied))
check("yer tutucu sizmadi", "[[G" not in restored, restored)

# --- 5) Yer tutucu kaybolursa dogrudan degistirme --------------------------
print("\n5) Yer tutucu kaybolursa dogrudan degistirme (guvenli geri dusus)")
g = Glossary((GlossaryEntry("OpenAI", "OpenAI"),))
_, mapping = g.protect("OpenAI is fast.", "en", "tr")
restored, report = g.restore_full("OpenAI hizlidir.", mapping, "en", "tr")
check("dogrudan degistirme calisti", report.fallback_used == 1, str(report))
check("sonuc dogru", restored == "OpenAI hizlidir.", restored)
check("cozulemeyen yok", report.unresolved == (), str(report.unresolved))

g = Glossary((GlossaryEntry("OpenAI", "OpenAI"),))
_, mapping = g.protect("OpenAI is fast.", "en", "tr")
restored, report = g.restore_full("Oldukca hizlidir.", mapping, "en", "tr")
check("hic bulunamazsa rapor", report.unresolved == ("OpenAI",), str(report))
check("metin bozulmadi", restored == "Oldukca hizlidir.", restored)
check("yer tutucu yok", "[[G" not in restored)

# --- 6) Eslesme kurallari --------------------------------------------------
print("\n6) Eslesme kurallari")
g = Glossary((GlossaryEntry("C++", "C++"), GlossaryEntry("(beta)", "(beta)")))
protected, mapping = g.protect("C++ (beta) surumu", "en", "tr")
check("regex ozel karakterler", len(mapping) == 2, protected)
check("metin ayni", protected.count("[[G") == 2, protected)

g = Glossary((GlossaryEntry("net", "network"),))
check("kelime ortasinda eslesmez", g.apply("internet iyidir", "en", "tr") == "internet iyidir")
check("tam kelime eslesir", g.apply("net hizli", "en", "tr") == "network hizli")

g = Glossary((GlossaryEntry("yapay zeka", "AI"), GlossaryEntry("yapay", "artificial")))
protected, mapping = g.protect("yapay zeka guclu", "tr", "en")
check("en uzun terim kazanir", list(mapping.values()) == ["AI"], str(mapping))

# --- 7) Turkce buyuk/kucuk harf -------------------------------------------
print("\n7) Turkce buyuk/kucuk harf")
g = Glossary((GlossaryEntry("istanbul", "Istanbul"), GlossaryEntry("İzmir", "Izmir")))
check("İ -> i eslesir", g.apply("İSTANBUL guzel", "tr", "en") == "Istanbul guzel")
check("izmir -> İzmir eslesir", g.apply("izmir guzel", "tr", "en") == "Izmir guzel")
check("buyuk I eslesir", g.apply("ISTANBUL guzel", "tr", "en") == "Istanbul guzel")

# --- 8) Sozluk yok / bos ---------------------------------------------------
print("\n8) Bos sozluk")
empty = Glossary(())
check("bool false", not empty)
check("bos metin", empty.apply("", "en", "tr") == "")
check("protect no-op", empty.protect("metin", "en", "tr") == ("metin", {}))

# --- 9) Ayni terim iki kez: sonuncusu gecerli ------------------------------
print("\n9) Yinelenen terim")
dup = write_temp("GPU\tekran karti\nGPU\tgrafik islemcisi\n")
g = load_glossary(dup)
check("tek kayit", len(g) == 1, str(len(g)))
check("son deger kazandi", g.entries[0].target == "grafik islemcisi")
dup.unlink(missing_ok=True)

failed = [label for label, ok, _ in checks if not ok]
print()
if failed:
    print(f"GLOSSARY TESTI BASARISIZ: {failed}")
    traceback.print_exc()
    sys.exit(1)
print(f"{len(checks)} kontrol gecti")
print("GLOSSARY TESTI: GECTI")
