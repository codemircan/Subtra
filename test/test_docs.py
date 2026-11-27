"""Subtra icin dokumantasyon uyum testi — README'lerdeki iddialar kaynakla uyusuyor mu?"""

import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
EN = (ROOT / "README.md").read_text(encoding="utf-8")
TR = (ROOT / "docs" / "README.tr.md").read_text(encoding="utf-8")

checks: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


print("=" * 66)
print("DOKUMANTASYON UYUMU")
print("=" * 66)

print("\n1) Test listesi gercek dosyalarla uyusuyor")
listed_en = set(re.findall(r"py (test/test_[\w]+\.py)", EN))
listed_tr = set(re.findall(r"py (test/test_[\w]+\.py)", TR))
existing = {f"test/{path.name}" for path in (ROOT / "test").glob("test_*.py")}
missing_en = sorted(listed_en - existing)
missing_tr = sorted(listed_tr - existing)
check("README'deki testler var", not missing_en, str(missing_en))
check("TR README'deki testler var", not missing_tr, str(missing_tr))

# run_all.py'nin calistirdigi her test gercekten var mi?
suite = (ROOT / "test" / "run_all.py").read_text(encoding="utf-8")
suite_files = set(re.findall(r'"(test/test_[\w]+\.py)"', suite))
check("run_all'daki testler var", not (suite_files - existing), str(sorted(suite_files - existing)))
check(
    "yeni P3 testleri run_all'da",
    {"test/test_glossary.py", "test/test_subtitle_import.py", "test/test_icon.py",
     "test/test_ci_workflow.py"} <= suite_files,
)

# Calistirilabilir her testin en azindan birinde gecmesi gerekmez (bazi
# testler ic yardimci) ama yeni P3 testleri ikisinde de olmali.
for name in (
    "test/test_glossary.py",
    "test/test_glossary_pipeline.py",
    "test/test_glossary_ui.py",
    "test/test_subtitle_import.py",
    "test/test_packaging.py",
    "test/test_model_guard.py",
    "test/test_icon.py",
    "test/test_audio_select.py",
    "test/test_transcriber_units.py",
):
    check(f"EN belgeli: {name}", name in EN)
    check(f"TR belgeli: {name}", name in TR)

print("\n2) Proje yapisi tablosu")
for module in ("glossary.py", "subtitle_preview.py", "transcript_cache.py"):
    check(f"EN tablo: {module}", f"`{module}`" in EN)
    check(f"TR tablo: {module}", f"`{module}`" in TR)

print("\n3) Surum ve yeni bolum")
import version  # noqa: E402

major_minor = ".".join(version.__version__.split(".")[:2])
check("EN 'What's new' guncel", f"## What's new in {major_minor}" in EN, major_minor)
check("TR 'neler yeni' guncel", f"## {major_minor}'te neler yeni" in TR, major_minor)
check("EN sozluk bicimi", "### Glossary file format" in EN)
check("TR sozluk bicimi", "### Terim sözlüğü dosyası" in TR)
check("EN kapsam disi", "### Not included" in EN)
check("TR kapsam disi", "### Kapsam dışı" in TR)

print("\n4) Sozluk sablonu belgelenen bicimde")
sample = ROOT / "docs" / "glossary-ornek.tsv"
check("sablon var", sample.exists())
if sample.exists():
    import glossary  # noqa: E402

    loaded = glossary.load_glossary(sample)
    check("sablon ayristirildi", len(loaded) > 5, f"{len(loaded)} terim")
    sample_text = sample.read_text(encoding="utf-8")
    check("EN sablonu gosteriyor", "glossary-ornek.tsv" in EN)
    check("TR sablonu gosteriyor", "glossary-ornek.tsv" in TR)
    check("sekme ornegi belgeli", "OpenAI\tOpenAI" in sample_text)

print("\n5) Kirik goreli link yok")
for label, text, base in (("EN", EN, ROOT), ("TR", TR, ROOT / "docs")):
    broken = [
        match.group(1)
        for match in re.finditer(r"\]\((?!https?:)([^)#]+)(#[^)]*)?\)", text)
        if not (base / match.group(1)).resolve().exists()
    ]
    check(f"{label} linkler", not broken, str(broken))

print("\n6) CI belgelenmis")
check("EN CI bolumu", "### C2. CI" in EN)
check("TR CI bolumu", "### C2. CI" in TR)
check("EN workflow yolu", ".github/workflows/ci.yml" in EN)
check("TR workflow yolu", ".github/workflows/ci.yml" in TR)

failed = [label for label, ok, _ in checks if not ok]
print()
if failed:
    print(f"DOKUMANTASYON TESTI BASARISIZ: {failed}")
    sys.exit(1)
print(f"{len(checks)} kontrol gecti")
print("DOKUMANTASYON TESTI: GECTI")
