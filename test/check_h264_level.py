"""H.264 level uygunlugunu (MaxFS / MaxDPB) denetler.

Yirtilma ve kismi piksellesmenin nedeni: kodlanan stream, bildirilen level'in
sinirlarini asiyorsa bazi cozuculer (ozellikle donanim cozuculer ve mobil
oynaticilar) kareyi eksik cozer; sonuc yirtilma / blok kopyalama olur.

1080x1918 @ 30 fps:
  Makroblok/kare = ceil(1080/16) * ceil(1918/16) = 68 * 120 = 8160
  Level 4.0 MaxFS = 8192        -> sigar (sinirda)
  Level 4.0 MaxDPB = 32768      -> 32768 / 8160 = 4.01 kare
  ref=3 icin gereken kare    = 5   -> SIGMAZ (ihlal)
  ref=5 icin gereken kare    = 7   -> SIGMAZ (ihlal)
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import ffmpeg_utils as fu  # noqa: E402

LEVELS = {
    # level: (MaxFS, MaxMBPS, MaxDPB)
    "4.0": (8192, 245760, 32768),
    "4.1": (8192, 245760, 32768),
    "4.2": (8704, 522240, 34816),
    "5.0": (22080, 589824, 86016),
    "5.1": (36864, 983040, 184320),
    "5.2": (36864, 2073600, 184320),
    "6.0": (139264, 4177920, 696320),
}


def check(width: int, height: int, fps: float, refs: int, level: str) -> dict:
    mbs_w = (width + 15) // 16
    mbs_h = (height + 15) // 16
    frame_mbs = mbs_w * mbs_h
    mbps = frame_mbs * fps
    max_fs, max_mbps, max_dpb = LEVELS[level]

    frames_in_dpb = max_dpb / frame_mbs
    needed = refs + 2  # referans kareler + guncel kare (+ b kare payi)

    return {
        "mb_w": mbs_w,
        "mb_h": mbs_h,
        "frame_mbs": frame_mbs,
        "mbps": mbps,
        "max_fs": max_fs,
        "max_mbps": max_mbps,
        "max_dpb": max_dpb,
        "frames_in_dpb": frames_in_dpb,
        "needed_frames": needed,
        "fs_ok": frame_mbs <= max_fs,
        "mbps_ok": mbps <= max_mbps,
        "dpb_ok": needed <= frames_in_dpb,
    }


CASES = [
    ("Kullanicinin videosu (ESKI ayar)", 1080, 1918, 30.0, 3, "4.0"),
    ("Kullanicinin videosu (YENI ayar)", 1080, 1918, 30.0, 5, "5.0"),
    ("1080p yatay (yaygin)", 1920, 1080, 30.0, 5, "5.0"),
    ("720p", 1280, 720, 30.0, 5, "4.0"),
]

print("=" * 88)
print("H.264 LEVEL UYGUNLUK DENETIMI")
print("=" * 88)

for label, width, height, fps, refs, level in CASES:
    data = check(width, height, fps, refs, level)
    ok = data["fs_ok"] and data["mbps_ok"] and data["dpb_ok"]
    computed = fu.h264_level_for(width, height, fps, refs)

    print(f"\n{label}")
    print(f"  {width}x{height} @ {fps:.0f} fps, ref={refs}, bildirilen level={level}")
    print(f"  Makroblok blogu        : {data['mb_w']} x {data['mb_h']} = {data['frame_mbs']}")
    print(f"  MaxFS  (level {level})   : {data['frame_mbs']} <= {data['max_fs']}          "
          f"{'OK' if data['fs_ok'] else 'IHLAL'}")
    print(f"  MaxMBPS(level {level})   : {data['mbps']:.0f} <= {data['max_mbps']}      "
          f"{'OK' if data['mbps_ok'] else 'IHLAL'}")
    print(f"  MaxDPB (level {level})   : {data['needed_frames']} kare gerekli, "
          f"{data['frames_in_dpb']:.2f} kare sigar   "
          f"{'OK' if data['dpb_ok'] else 'IHLAL <<<'}")
    print(f"  Sonuc: {'UYUMLU' if ok else 'UYUMSUZ — yirtilma/bloklanma riski'}")
    print(f"  Dogru level (hesaplanan): {computed}")

print("\n" + "=" * 88)
print("OZET")
print("=" * 88)
print("Eski cikti: level 4.0 + ref=3 -> DPB ihlali (4.01 kare yerine 5 gerekli)")
print("  => Bazi cozuculer kareyi eksik cozer: yirtilma, kismi piksellesme.")
print("Yeni cikti: level 5.0 + ref=5 -> DPB 10.5 kare, 7 gerekli -> uyumlu.")
