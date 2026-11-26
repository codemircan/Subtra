"""Burn-in çoklu ses kanalı koruma testi."""

import io
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import ffmpeg_bootstrap
import ffmpeg_utils as fu
import fixtures
from ffmpeg_utils import SubtitleStyle

PROJECT = Path(__file__).resolve().parent.parent
WORK = PROJECT / "test" / "_multi"
WORK.mkdir(parents=True, exist_ok=True)
NO_WINDOW = 0x08000000

loc = ffmpeg_bootstrap.find_existing()
if loc is None:
    raise SystemExit(fixtures.skip("FFmpeg bulunamadı (otomatik indirme testlerde kapalı)"))
FFMPEG, FFPROBE = loc.ffmpeg, loc.ffprobe

checks = []


def check(label, ok, detail=""):
    checks.append((label, ok))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))


def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       creationflags=NO_WINDOW, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def streams(path: Path) -> list[tuple[str, str]]:
    """(codec_type, codec_name) listesi — JSON ile sütun sırasına bağımlı değil."""
    code, out = run([FFPROBE, "-v", "error", "-print_format", "json",
                     "-show_entries", "stream=codec_type,codec_name", str(path)])
    if code != 0:
        return []
    import json

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    return [
        (str(s.get("codec_type", "")), str(s.get("codec_name", "")))
        for s in data.get("streams", [])
    ]


print("=" * 66)
print("1) Çoklu ses kanallı test videosu üretiliyor")
print("=" * 66)
source = WORK / "multi_audio.mp4"
if source.exists():
    source.unlink()

# 2 farklı ses + 1 video, ayrıca bir altyazı akışı
code, out = run([
    FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
    "-f", "lavfi", "-i", "color=c=0x203040:s=640x360:d=6",
    "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
    "-f", "lavfi", "-i", "sine=frequency=880:duration=6",
    "-map", "0:v", "-map", "1:a", "-map", "2:a",
    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "96k",
    "-metadata:s:a:0", "language=tur",
    "-metadata:s:a:1", "language=eng",
    str(source),
])
if code != 0:
    print("  video üretilemedi:", out[-300:])
    sys.exit(1)

src_streams = streams(source)
print(f"   kaynak akışları: {src_streams}")
check("kaynakta 2 ses kanalı var", sum(1 for t, _ in src_streams if t == "audio") == 2)

print("\n" + "=" * 66)
print("2) SRT hazırlanıyor ve burn-in çalıştırılıyor")
print("=" * 66)
srt = WORK / "multi_audio_tr.srt"
srt.write_text(
    "1\n00:00:01,000 --> 00:00:03,000\nTest altyazı\n\n"
    "2\n00:00:03,500 --> 00:00:05,500\nİkinci satır\n",
    encoding="utf-8",
)

output = WORK / "multi_audio_burn.mp4"
if output.exists():
    output.unlink()

code, out = run([
    FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
    "-i", str(source),
    "-vf", fu.build_subtitles_filter(srt, SubtitleStyle(font_size=20), 640, 360),
    "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?", "-map_metadata", "0",
    "-c:v", "libx264", "-preset", "medium", "-crf", "20",
    "-pix_fmt", "yuv420p", "-c:a", "copy", "-c:s", "mov_text",
    str(output),
])
if code != 0:
    print("  encode hatası:", out[-500:])
    check("burn-in başarılı", False)
    sys.exit(1)

check("burn-in başarılı", output.exists())

print("\n" + "=" * 66)
print("3) Çıktıda akışlar korunmuş mu")
print("=" * 66)
dst = streams(output)
print(f"   çıktı akışları: {dst}")

src_audio = sum(1 for t, _ in src_streams if t == "audio")
dst_audio = sum(1 for t, _ in dst if t == "audio")
print(f"   ses kanalı: kaynak {src_audio} -> çıktı {dst_audio}")
check("iki ses kanalı da korundu", dst_audio == src_audio, f"{dst_audio}/{src_audio}")
check("video akışı var", any(t == "video" for t, _ in dst))

# Ses dilleri korunmuş mu
code, out = run([FFPROBE, "-v", "error", "-select_streams", "a",
                 "-show_entries", "stream=index:stream_tags=language",
                 "-of", "csv=p=0", str(output)])
langs = [line.strip() for line in out.strip().splitlines() if line.strip()]
print(f"   ses dilleri: {langs}")
check("ses dili etiketleri korundu", len(langs) == 2, str(langs))

print("\n" + "=" * 66)
print("4) Eski davranış (-map 0:a:0) ile karşılaştırma")
print("=" * 66)
old_out = WORK / "multi_audio_old.mp4"
if old_out.exists():
    old_out.unlink()
code, out = run([
    FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
    "-vf", fu.build_subtitles_filter(srt, SubtitleStyle(font_size=20), 640, 360),
    "-map", "0:v:0", "-map", "0:a:0",
    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "copy",
    str(old_out),
])
old_audio = sum(1 for t, _ in streams(old_out) if t == "audio") if code == 0 else -1
print(f"   eski yöntemle ses kanalı: {old_audio} (kaynak 2)")
check("eski yöntem kanal kaybediyordu (regresyon kanıtı)", old_audio == 1, f"{old_audio}")

print("\n" + "=" * 66)
failed = [label for label, ok in checks if not ok]
print(f"{len(checks) - len(failed)}/{len(checks)} kontrol geçti")
print("ÇOKLU SES KANALI TESTİ: " + ("GEÇTİ" if not failed else f"BAŞARISIZ -> {failed}"))

import shutil
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(0 if not failed else 1)
