"""transcriber birim testleri — model/ffmpeg gerekmez.

Kapsam:
  * `_pseudo_words`: kelime damgasi kapaliyken segment metnini bolme
  * `flatten_words`: tekrarlari eleme, siralama
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from transcriber import _pseudo_words, flatten_words  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


print("=" * 66)
print("TRANSCRIBER BIRIM TESTLERI")
print("=" * 66)

print("\n1) _pseudo_words: temel bolme")
words = _pseudo_words("Merhaba ve hos geldiniz.", 1.0, 3.0)
check("kelime sayisi 4", len(words) == 4, str(len(words)))
check("metinler korundu",
      [w["text"] for w in words] == ["Merhaba", "ve", "hos", "geldiniz."],
      str([w["text"] for w in words]))
check("ilk kelime segment basinda", abs(words[0]["start"] - 1.0) < 1e-6, str(words[0]["start"]))
check("son kelime segment sonunda", abs(words[-1]["end"] - 3.0) < 1e-6, str(words[-1]["end"]))
check("sirali ve ortusmesiz",
      all(words[i]["end"] <= words[i + 1]["start"] + 1e-6 for i in range(len(words) - 1)))
check("hepsi pozitif sure", all(w["end"] > w["start"] for w in words))
check("uzun kelime daha uzun sure",
      (words[0]["end"] - words[0]["start"]) > (words[1]["end"] - words[1]["start"]),
      f'{words[0]["end"] - words[0]["start"]:.2f} vs {words[1]["end"] - words[1]["start"]:.2f}')

print("\n2) _pseudo_words: sinir durumlari")
check("bos metin -> bos liste", _pseudo_words("", 0.0, 1.0) == [])
check("yalniz bosluk -> bos liste", _pseudo_words("   ", 0.0, 1.0) == [])
sifir = _pseudo_words("a b", 5.0, 5.0)
check("sifir surede kelime uretir", len(sifir) == 2, str(len(sifir)))
check("sifir surede pozitif uzunluk", all(w["end"] > w["start"] for w in sifir))
ters = _pseudo_words("a b", 3.0, 1.0)
check("ters aralikta cokme yok", len(ters) == 2, str(len(ters)))

print("\n3) flatten_words: tekrarlari eler")
segments = [
    {"start": 0.0, "end": 1.3, "words": [
        {"text": "bir", "start": 0.0, "end": 0.9},
        {"text": "iki", "start": 0.9, "end": 1.3},
    ]},
    {"start": 1.0, "end": 2.0, "words": [
        # dilim sinirinda tekrar: 0.3 sn geriden basliyor (esik 0.25)
        {"text": "iki", "start": 1.0, "end": 1.6},
        {"text": "uc", "start": 1.6, "end": 2.0},
    ]},
]
flat = flatten_words(segments)
check("tekrar elendi", [w["text"] for w in flat] == ["bir", "iki", "uc"],
      str([w["text"] for w in flat]))

# Esik altindaki (0.1 sn) ortusme tekrar sayilmaz: gercek ardisik kelime.
kisa = flatten_words([
    {"words": [{"text": "a", "start": 0.0, "end": 1.0}]},
    {"words": [{"text": "b", "start": 0.9, "end": 1.5}]},
])
check("kisa ortusme korunur", [w["text"] for w in kisa] == ["a", "b"],
      str([w["text"] for w in kisa]))
check("bos metinli kelime atilir",
      flatten_words([{"words": [{"text": "  ", "start": 0, "end": 1}]}]) == [])
check("kelimesiz segment cokme yok", flatten_words([{"text": "x"}]) == [])

print("\n4) _pseudo_words ciktisi flatten_words ile uyumlu")
segment_words = _pseudo_words("bir iki uc dort", 0.0, 2.0)
flat2 = flatten_words([{"words": segment_words}])
check("4 kelime korundu", len(flat2) == 4, str(len(flat2)))

failed = [label for label, ok, _ in checks if not ok]
print()
if failed:
    print(f"TRANSCRIBER BIRIM TESTI BASARISIZ: {failed}")
    sys.exit(1)
print(f"{len(checks)} kontrol gecti")
print("TRANSCRIBER BIRIM TESTI: GECTI")
