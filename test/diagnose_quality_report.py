"""Video kalite teshisi: burn-in ciktisini kaynakla karsilastirir.

Kullanim:
    py test/diagnose_quality_report.py <kaynak_video> [cikti_video] [srt]

Cikti:
  * Altyazi olcegi (beyaz piksel orani)
  * Bloklanma farki (karanlik bolgeler)
  * SSIM (altyazili / temiz bolge ayri)
  * H.264 level ve bitrate karsilastirmasi
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
FFMPEG = str(PROJECT / "ffmpeg" / "bin" / "ffmpeg.exe")
FFPROBE = str(PROJECT / "ffmpeg" / "bin" / "ffprobe.exe")
WORK = PROJECT / "test" / "_diag"
WORK.mkdir(parents=True, exist_ok=True)
NO_WINDOW = 0x08000000


def run(cmd, cwd=None):
    result = subprocess.run(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=NO_WINDOW, text=True, encoding="utf-8", errors="replace",
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def probe(path: Path) -> dict:
    _, out = run([
        FFPROBE, "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=level,refs,profile,width,height,bit_rate,pix_fmt,avg_frame_rate",
        "-of", "default=nw=1", str(path),
    ])
    data = {}
    for line in out.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            data[key] = value
    return data


def gray(path: Path, timestamp: float) -> np.ndarray | None:
    raw = WORK / "f.raw"
    raw.unlink(missing_ok=True)
    code, _ = run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(path), "-ss", f"{timestamp}", "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", "gray", str(raw),
    ])
    if code != 0 or not raw.exists():
        return None
    data = np.frombuffer(raw.read_bytes(), dtype=np.uint8).copy()
    raw.unlink(missing_ok=True)
    return data


def blockiness(frame: np.ndarray, width: int, block: int = 8) -> float:
    height = frame.size // width
    if height * width != frame.size or height < 8:
        return 0.0
    image = frame.reshape(height, width).astype(np.float32)
    boundary = [c for c in range(block, width - 1, block)]
    inner = [c for c in range(1, width - 1) if c % block != 0]
    if not boundary or not inner:
        return 0.0
    b = np.abs(image[:, boundary] - image[:, np.array(boundary) - 1]).mean()
    i = np.abs(image[:, inner] - image[:, np.array(inner) - 1]).mean()
    return float(b / i) if i > 1e-6 else 0.0


def white_ratio(path: Path, timestamp: float) -> float:
    frame = gray(path, timestamp)
    return float((frame > 240).sum()) / frame.size if frame is not None else 0.0


def ssim(path: Path, reference: Path) -> tuple[float, float]:
    """(ortalama, en kotu) Y-SSIM. Kare hizlarini esitleyerek karsilastirir.

    Iki dosyanin timebase'i farkli olabilir (or. 1/15360 vs 1/30000); bu
    durumda filtre yanlis eslestirir. `fps` ile ortak tabana oturtulur.
    """
    log = WORK / "ssim.log"
    log.unlink(missing_ok=True)
    run([
        FFMPEG, "-hide_banner", "-nostats", "-y",
        "-i", str(path), "-i", str(reference),
        "-lavfi",
        "[1:v]setpts=N/FRAME_RATE/TB[ref];[0:v]setpts=N/FRAME_RATE/TB[main];"
        "[main][ref]ssim=stats_file=ssim.log",
        "-f", "null", "-",
    ], cwd=str(WORK))
    if not log.exists():
        return 0.0, 0.0
    pattern = re.compile(r"Y:([\d.]+)")
    values = [
        float(m.group(1))
        for m in (pattern.search(line) for line in log.read_text().splitlines())
        if m
    ]
    return (sum(values) / len(values), min(values)) if values else (0.0, 0.0)


def is_flat(frame: np.ndarray) -> bool:
    """Duz renkli kare mi? (bloklanma olcumu anlamsiz olur)."""
    if frame is None or frame.size == 0:
        return True
    return float(frame.std()) < 3.0


def srt_ranges(srt: Path) -> list[tuple[float, float]]:
    """SRT icindeki cue zaman araliklarini dondurur."""
    if not srt.exists():
        return []
    text = srt.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
    )
    ranges: list[tuple[float, float]] = []
    for m in pattern.finditer(text):
        start = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000
        end = int(m.group(5)) * 3600 + int(m.group(6)) * 60 + int(m.group(7)) + int(m.group(8)) / 1000
        ranges.append((start, end))
    return ranges


def in_ranges(timestamp: float, ranges: list[tuple[float, float]], pad: float = 0.4) -> bool:
    return any(start - pad <= timestamp <= end + pad for start, end in ranges)


def main() -> int:
    if len(sys.argv) < 2:
        print("Kullanim: py test/diagnose_quality_report.py <kaynak> [cikti] [srt]")
        return 1

    source = Path(sys.argv[1])
    if not source.exists():
        print("Kaynak bulunamadi:", source)
        return 1

    output = Path(sys.argv[2]) if len(sys.argv) > 2 else source.with_name(source.stem + "_tr.mp4")
    srt = Path(sys.argv[3]) if len(sys.argv) > 3 else source.with_name(source.stem + "_tr.srt")

    src_info = probe(source)
    width = int(src_info.get("width", 0))
    height = int(src_info.get("height", 0))
    fps_text = src_info.get("avg_frame_rate", "30/1")

    print("=" * 78)
    print("KAYNAK")
    print("=" * 78)
    print(f"  {width}x{height} @ {fps_text}  profile={src_info.get('profile')}  "
          f"level={int(src_info.get('level', 0))/10:.1f}")
    print(f"  bitrate={round(int(src_info.get('bit_rate') or 0)/1000)} kbps  "
          f"boyut={source.stat().st_size/(1024**2):.2f} MB")

    if not output.exists():
        print("\nCikti video bulunamadi:", output)
        return 1

    out_info = probe(output)
    print("\n" + "=" * 78)
    print("CIKTI")
    print("=" * 78)
    print(f"  {out_info.get('width')}x{out_info.get('height')} @ "
          f"{out_info.get('avg_frame_rate')}  profile={out_info.get('profile')}  "
          f"level={int(out_info.get('level', 0))/10:.1f}")
    print(f"  bitrate={round(int(out_info.get('bit_rate') or 0)/1000)} kbps  "
          f"boyut={output.stat().st_size/(1024**2):.2f} MB")

    print("\n" + "=" * 78)
    print("SSIM (kaynak referans)")
    print("=" * 78)
    mean, worst = ssim(output, source)
    print(f"  Ortalama Y: {mean:.4f}   En kotu kare: {worst:.4f}")

    if srt.exists():
        entries = re.findall(r"(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})",
                             srt.read_text(encoding="utf-8", errors="replace"))
        if entries:
            def parse(item, offset):
                return (int(item[offset]) * 3600 + int(item[offset + 1]) * 60
                        + int(item[offset + 2]) + int(item[offset + 3]) / 1000)
            first_start = parse(entries[0], 0)
            last_end = max(parse(item, 4) for item in entries)
            mid = (first_start + last_end) / 2
            src_white = white_ratio(source, mid)
            out_white = white_ratio(output, mid)
            print("\n  Altyazı alanı (beyaz piksel oranı):")
            print(f"    kaynak: {src_white*100:.2f}%")
            print(f"    çıktı : {out_white*100:.2f}%  "
                  f"(altyazı {(out_white-src_white)*100:.2f}%)")

    print("\n" + "=" * 78)
    print("BLOKLANMA (karanlık bölgeler — altyazılı kareler hariç, düşük daha iyi)")
    print("=" * 78)
    print(f"{'t(sn)':>8s} {'kaynak':>9s} {'çıktı':>9s} {'fark':>9s}")
    print("-" * 78)
    cue_ranges = srt_ranges(srt)
    diffs = []
    skipped = 0
    for timestamp in (2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0):
        if in_ranges(timestamp, cue_ranges):
            continue
        src_frame = gray(source, timestamp)
        out_frame = gray(output, timestamp)
        if src_frame is None or out_frame is None:
            continue
        if is_flat(src_frame):
            skipped += 1
            continue
        sb = blockiness(src_frame, width)
        ob = blockiness(out_frame, width)
        diffs.append(ob - sb)
        print(f"{timestamp:8.1f} {sb:9.3f} {ob:9.3f} {ob-sb:+9.3f}")
    if skipped:
        print(f"  ({skipped} kare düz renkli olduğu için atlandı)")
    if diffs:
        average = sum(diffs) / len(diffs)
        verdict = "İYİ" if average < 0.1 else ("KABUL EDİLEBİLİR" if average < 0.2 else "KÖTÜ")
        print("-" * 78)
        print(f"{'ORTALAMA':>8s} {'':>9s} {'':>9s} {average:+9.3f}   -> {verdict}")
        if average >= 0.2:
            print("\n  Öneri: burn-in CRF'i 16'ya düşürün ve preset'i slow yapın.")
    else:
        print("  Yeterli dokulu kare bulunamadı (düz renkli video).")

    import shutil
    shutil.rmtree(WORK, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
