"""Eski ve yeni burn-in ciktisini ayni noktalarda karsilastirir (ozet)."""

import io
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import numpy as np

import ffmpeg_utils as fu

PROJECT = Path(__file__).resolve().parent.parent
FFMPEG = str(PROJECT / "ffmpeg" / "bin" / "ffmpeg.exe")
FFPROBE = str(PROJECT / "ffmpeg" / "bin" / "ffprobe.exe")
DOWNLOADS = Path(r"C:\Users\Administrator\Downloads")
SRC = DOWNLOADS / "ValidStrongAfricanaugurbuzzard.mp4"
if not SRC.exists():
    SRC = next(p for p in DOWNLOADS.glob("*.mp4") if not p.stem.endswith("_tr"))
SRT = SRC.with_name(SRC.stem + "_tr.srt")
OLD = SRC.with_name(SRC.stem + "_tr.mp4")
WORK = PROJECT / "test" / "_final"
WORK.mkdir(parents=True, exist_ok=True)
NO_WINDOW = 0x08000000


def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       creationflags=NO_WINDOW, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def gray(path, t):
    raw = WORK / "f.raw"
    raw.unlink(missing_ok=True)
    code, _ = run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
                   "-ss", str(t), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", str(raw)])
    if code != 0 or not raw.exists():
        return None
    data = np.frombuffer(raw.read_bytes(), dtype=np.uint8).copy()
    raw.unlink(missing_ok=True)
    return data


def blockiness(frame, width, block=8):
    h = frame.size // width
    if h * width != frame.size or h < 8:
        return 0.0
    img = frame.reshape(h, width).astype(np.float32)
    b_cols = [c for c in range(block, width - 1, block)]
    i_cols = [c for c in range(1, width - 1) if c % block != 0]
    if not b_cols or not i_cols:
        return 0.0
    b = np.abs(img[:, b_cols] - img[:, np.array(b_cols) - 1]).mean()
    i = np.abs(img[:, i_cols] - img[:, np.array(i_cols) - 1]).mean()
    return float(b / i) if i > 1e-6 else 0.0


width, height, fps = fu.media_size(FFPROBE, SRC)
style = fu.SubtitleStyle(font_size=18, color="#FFFFFF", position="bottom")

new = WORK / "new.mp4"
new.unlink(missing_ok=True)
level = fu.h264_level_for(width, height, fps)
code, out = run([
    FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(SRC),
    "-vf", fu.build_subtitles_filter(SRT, style, width, height),
    "-map", "0:v:0", "-map", "0:a:0",
    "-c:v", "libx264", "-preset", fu.BURN_IN_PRESET, "-crf", str(fu.BURN_IN_CRF),
    "-x264-params", fu.BURN_IN_X264_PARAMS, "-pix_fmt", "yuv420p",
    "-level", level, "-c:a", "copy", str(new),
], cwd=str(SRT.parent))
if code != 0:
    print("HATA:", out[-400:])
    sys.exit(1)

POINTS = (12.0, 14.0, 16.0, 18.0, 20.0)
print("=" * 76)
print(f"BLOKLANMA KARSILASTIRMASI — {width}x{height}@{fps:.0f} level={level}")
print("=" * 76)
print(f"{'t(sn)':>7s} {'kaynak':>9s} {'ESKI':>9s} {'YENI':>9s} {'eski fark':>11s} {'yeni fark':>11s}")
print("-" * 76)
old_sum = new_sum = 0.0
for t in POINTS:
    sb = blockiness(gray(SRC, t), width)
    ob = blockiness(gray(OLD, t), width)
    nb = blockiness(gray(new, t), width)
    old_sum += ob - sb
    new_sum += nb - sb
    print(f"{t:7.1f} {sb:9.3f} {ob:9.3f} {nb:9.3f} {ob-sb:+11.3f} {nb-sb:+11.3f}")
print("-" * 76)
om = old_sum / len(POINTS)
nm = new_sum / len(POINTS)
print(f"{'ORT.':>7s} {'':>9s} {'':>9s} {'':>9s} {om:+11.3f} {nm:+11.3f}")
print(f"\nBloklanma iyilesmesi: %{(1 - nm/om)*100:.1f}" if om else "")

# Altyazi alani
def white(p, t):
    f = gray(p, t)
    return float((f > 240).sum()) / f.size if f is not None else 0.0

print("\n" + "=" * 76)
print("ALTYAZI ALANI (beyaz piksel orani)")
print("=" * 76)
sw, ow, nw = white(SRC, 3.0), white(OLD, 3.0), white(new, 3.0)
print(f"  kaynak: {sw*100:5.2f}%   ESKI: {ow*100:5.2f}%   YENI: {nw*100:5.2f}%")
if ow > sw:
    print(f"  Altyazi alani azalmasi: %{(1 - (nw-sw)/(ow-sw))*100:.1f}")

print("\n" + "=" * 76)
print("BOYUT / LEVEL")
print("=" * 76)
for label, path in (("kaynak", SRC), ("ESKI", OLD), ("YENI", new)):
    _, info = run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                   "-show_entries", "stream=level,bit_rate", "-of", "csv=p=0", str(path)])
    parts = info.strip().split(",")
    try:
        lv = int(parts[0]) / 10
        br = round(int(parts[1]) / 1000)
    except (ValueError, IndexError):
        lv, br = 0, 0
    print(f"  {label:8s} level={lv:.1f} bitrate={br:5d} kbps boyut={path.stat().st_size/(1024**2):5.2f} MB")

import shutil
shutil.rmtree(WORK, ignore_errors=True)
