"""CI workflow dogrulama + yerel simulasyon.

GitHub Actions calismadiginda (hesap/billing kilidi) workflow'un gecerli
oldugunu ve adimlarinin yerelde gectigini kanitlar.
"""

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
checks: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


print("=" * 66)
print("CI WORKFLOW DOGRULAMA")
print("=" * 66)

# Bu test kendi icinde `test/run_all.py` calistirir. Ic ice cagrida (veya
# GitHub Actions'in kendisinde) tekrar calismamali: aksi halde sonsuz
# ozyineleme olur. Ic kosuda SKIP (exit 77) doner.
if os.environ.get("SUBTRA_CI_INNER") or os.environ.get("GITHUB_ACTIONS"):
    print("\n  SKIP: ic ice CI simulasyonu (SUBTRA_CI_INNER / GITHUB_ACTIONS).")
    print("  (test atlandi, hata degil)")
    sys.exit(77)

print("\n1) YAML gecerliligi")
raw = WORKFLOW.read_text(encoding="utf-8")
parsed = yaml.safe_load(raw)
check("YAML ayristirildi", isinstance(parsed, dict))

print("\n2) Workflow semasi")
# YAML'de anahtar 'on' -> True olarak okunabilir (YAML 1.1)
triggers = parsed.get("on") or parsed.get(True) or {}
check("push tetikleyicisi", "push" in triggers, str(list(triggers)))
check("pull_request tetikleyicisi", "pull_request" in triggers)
jobs = parsed.get("jobs") or {}
check("tek job: test", list(jobs) == ["test"], str(list(jobs)))
job = jobs["test"]
check("windows-latest", job.get("runs-on") == "windows-latest", str(job.get("runs-on")))
check("timeout var", isinstance(job.get("timeout-minutes"), int))

env = job.get("env") or {}
check("SUBTRA_NO_DOWNLOAD=1", str(env.get("SUBTRA_NO_DOWNLOAD")) == "1")
check("QT_QPA_PLATFORM=offscreen", env.get("QT_QPA_PLATFORM") == "offscreen")
check("UTF-8 cikti", str(env.get("PYTHONIOENCODING")).lower() == "utf-8")

steps = job.get("steps") or []
uses = [step.get("uses", "") for step in steps]
check("checkout@v4", any("actions/checkout@v4" in u for u in uses), str(uses[:2]))
check("setup-python@v5", any("actions/setup-python@v5" in u for u in uses))
checkout = next(s for s in steps if "checkout" in s.get("uses", ""))
check("fetch-depth 0 (etiket)", checkout.get("with", {}).get("fetch-depth") == 0)

setup = next(s for s in steps if "setup-python" in s.get("uses", ""))
check("Python 3.13", str(setup.get("with", {}).get("python-version")) == "3.13")
check("pip cache", setup.get("with", {}).get("cache") == "pip")

run_scripts = "\n".join(step.get("run", "") for step in steps)
for needle, label in (
    ("requirements.txt", "requirements kuruluyor"),
    ("ruff check", "ruff"),
    ("compileall", "compileall"),
    ("test/run_all.py", "test paketi"),
):
    check(label, needle in run_scripts, needle)

print("\n3) Workflow'un adimlarini yerelde kos")
env_local = dict(os.environ)
env_local.update(
    PYTHONIOENCODING="utf-8",
    QT_QPA_PLATFORM="offscreen",
    SUBTRA_NO_DOWNLOAD="1",
    SUBTRA_CI_INNER="1",  # ic run_all'da bu test tekrar kosmasin
)

proc = subprocess.run(
    [sys.executable, "-m", "ruff", "check", "."],
    cwd=str(ROOT), env=env_local, capture_output=True, text=True,
    encoding="utf-8", errors="replace",
)
check("ruff check gecti", proc.returncode == 0, (proc.stdout or "").strip()[-90:])

proc = subprocess.run(
    [sys.executable, "-m", "compileall", "-q", "."],
    cwd=str(ROOT), env=env_local, capture_output=True, text=True,
    encoding="utf-8", errors="replace",
)
check("compileall gecti", proc.returncode == 0, (proc.stderr or "").strip()[-90:])

# Temiz klon simulasyonu: model/ffmpeg olmadan run_all SKIP verir, exit 0.
clone = Path(tempfile.mkdtemp(prefix="subtra_ci_clone_"))
try:
    result = subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", str(ROOT), str(clone)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    check("yerel klon", result.returncode == 0, (result.stderr or "").strip()[:80])
    for ignored in ("models", "ffmpeg"):
        check(f"klonda {ignored}/ yok", not (clone / ignored).exists())
    check(
        "klonda test fixture yok",
        not (clone / "test" / "konusma ingilizce.mp4").exists(),
    )

    proc = subprocess.run(
        [sys.executable, "test/run_all.py"],
        cwd=str(clone), env=env_local, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=1800,
    )
    tail = (proc.stdout or "").strip().splitlines()[-3:]
    print("    " + "\n    ".join(tail))
    check("temiz klonda run_all kod=0", proc.returncode == 0, f"kod={proc.returncode}")
    check(
        "temiz klonda BASARISIZ yok",
        "0 başarısız" in (proc.stdout or ""),
        next((l for l in tail if "başarısız" in l), ""),
    )
finally:
    shutil.rmtree(clone, ignore_errors=True)

failed = [label for label, ok, _ in checks if not ok]
print()
if failed:
    print(f"CI DOGRULAMA BASARISIZ: {failed}")
    sys.exit(1)
print(f"{len(checks)} kontrol gecti")
print("CI DOGRULAMA: GECTI")
