"""Ses kanalı seçimi testi — FFmpeg gerekir (yoksa SKIP).

Regresyon: `extract_audio` her zaman `-map 0:a:0` kullanıyordu; videoda
Türkçe + İngilizce ses varsa kullanıcı ikinciyi seçemiyordu.

Kanıt yöntemi: iki kanallı videoda kanal 0 = 440 Hz, kanal 1 = 880 Hz.
Çıkarılan WAV'ın baskın frekansı ölçülür; yanlış kanal seçilirse test düşer.
"""

import io
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import fixtures  # noqa: E402
import ffmpeg_bootstrap  # noqa: E402
import ffmpeg_utils as fu  # noqa: E402
from errors import FFmpegError  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


print("=" * 66)
print("SES KANALI SECIMI")
print("=" * 66)

loc = ffmpeg_bootstrap.find_existing()
if loc is None:
    print(
        fixtures.skip("FFmpeg bulunamadı (otomatik indirme testlerde kapalı)")
    )
    sys.exit(77)
FFMPEG, FFPROBE = loc.ffmpeg, loc.ffprobe

WORK = Path(__file__).resolve().parent / "_audio_select"
WORK.mkdir(parents=True, exist_ok=True)


def run(cmd: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=0x08000000, text=True, encoding="utf-8", errors="replace",
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def dominant_hz(wav: Path) -> float:
    """16 kHz mono WAV'ın baskın frekansı."""
    import wave

    with wave.open(str(wav), "rb") as handle:
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return 0.0
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(samples.size)))
    freqs = np.fft.rfftfreq(samples.size, d=1.0 / rate)
    return float(freqs[int(np.argmax(spectrum))])


print("\n1) Iki sesli video uretiliyor (440 Hz + 880 Hz)")
video = WORK / "iki_ses.mp4"
code, out = run([
    FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
    "-f", "lavfi", "-i", "color=c=0x203040:s=320x180:d=4",
    "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
    "-f", "lavfi", "-i", "sine=frequency=880:duration=4",
    "-map", "0:v", "-map", "1:a", "-map", "2:a",
    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "96k",
    "-metadata:s:a:0", "language=tur",
    "-metadata:s:a:1", "language=eng",
    str(video),
])
if code != 0:
    print("  uretilemedi:", out[-300:])
    sys.exit(1)
check("video olustu", video.exists())

print("\n2) audio_streams() listeleme")
tracks = fu.audio_streams(FFPROBE, video)
check("2 ses kanali", len(tracks) == 2, str(len(tracks)))
if len(tracks) == 2:
    check("audio_index sirali", [t["audio_index"] for t in tracks] == [0, 1],
          str([t["audio_index"] for t in tracks]))
    check("global index dolu", all(isinstance(t["index"], int) for t in tracks),
          str([t["index"] for t in tracks]))
    check("dil 0 = tur", tracks[0]["language"] == "tur", tracks[0]["language"])
    check("dil 1 = eng", tracks[1]["language"] == "eng", tracks[1]["language"])
    check("codec aac", tracks[0]["codec"] == "aac", tracks[0]["codec"])
    check("kanal sayisi 1", tracks[0]["channels"] == 1, str(tracks[0]["channels"]))

print("\n3) Kanal 0 cikariliyor (varsayilan)")
wav0 = fu.extract_audio(FFMPEG, video, WORK / "k0.wav", 4.0)
hz0 = dominant_hz(wav0)
check("kanal 0 = 440 Hz", abs(hz0 - 440) < 25, f"{hz0:.0f} Hz")

print("\n4) Kanal 1 cikariliyor (audio_index=1)")
wav1 = fu.extract_audio(FFMPEG, video, WORK / "k1.wav", 4.0, audio_index=1)
hz1 = dominant_hz(wav1)
check("kanal 1 = 880 Hz", abs(hz1 - 880) < 35, f"{hz1:.0f} Hz")
check("kanallar gercekten farkli", abs(hz1 - hz0) > 300, f"{hz0:.0f} / {hz1:.0f}")

print("\n5) Gecersiz kanal indeksi net hata verir")
try:
    fu.extract_audio(FFMPEG, video, WORK / "yok.wav", 4.0, audio_index=7)
    check("hata beklenirdi", False)
except FFmpegError as exc:
    message = str(exc).lower()
    check("FFmpegError", True, str(exc).splitlines()[0][:70])
    check("mesaj anlasilir", "ses kanal" in message, str(exc)[:90])

print("\n6) Tek sesli videoda liste tek eleman")
tek = fixtures.require_video()
tek_tracks = fu.audio_streams(FFPROBE, tek)
check("tek kanal", len(tek_tracks) == 1, str(len(tek_tracks)))
if tek_tracks:
    check("index 0", tek_tracks[0]["audio_index"] == 0)

print("\n7) Arayuz: secim JobSettings'e tasiniyor")
import os  # noqa: E402

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication  # noqa: E402
import PySide6.QtWidgets as QtWidgets  # noqa: E402

QtWidgets.QMessageBox.information = staticmethod(lambda *a, **k: None)
QtWidgets.QMessageBox.warning = staticmethod(lambda *a, **k: None)

app = QApplication.instance() or QApplication(sys.argv[:1])
from gui import MainWindow  # noqa: E402

window = MainWindow()
window._ffmpeg_path = FFMPEG
window._set_single_input(str(video))
window._refresh_audio_tracks()

combo = window.audio_track_combo
check("combo 2 giris", combo.count() == 2, str(combo.count()))
check("etiketler dil iceriyor",
      all(("tur" in combo.itemText(i) or "eng" in combo.itemText(i)) for i in range(combo.count())),
      " | ".join(combo.itemText(i) for i in range(combo.count())))
check("ilk secim 0", combo.currentData() == 0, str(combo.currentData()))

combo.setCurrentIndex(1)
check("secim 1'e gecti", combo.currentData() == 1, str(combo.currentData()))
settings = window._base_settings(input_path=str(video))
check("JobSettings.audio_stream_index", settings.audio_stream_index == 1,
      str(settings.audio_stream_index))

# Tek sesli videoda combo tek girisli ve 0
window._set_single_input(str(tek))
window._refresh_audio_tracks()
check("tek ses -> 1 giris", window.audio_track_combo.count() == 1,
      str(window.audio_track_combo.count()))
check("tek ses -> 0", window.audio_track_combo.currentData() == 0,
      str(window.audio_track_combo.currentData()))
window.close()

print("\n8) Uctan uca: konusma 2. kanalda (Whisper)")
from transcriber import cached_whisper_models  # noqa: E402
import app_paths  # noqa: E402
from worker import JobRunner, JobSettings, ModelCache  # noqa: E402
from errors import NoSpeechError, SubtraError  # noqa: E402

models_dir = app_paths.resolve_models_dir()


def _skip_on_memory(callable_, label: str):
    """Bellek korumasi devreye girerse testi kirmizi yapma: SKIP et."""
    try:
        return callable_()
    except SubtraError as exc:
        if "Bellek yetersiz" in str(exc):
            print(f"  SKIP: bos RAM yetersiz — {label} (bellek korumasi)")
            return None
        raise


if "tiny" not in cached_whisper_models(models_dir):
    print("  SKIP: whisper tiny onbellekte yok (model indirilmez).")
else:
    # fixture videosundan konusmayi al, ton + konusma olarak yeniden paketle
    speech = WORK / "konusma.wav"
    code, out = run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                     "-i", str(tek), "-vn", "-ac", "1", "-ar", "16000",
                     "-c:a", "pcm_s16le", str(speech)])
    check("konusma cikarildi", code == 0 and speech.exists(), out[-150:])

    karisik = WORK / "ton_ve_konusma.mkv"
    code, out = run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                     "-f", "lavfi", "-i", "color=c=0x101820:s=320x180:d=15",
                     "-f", "lavfi", "-i", "sine=frequency=200:duration=15",
                     "-i", str(speech),
                     "-map", "0:v", "-map", "1:a", "-map", "2:a",
                     "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                     "-c:a", "aac", "-b:a", "96k",
                     "-metadata:s:a:0", "language=und",
                     "-metadata:s:a:1", "language=eng",
                     "-shortest", str(karisik)])
    check("karisik video olustu", code == 0 and karisik.exists(), out[-150:])

    mux_streams = fu.audio_streams(FFPROBE, karisik) if code == 0 else []
    check("2 kanal (ton + konusma)", len(mux_streams) == 2, str(len(mux_streams)))

    logs: list[str] = []
    import worker as worker_mod

    def make_runner(index: int) -> JobRunner:
        settings = JobSettings(
            input_path=str(karisik),
            model_size="tiny",
            target_lang="tr",
            output_mode="srt",
            models_dir=str(models_dir),
            skip_preview=True,
            use_transcript_cache=False,
            word_timestamps=True,
            audio_stream_index=index,
        )
        return JobRunner(settings, ModelCache(models_dir), worker_mod.JobHooks(log=logs.append))

    # Kanal 0 = saf ton: konusma yok -> net hata
    try:
        make_runner(0).run()
        check("kanal 0 (ton) konusma bulamadi", False, "beklenen istisna gelmedi")
    except NoSpeechError:
        check("kanal 0 (ton) konusma bulamadi", True)
    except SubtraError as exc:
        if "Bellek yetersiz" not in str(exc):
            raise
        print("  SKIP: bos RAM yetersiz (bellek korumasi) — uctan uca bolum atlandi.")
        _memory_skip = True
    else:
        _memory_skip = False

    def _run_whisper_sections() -> None:
        # Kanal 1 = konusma: metin cikmali
        video_out, srt_out, summary = make_runner(1).run()
        check("kanal 1 video uretmedi (srt modu)", video_out == "", video_out)
        text = Path(srt_out).read_text(encoding="utf-8")
        check("kanal 1 metin uretti", len(text.strip()) > 40, text[:80].replace("\n", " | "))
        check("log kanal secimini yazdi", any("Ses kanalı: #2" in line for line in logs),
              next((l for l in logs if "Ses kanal" in l), "(yok)"))

        print("\n9) Regresyon: kelime damgasi KAPALI (word_timestamps=False)")
        settings = JobSettings(
            input_path=str(karisik),
            model_size="tiny",
            target_lang="tr",
            output_mode="srt",
            models_dir=str(models_dir),
            skip_preview=True,
            use_transcript_cache=False,
            word_timestamps=False,
            audio_stream_index=1,
        )
        try:
            _video, srt_kapali, _summary = JobRunner(
                settings, ModelCache(models_dir), worker_mod.JobHooks(log=logs.append)
            ).run()
            text_kapali = Path(srt_kapali).read_text(encoding="utf-8")
            check("kelime damgasi kapali da metin uretir", len(text_kapali.strip()) > 40,
                  text_kapali[:70].replace("\n", " | "))
            check("SRT bicimi gecerli", "-->" in text_kapali)
        except NoSpeechError as exc:
            check("kelime damgasi kapali da metin uretir", False,
                  f"NoSpeechError: {str(exc).splitlines()[0]}")

    if not _memory_skip:
        _skip_on_memory(_run_whisper_sections, "Whisper bolumleri")

failed = [label for label, ok, _ in checks if not ok]
print()
if failed:
    print(f"SES KANALI TESTI BASARISIZ: {failed}")
    sys.exit(1)
print(f"{len(checks)} kontrol gecti")
print("SES KANALI TESTI: GECTI")
