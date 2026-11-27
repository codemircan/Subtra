"""Paketleme ve CI tutarliligi — pyproject, requirements, workflow."""

import io
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: testi atla, uygulama calisir
    print("\n  SKIP: tomllib yok (Python 3.11+ gerekli).")
    print("  (test atlandi, hata degil)")
    sys.exit(77)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
checks: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


print("=" * 66)
print("PAKETLEME / CI")
print("=" * 66)

# --- 1) pyproject ---------------------------------------------------------
print("\n1) pyproject.toml")
pyproject_path = ROOT / "pyproject.toml"
check("dosya var", pyproject_path.exists())
try:
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data["project"]
    check("ad subtra", project["name"] == "subtra", project["name"])
    check("dinamik surum", project.get("dynamic") == ["version"], str(project.get("dynamic")))
    check(
        "surum version.py'den",
        data["tool"]["setuptools"]["dynamic"]["version"]["attr"] == "version.__version__",
    )
    check("python >= 3.10", project["requires-python"] == ">=3.10", project["requires-python"])
    check("MIT lisans", "MIT" in str(project.get("license")), str(project.get("license")))

    modules = data["tool"]["setuptools"]["py-modules"]
    for name in ("glossary", "subtitle_preview", "transcript_cache", "worker", "gui"):
        check(f"modul listesinde {name}", name in modules)
    check("tum kok modulleri listeli", all(
        path.stem in modules for path in ROOT.glob("*.py")
    ), str(sorted(set(p.stem for p in ROOT.glob("*.py")) - set(modules))))

    # --- 2) requirements tutarliligi -------------------------------------
    print("\n2) requirements.txt <-> pyproject")
    requirements = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    dependencies = [dep.strip() for dep in project["dependencies"]]
    check("ayni bagimliliklar", sorted(requirements) == sorted(dependencies),
          f"eksik/fazla: {sorted(set(requirements) ^ set(dependencies))}")
    check("PySide6 var", any("PySide6" in dep for dep in dependencies))
except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
    check("pyproject ayristirildi", False, f"{type(exc).__name__}: {exc}")

# --- 3) CI workflow -------------------------------------------------------
print("\n3) GitHub Actions")
workflow = ROOT / ".github" / "workflows" / "ci.yml"
check("workflow var", workflow.exists())
if workflow.exists():
    text = workflow.read_text(encoding="utf-8")
    check("windows runner", "windows-latest" in text)
    check("run_all calisiyor", "test/run_all.py" in text)
    check("model indirme kapali", "SUBTRA_NO_DOWNLOAD" in text)
    check("offscreen Qt", "QT_QPA_PLATFORM" in text)
    check("ruff", "ruff check" in text)
    check("etiket icin fetch-depth", "fetch-depth: 0" in text)
    check("requirements kuruluyor", "requirements.txt" in text)

# --- 4) Yardimci dosyalar -------------------------------------------------
print("\n4) Yardimci dosyalar")
for name in ("LICENSE", "README.md", "docs/README.tr.md", "docs/glossary-ornek.tsv",
             "build.ps1", "calistir.bat", "Subtra.spec"):
    check(name, (ROOT / name).exists())

failed = [label for label, ok, _ in checks if not ok]
print()
if failed:
    print(f"PAKETLEME TESTI BASARISIZ: {failed}")
    sys.exit(1)
print(f"{len(checks)} kontrol gecti")
print("PAKETLEME TESTI: GECTI")
