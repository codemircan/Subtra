"""Gomulu altyazi ice aktarma testi (FFmpeg gerekir; yoksa SKIP)."""

import io
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import fixtures  # noqa: E402
import ffmpeg_bootstrap  # noqa: E402
import ffmpeg_utils  # noqa: E402
from errors import FFmpegError  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, ok, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


print("=" * 66)
print("GOMULU ALTYAZI ICE AKTARMA")
print("=" * 66)

location = ffmpeg_bootstrap.find_existing()
if location is None:
    print("\n  SKIP: FFmpeg yok.")
    print("  (test atlandi, hata degil)")
    sys.exit(77)

FFMPEG, FFPROBE = location.ffmpeg, location.ffprobe
WORK = Path(__file__).resolve().parent / "_sub_import"
shutil.rmtree(WORK, ignore_errors=True)
WORK.mkdir(parents=True, exist_ok=True)

SRT_TEXT = (
    "1\n00:00:00,200 --> 00:00:01,500\nTürkçe altyazı satırı.\n\n"
    "2\n00:00:01,700 --> 00:00:03,000\nİkinci satır: ğüşiöç.\n"
)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=0x08000000, timeout=180,
    )


def build_video(target: Path, codec: str, language: str, with_subs: bool = True) -> bool:
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=0x334155:s=320x180:d=3.5:r=15",
    ]
    if with_subs:
        cmd += ["-i", str(WORK / "kaynak.srt")]
        cmd += ["-map", "0:v", "-map", "1:s"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if with_subs:
        cmd += ["-c:s", codec, "-metadata:s:s:0", f"language={language}"]
    cmd += ["-t", "3.5", str(target)]
    result = run(cmd)
    if result.returncode != 0:
        print("   ffmpeg:", (result.stderr or "").strip()[-300:])
        return False
    return target.exists() and target.stat().st_size > 1000


(WORK / "kaynak.srt").write_text(SRT_TEXT, encoding="utf-8")

print("\n1) MKV (subrip) — listeleme")
mkv = WORK / "gomulu.mkv"
if not build_video(mkv, "srt", "tur"):
    sys.exit(fixtures.skip("test videosu uretilemedi"))

streams = ffmpeg_utils.subtitle_streams(FFPROBE, mkv)
check("tek akis bulundu", len(streams) == 1, str(streams))
if streams:
    stream = streams[0]
    check("codec subrip", stream["codec"] == "subrip", stream["codec"])
    check("dil tur", stream["language"] == "tur", stream["language"])
    check("metin tabanli", stream["text_based"] is True, str(stream))

print("\n2) MKV — cikarma")
extracted = ffmpeg_utils.extract_subtitle_stream(
    FFMPEG, FFPROBE, mkv, streams[0]["index"], WORK / "cikti_tr.srt"
)
text = extracted.read_text(encoding="utf-8")
check("dosya olustu", extracted.exists())
check("metin korundu", "Türkçe altyazı satırı." in text, text[:80].replace("\n", "|"))
check("Turkce karakterler", "ğüşiöç" in text, text[:120].replace("\n", "|"))
check("SRT bicimi", "-->" in text)

print("\n3) MP4 (mov_text)")
mp4 = WORK / "gomulu.mp4"
if build_video(mp4, "mov_text", "eng"):
    streams_mp4 = ffmpeg_utils.subtitle_streams(FFPROBE, mp4)
    check("mp4 akisi", len(streams_mp4) == 1, str(streams_mp4))
    if streams_mp4:
        check("mov_text metin tabanli", streams_mp4[0]["text_based"] is True, streams_mp4[0]["codec"])
        out = ffmpeg_utils.extract_subtitle_stream(
            FFMPEG, FFPROBE, mp4, streams_mp4[0]["index"], WORK / "cikti_en.srt"
        )
        check("mp4 cikarma", "Türkçe altyazı" in out.read_text(encoding="utf-8"))
else:
    check("mp4 olusturuldu", False, "atlandi")

print("\n4) Altyazisiz video")
plain = WORK / "duz.mp4"
if build_video(plain, "srt", "und", with_subs=False):
    check("bos liste", ffmpeg_utils.subtitle_streams(FFPROBE, plain) == [])
else:
    check("duz video olusturuldu", False)

print("\n5) Hatali istekler")
try:
    ffmpeg_utils.extract_subtitle_stream(FFMPEG, FFPROBE, mkv, 999, WORK / "x.srt")
    check("olmayan indeks hata verdi", False)
except FFmpegError as exc:
    check("olmayan indeks hata verdi", "bulunamadı" in str(exc).lower(), str(exc)[:70])

original = ffmpeg_utils.subtitle_streams
ffmpeg_utils.subtitle_streams = lambda *a, **k: [
    {"index": 2, "codec": "hdmv_pgs_subtitle", "language": "tur", "title": "",
     "default": False, "forced": False, "text_based": False, "image_based": True}
]
try:
    ffmpeg_utils.extract_subtitle_stream(FFMPEG, FFPROBE, mkv, 2, WORK / "pgs.srt")
    check("gorsel altyazi reddedildi", False)
except FFmpegError as exc:
    check("gorsel altyazi reddedildi", "görüntü tabanlı" in str(exc).lower(), str(exc)[:60])
finally:
    ffmpeg_utils.subtitle_streams = original

print("\n6) Arayuz etiketi")
from gui import MainWindow  # noqa: E402

label = MainWindow._stream_label(
    {"index": 3, "codec": "subrip", "language": "deu", "title": "Almanca",
     "default": True, "forced": False, "text_based": True}
)
check("etiket indeks/dil", "#3" in label and "deu" in label, label)
check("etiket baslik", "Almanca" in label, label)
check("etiket varsayilan", "varsayılan" in label, label)

from languages import from_subtitle_tag  # noqa: E402

check("tur -> tr", from_subtitle_tag("tur") == "tr", from_subtitle_tag("tur"))
check("eng -> en", from_subtitle_tag("eng") == "en", from_subtitle_tag("eng"))
check("deu -> de", from_subtitle_tag("deu") == "de", from_subtitle_tag("deu"))
check("ger -> de", from_subtitle_tag("GER") == "de", from_subtitle_tag("GER"))
check("taninmayan -> bos", from_subtitle_tag("xyz") == "", from_subtitle_tag("xyz"))

print("\n7) Arayuz akisi (buton -> secim -> SRT sekmesi)")
import os  # noqa: E402

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication  # noqa: E402
import PySide6.QtWidgets as QtWidgets  # noqa: E402

QtWidgets.QMessageBox.information = staticmethod(lambda *a, **k: None)
QtWidgets.QMessageBox.warning = staticmethod(lambda *a, **k: None)
QtWidgets.QMessageBox.critical = staticmethod(lambda *a, **k: None)
QtWidgets.QInputDialog.getItem = staticmethod(lambda *a, **k: (a[3][0], True))

app = QApplication.instance() or QApplication(sys.argv[:1])
window = MainWindow()
window._ffmpeg_path = FFMPEG
window._set_single_input(str(mkv))
window._import_embedded_subtitle()

expected = WORK / "gomulu_embedded_tur.srt"
check("SRT cikarildi", expected.exists(), str(expected))
check("SRT sekmesi aktif", window.tabs.currentIndex() == 2, str(window.tabs.currentIndex()))
check("SRT girdisi ayarlandi", getattr(window, "_srt_input", "") == str(expected),
      getattr(window, "_srt_input", ""))
check("kaynak dil tr", window.srt_lang_combo.currentData() == "tr",
      str(window.srt_lang_combo.currentData()))
if expected.exists():
    check("metin aktarildi", "Türkçe altyazı" in expected.read_text(encoding="utf-8"))
window.close()

shutil.rmtree(WORK, ignore_errors=True)

failed = [label for label, ok, _ in checks if not ok]
print()
if failed:
    print(f"ALTYAZI ICE AKTARMA BASARISIZ: {failed}")
    sys.exit(1)
print(f"{len(checks)} kontrol gecti")
print("ALTYAZI ICE AKTARMA: GECTI")
