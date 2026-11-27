"""Kuyrukta dosya basina terim sozlugu testi.

Gercek is calistirmaz: kuyruk satirlarinin JobSettings'e dogru sozluk
yolunu tasidigini ve global sozlukten bagimsiz oldugunu dogrular.
"""

import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication  # noqa: E402
import PySide6.QtWidgets as QtWidgets  # noqa: E402

QtWidgets.QMessageBox.exec = lambda self: 0
QtWidgets.QMessageBox.information = staticmethod(lambda *a, **k: None)
QtWidgets.QMessageBox.warning = staticmethod(lambda *a, **k: None)
QtWidgets.QMessageBox.critical = staticmethod(lambda *a, **k: None)
QtWidgets.QFileDialog.getOpenFileName = staticmethod(
    lambda *a, **k: (str(Path(__file__).resolve().parent.parent / "docs" / "glossary-ornek.tsv"), "")
)

app = QApplication(sys.argv[:1])

from gui import QUEUE_COLUMNS, MainWindow  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
WORK = PROJECT / "test" / "_queue_glossary"
WORK.mkdir(parents=True, exist_ok=True)

checks: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


def make_glossary(name: str, source: str, target: str) -> Path:
    path = WORK / name
    path.write_text(f"{source}\t{target}\n", encoding="utf-8")
    return path


print("=" * 66)
print("KUYRUKTA DOSYA BASINA SOZLUK")
print("=" * 66)

# Iki sahte video (icerik onemli degil; is calistirilmiyor)
video_a = WORK / "a.mp4"
video_b = WORK / "b.mp4"
for video in (video_a, video_b):
    video.write_bytes(b"\x00" * 1024)

gloss_a = make_glossary("a.tsv", "Alpha", "ALFA")
gloss_b = make_glossary("b.tsv", "Beta", "BETA")
global_gloss = make_glossary("global.tsv", "Gamma", "GAMA")

window = MainWindow()

print("\n1) Tablo sutunlari")
check("5 sutun", len(QUEUE_COLUMNS) == 5, str(QUEUE_COLUMNS))
check("sozluk sutunu var",
      any("zl" in name.lower() for name in QUEUE_COLUMNS), str(QUEUE_COLUMNS))
check("tablo 5 kolon", window.queue_table.columnCount() == 5,
      str(window.queue_table.columnCount()))

print("\n2) Global sozluk varsayilan olarak satirlara yazilir")
window._set_glossary(str(global_gloss), announce=False)
window._add_to_queue([str(video_a), str(video_b)])
check("2 satir", window.queue_table.rowCount() == 2, str(window.queue_table.rowCount()))
settings = window._queue_jobs()
check("satir 0 global sozluk", Path(settings[0].glossary_path) == global_gloss,
      settings[0].glossary_path)
check("satir 1 global sozluk", Path(settings[1].glossary_path) == global_gloss,
      settings[1].glossary_path)
check("satirlar 'ozel' sayilmaz",
      not any(window._queue_has_own_glossary(row) for row in range(2)))

print("\n3) Satir secilip kendi sozlugu atanir")
window.queue_table.selectRow(0)
window._apply_queue_glossary(str(gloss_a))
jobs = window._queue_jobs()
check("satir 0 kendi sozlugu", Path(jobs[0].glossary_path) == gloss_a, jobs[0].glossary_path)
check("satir 1 global kaldi", Path(jobs[1].glossary_path) == global_gloss, jobs[1].glossary_path)
check("hucrede dosya adi", "a.tsv" in window.queue_table.item(0, 2).text(),
      window.queue_table.item(0, 2).text())

print("\n4) Ikinci satira farkli sozluk")
window.queue_table.selectRow(1)
window._apply_queue_glossary(str(gloss_b))
jobs = window._queue_jobs()
paths = [Path(job.glossary_path).name for job in jobs]
check("iki farkli sozluk", paths == ["a.tsv", "b.tsv"], str(paths))

print("\n5) Global sozluk degisince yalnizca atanmamis satir etkilenir")
window._set_glossary("", announce=False)  # global kapat
jobs = window._queue_jobs()
check("satir 0 hala a.tsv", Path(jobs[0].glossary_path) == gloss_a, jobs[0].glossary_path)
check("satir 1 hala b.tsv", Path(jobs[1].glossary_path) == gloss_b, jobs[1].glossary_path)

print("\n5b) Atanmamis satir global degisimini izler")
window._add_to_queue([str(WORK / "c.mp4")])
(WORK / "c.mp4").write_bytes(b"\x00" * 1024)
window._add_to_queue([str(WORK / "c.mp4")])
last = window.queue_table.rowCount() - 1
check("yeni satir globalsiz", window._queue_jobs()[last].glossary_path == "",
      repr(window._queue_jobs()[last].glossary_path))
window._set_glossary(str(global_gloss), announce=False)
check("global ataninca yeni satir izler",
      Path(window._queue_jobs()[last].glossary_path) == global_gloss,
      window._queue_jobs()[last].glossary_path)
check("ozel satir hala a.tsv",
      Path(window._queue_jobs()[0].glossary_path) == gloss_a)
window.queue_table.removeRow(last)

print("\n6) Kaldirma: satir genel sozluge doner")
window.queue_table.selectRow(0)
window._clear_queue_glossary()
jobs = window._queue_jobs()
check("satir 0 artik ozel degil", not window._queue_has_own_glossary(0))
check("satir 0 genel sozlugu kullaniyor", Path(jobs[0].glossary_path) == global_gloss,
      jobs[0].glossary_path)
check("satir 1 bozulmadi", Path(jobs[1].glossary_path) == gloss_b, jobs[1].glossary_path)
check("hucre bos isaretli", window.queue_table.item(0, 2).text() in ("—", "-", ""),
      repr(window.queue_table.item(0, 2).text()))

print("\n7) Bozuk sozluk satira yazilmaz")
window.queue_table.selectRow(1)
bad = WORK / "bozuk.tsv"
bad.write_text("tek_sutun\n", encoding="utf-8")
window._apply_queue_glossary(str(bad))
jobs = window._queue_jobs()
check("bozuk sozluk reddedildi", Path(jobs[1].glossary_path) == gloss_b, jobs[1].glossary_path)

print("\n8) Olmayan dosya satira yazilmaz")
missing = WORK / "yok.tsv"
window._apply_queue_glossary(str(missing))
jobs = window._queue_jobs()
check("olmayan dosya reddedildi", Path(jobs[1].glossary_path) == gloss_b, jobs[1].glossary_path)

print("\n9) Tumune uygula")
window._apply_queue_glossary_all(str(gloss_a))
jobs = window._queue_jobs()
check("hepsi a.tsv", all(Path(job.glossary_path) == gloss_a for job in jobs),
      str([Path(j.glossary_path).name for j in jobs]))

print("\n10) Ozet satirinda sozluk cesitliligi gorunur")
summary = window.queue_summary.text()
check("ozet sozlukten soz ediyor", "sözlük" in summary.lower(), summary[:110])

print("\n11) Uctan uca: ayni video, iki farkli sozluk")
import shutil  # noqa: E402

import fixtures  # noqa: E402
import app_paths  # noqa: E402
from transcriber import cached_whisper_models  # noqa: E402
from worker import JobRunner, ModelCache  # noqa: E402
import worker as worker_mod  # noqa: E402
from subtitles import read_srt  # noqa: E402
from errors import SubtraError  # noqa: E402

models_dir = app_paths.resolve_models_dir()
if "tiny" not in cached_whisper_models(models_dir):
    print("  SKIP: whisper tiny onbellekte yok (model indirilmez).")
else:
    try:
        base_video = fixtures.require_video()
    except SystemExit:
        base_video = None
    if base_video is None:
        print("  SKIP: fixture video yok.")
    else:
        # Ayni ses, iki kopya; her kopyaya ayri sozluk
        copy_a = WORK / "kopya_a.mp4"
        copy_b = WORK / "kopya_b.mp4"
        for target in (copy_a, copy_b):
            shutil.copy2(base_video, target)

        glossary_a = make_glossary("ozel_a.tsv", "subtitle", "ALTYAZI_A")
        glossary_b = make_glossary("ozel_b.tsv", "subtitle", "ALTYAZI_B")

        # Kuyrugu GUI uzerinden kur: satirlara ayri sozluk ata
        window.queue_table.setRowCount(0)
        window._set_glossary("", announce=False)
        window._add_to_queue([str(copy_a), str(copy_b)])
        window._apply_queue_glossary(str(glossary_a), [0])
        window._apply_queue_glossary(str(glossary_b), [1])
        jobs = window._queue_jobs()
        check("iki is, iki farkli sozluk",
              [Path(job.glossary_path).name for job in jobs] == ["ozel_a.tsv", "ozel_b.tsv"],
              str([Path(job.glossary_path).name for job in jobs]))

        models = ModelCache(models_dir)
        outputs = []
        ram_skip = False
        for job in jobs:
            job.skip_preview = True
            job.use_transcript_cache = True   # 2. is transkripti onbellekten alir
            job.model_size = "tiny"
            job.target_lang = "tr"            # kayitli ayardan bagimsiz
            try:
                _video, srt_out, _summary = JobRunner(
                    job, models, worker_mod.JobHooks(log=lambda m: None)
                ).run()
            except SubtraError as exc:
                if "Bellek yetersiz" in str(exc):
                    ram_skip = True
                    break
                raise
            text = " ".join(entry["text"] for entry in read_srt(srt_out))
            outputs.append(text)
        models.release_all()

        if ram_skip:
            print("  SKIP: bos RAM yetersiz (bellek korumasi devreye girdi).")
        else:
            check("1. video A terimini kullandi", "ALTYAZI_A" in outputs[0], outputs[0][:80])
            check("2. video B terimini kullandi", "ALTYAZI_B" in outputs[1], outputs[1][:80])
            check("sozlukler karismadi",
                  "ALTYAZI_B" not in outputs[0] and "ALTYAZI_A" not in outputs[1],
                  "capraz kullanim yok")

        for target in (copy_a, copy_b):
            target.unlink(missing_ok=True)
        for extra in WORK.glob("kopya_*_tr.srt"):
            extra.unlink(missing_ok=True)

window.close()

failed = [label for label, ok, _ in checks if not ok]
print()
if failed:
    print(f"KUYRUK SOZLUK TESTI BASARISIZ: {failed}")
    sys.exit(1)
print(f"{len(checks)} kontrol gecti")
print("KUYRUK SOZLUK TESTI: GECTI")
