"""Altyazi motoru testleri (model gerekmez)."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from subtitles import (  # noqa: E402
    apply_cps,
    cps,
    cps_report,
    finalize_segments,
    group_sentences,
    read_srt,
    sentences_to_cues,
    to_srt,
    write_srt,
)


def make_words(text: str, step: float = 0.5, word_len: float = 0.45):
    words = []
    t = 0.0
    for token in text.split():
        words.append({"text": token, "start": round(t, 2), "end": round(t + word_len, 2)})
        t += step
    return words


def check(condition: bool, label: str) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        raise SystemExit(1)


print("1) Kelime -> cumle gruplama")
words = make_words(
    "Merhaba ve hoş geldiniz. Bu otomatik altyazı sisteminin bir testidir. Kısa bir cümle."
)
sentences = group_sentences(words)
for sentence in sentences:
    print(f"   [{sentence['start']:.2f}-{sentence['end']:.2f}] {sentence['text']}")
check(len(sentences) == 3, "3 cümle bulundu")

print("\n2) Kelime damgasindan kume (ceviri yok)")
cues = sentences_to_cues(sentences, translated=False)
for cue in cues:
    print(f"   [{cue['start']:.2f}-{cue['end']:.2f}] {cue['text']}")
check(all(len(c["text"]) <= 84 for c in cues), "hepsi 2 satıra sığar")

print("\n3) Cevrilmis metinden kume (oransal zaman)")
translated = [dict(s, translated=s["text"].upper()) for s in sentences]
cues2 = sentences_to_cues(translated, translated=True)
for cue in cues2:
    print(f"   [{cue['start']:.2f}-{cue['end']:.2f}] {cue['text']}")
check(len(cues2) == 3, "cevrilmis 3 kume")

print("\n4) CPS: cok hizli altyazi (uzatma veya bolme)")
fast = [{"start": 0.0, "end": 1.0, "text": "Bu çok uzun bir metin ve bir saniyede okunamaz kesinlikle"}]
fixed, changed = apply_cps(fast, max_cps=18)
print(f"   degistirilen: {changed}, kume sayisi: {len(fixed)}")
for cue in fixed:
    print(f"   [{cue['start']:.2f}-{cue['end']:.2f}] cps={cps(cue['text'], cue['end']-cue['start']):.1f} {cue['text']}")
check(changed >= 1, "CPS düzeltmesi uygulandı")
check(all(cps(c["text"], c["end"] - c["start"]) <= 18.6 for c in fixed), "CPS sınırı sağlandı")

print("\n4b) CPS: sonraki altyazi engelliyor -> bolunmemeli, uzatilmali")
blocked = [
    {"start": 0.0, "end": 1.0, "text": "Bu çok uzun bir metin ve bir saniyede okunamaz kesinlikle"},
    {"start": 1.2, "end": 3.0, "text": "Sonraki altyazı"},
]
fixed_b, _ = apply_cps(blocked, max_cps=18)
print(f"   kume sayisi: {len(fixed_b)} (bolme yok)")
for cue in fixed_b:
    print(f"   [{cue['start']:.2f}-{cue['end']:.2f}] cps={cps(cue['text'], cue['end']-cue['start']):.1f} {cue['text']}")
check(len(fixed_b) == 2, "bölünmedi (bölmek CPS'i düşürmez)")
check(fixed_b[0]["end"] <= 1.2, "sonraki altyazıya taşmadı")

print("\n5) Uzun tek kelime (bolunemez) -> sure uzatma")
long_word = [{"start": 0.0, "end": 0.5, "text": "Olağanüstükuvvetlendirilmiş"}]
fixed2, _ = apply_cps(long_word, max_cps=18)
print(f"   [{fixed2[0]['start']:.2f}-{fixed2[0]['end']:.2f}] süre={fixed2[0]['end']-fixed2[0]['start']:.2f}")
check(fixed2[0]["end"] - fixed2[0]["start"] > 0.5, "süre uzatıldı")

print("\n6) finalize_segments uctan uca")
everything = sentences_to_cues(sentences, translated=False)
final = finalize_segments(everything)
print(to_srt(final))
for entry in final:
    lines = entry["text"].split("\n")
    check(len(lines) <= 2, f"en fazla 2 satır ({len(lines)})")
print("   rapor:", cps_report(final))

print("\n7) SRT yaz/oku gidis-donus (BOM + CRLF + HTML)")
path = "test/_roundtrip.srt"
write_srt(path, final)
import pathlib

data = pathlib.Path(path).read_bytes()
pathlib.Path(path).write_bytes(b"\xef\xbb\xbf" + data.replace(b"\n", b"\r\n"))
back = read_srt(path)
print(f"   okunan: {len(back)} blok")
check(len(back) == len(final), "blok sayısı korundu")
check(back[0]["text"].startswith("Merhaba"), "metin doğru")

print("\n8) Bozuk/numarasiz SRT")
pathlib.Path("test/_broken.srt").write_text(
    "00:00:01,000 --> 00:00:03,000\n<i>Etiketli</i> metin\n\n"
    "2\n00:00:04,500 --> 00:00:06,000\nİkinci blok\n",
    encoding="utf-8",
)
broken = read_srt("test/_broken.srt")
for entry in broken:
    print(f"   [{entry['start']:.2f}-{entry['end']:.2f}] {entry['text']}")
check(len(broken) == 2, "iki blok okundu")
check(broken[0]["text"] == "Etiketli metin", "HTML etiketi temizlendi")

pathlib.Path(path).unlink(missing_ok=True)
pathlib.Path("test/_broken.srt").unlink(missing_ok=True)

print("\nTUM ALTYAZI TESTLERI GECTI")
