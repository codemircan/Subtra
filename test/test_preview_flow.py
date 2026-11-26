"""Önizleme kancasının iş akışına bağlanma testi (render öncesi durma)."""

import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import app_paths  # noqa: E402
import fixtures  # noqa: E402
from ffmpeg_utils import SubtitleStyle  # noqa: E402
from worker import JobHooks, JobRunner, JobSettings, ModelCache  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
VIDEO = fixtures.require_video()
models_root = app_paths.resolve_models_dir()
if not (models_root / "faster-whisper-tiny").exists():
    raise SystemExit(fixtures.skip("Whisper 'tiny' modeli indirilmemiş"))

checks = []


def check(label, ok, detail=""):
    checks.append((label, ok))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


class FakeHooks:
    """Önizleme kancasını taklit eden köprü (GUI olmadan)."""

    def __init__(self, proceed=True, only_srt=False, edit=None):
        self.logs = []
        self.stages = []
        self.preview_calls = []
        self._proceed = proceed
        self._only_srt = only_srt
        self._edit = edit

    def hooks(self) -> JobHooks:
        def preview(srt_path: str, summary: str):
            self.preview_calls.append((srt_path, summary))
            if self._edit is not None:
                Path(srt_path).write_text(self._edit, encoding="utf-8", newline="\n")
            return (self._proceed, self._only_srt)

        def stage(text: str, percent: int) -> None:
            self.stages.append(text)

        return JobHooks(
            log=self.logs.append,
            progress=lambda p: None,
            stage=stage,
            language=lambda c, n, p: None,
            preview=preview,
        )


def base(mode="burn", **kwargs) -> JobSettings:
    cfg = dict(
        input_path=str(VIDEO),
        model_size="tiny",
        target_lang="tr",
        output_mode=mode,
        style=SubtitleStyle(font_size=20),
        ffmpeg_path=fixtures._ffmpeg() or "",
        models_dir=str(models_root),
        pipeline_mode="off",
        use_transcript_cache=True,
        overwrite=True,
    )
    cfg.update(kwargs)
    return JobSettings(**cfg)


def cleanup_artifacts() -> None:
    """Testin ürettiği çıktı dosyalarını sil (repoyu kirletmesin)."""
    for path in (PROJECT / "test").glob("konusma ingilizce_*"):
        try:
            path.unlink()
        except OSError:
            pass


def run(settings, hooks: FakeHooks):
    cache = ModelCache(models_root, log_cb=lambda m: None)
    runner = JobRunner(settings, cache, hooks.hooks())
    try:
        return runner.run()
    except Exception as exc:  # noqa: BLE001
        return None, None, f"{type(exc).__name__}: {exc}"
    finally:
        cache.release_all()


print("=" * 68)
print("1) Önizleme çağrılıyor (burn modunda)")
print("=" * 68)
h1 = FakeHooks(proceed=True)
video, srt, summary = run(base("burn"), h1)
check("iş tamamlandı", video is not None and Path(video).exists(), str(video))
check("önizleme çağrıldı", len(h1.preview_calls) == 1, f"{len(h1.preview_calls)} kez")
if h1.preview_calls:
    path, summ = h1.preview_calls[0]
    check("SRT yolu geçerli", Path(path).exists(), Path(path).name)
    check("özet dolu", bool(summ))
check("video üretildi", Path(video).suffix == ".mp4")
check(
    "aşama: altyazı onayı beklendi",
    any("onayı bekleniyor" in s for s in h1.stages),
    str(h1.stages[-3:]),
)
check(
    "aşama: SRT onaylandı",
    any("SRT onaylandı" in s for s in h1.stages),
    str(h1.stages[-2:]),
)

print("\n" + "=" * 68)
print("2) 'Yalnızca .srt' -> video üretilmez")
print("=" * 68)
h2 = FakeHooks(proceed=True, only_srt=True)
video2, srt2, _ = run(base("burn", overwrite=False), h2)
check("video yok", not video2, repr(video2))
check("SRT var", Path(srt2).exists(), Path(srt2).name)
check(
    "log: yalnızca srt seçildi",
    any("yalnızca .srt" in line.lower() for line in h2.logs),
)

print("\n" + "=" * 68)
print("3) Vazgeç -> iş iptal, video üretilmez")
print("=" * 68)
h3 = FakeHooks(proceed=False)
video3, srt3, msg = run(base("burn", overwrite=False), h3)
check("iptal edildi", video3 is None, str(msg)[:60])
check(
    "mesaj: kullanıcı vazgeçti",
    "vazgeç" in str(msg).lower(),
    str(msg)[:70],
)

print("\n" + "=" * 68)
print("4) Kullanıcı SRT'yi düzenledi -> render düzenlenmiş metinle yapılır")
print("=" * 68)
EDITED = (
    "1\n00:00:00,200 --> 00:00:04,000\nDÜZENLENMİŞ SATIR BİR\n\n"
    "2\n00:00:05,000 --> 00:00:09,000\nDÜZENLENMİŞ SATIR İKİ\n"
)
h4 = FakeHooks(proceed=True, edit=EDITED)
video4, srt4, _ = run(base("burn", overwrite=False), h4)
check("render tamam", video4 is not None and Path(video4).exists())
check(
    "log: düzenlenmiş altyazı okundu",
    any("Düzenlenmiş altyazı okundu" in line for line in h4.logs),
    next((l for l in h4.logs if "Düzenlenmiş" in l), ""),
)
disk = Path(srt4).read_text(encoding="utf-8")
check("diskte düzenlenmiş metin", "DÜZENLENMİŞ SATIR BİR" in disk)

print("\n" + "=" * 68)
print("5) skip_preview=True -> önizleme çağrılmaz")
print("=" * 68)
h5 = FakeHooks(proceed=True)
video5, srt5, _ = run(base("srt", skip_preview=True, overwrite=False), h5)
check("önizleme çağrılmadı", len(h5.preview_calls) == 0)
check("SRT üretildi", Path(srt5).exists())

print("\n" + "=" * 68)
print("6) 'srt' modunda önizleme gerekmez (video yok)")
print("=" * 68)
h6 = FakeHooks(proceed=True)
video6, srt6, _ = run(base("srt", overwrite=False), h6)
check("önizleme çağrılmadı", len(h6.preview_calls) == 0)
check("SRT üretildi", Path(srt6).exists())

print("\n" + "=" * 68)
print("7) overwrite=False -> mevcut çıktı ezilmez")
print("=" * 68)
probe = PROJECT / "test" / "_overwrite_probe.mp4"
import shutil

shutil.copy2(VIDEO, probe)
name = probe.stem + "_tr"
existing_srt = probe.with_name(name + ".srt")
existing_srt.write_text("ESKİ İÇERİK KORUNMALI\n", encoding="utf-8")

h7 = FakeHooks(proceed=True)
video7, srt7, _ = run(
    base("srt", input_path=str(probe), overwrite=False), h7
)
kept = existing_srt.read_text(encoding="utf-8")
check("mevcut .srt korundu", "ESKİ İÇERİK KORUNMALI" in kept, kept.strip()[:40])
check("yeni dosya farklı ad", Path(srt7).name != existing_srt.name, Path(srt7).name)

shutil.rmtree(PROJECT / "test" / "_overwrite_probe_tr*", ignore_errors=True)
probe.unlink(missing_ok=True)
existing_srt.unlink(missing_ok=True)

failed = [label for label, ok in checks if not ok]
cleanup_artifacts()
print("\n" + "=" * 68)
print(f"{len(checks) - len(failed)}/{len(checks)} kontrol geçti")
print("ÖNİZLEME AKIŞ TESTİ: " + ("GEÇTİ" if not failed else f"BAŞARISIZ -> {failed}"))
sys.exit(0 if not failed else 1)
