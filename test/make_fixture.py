"""Test fixture'larını üretir.

Kullanım:
    py test/make_fixture.py            # yoksa üret
    py test/make_fixture.py --force    # üzerine yaz
    py test/make_fixture.py --check    # sadece durumu göster
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import fixtures  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    force = "--force" in args
    check_only = "--check" in args

    print("=" * 66)
    print("Subtra test fixture'ları")
    print("=" * 66)
    print(f"Klasör: {fixtures.TEST_DIR}")

    video = fixtures.video_path()
    print(f"\nVideo: {video.name}")
    if video.exists():
        size_kb = video.stat().st_size / 1024
        print(f"  durum: VAR ({size_kb:.0f} KB)")
    else:
        print("  durum: YOK")

    if check_only:
        print("\n(--check: üretim yapılmadı)")
        return 0 if video.exists() else 1

    if video.exists() and not force:
        print("  (zaten var; yeniden üretmek için --force)")
    else:
        print()
        result = fixtures.ensure_video(force=force)
        if result is None:
            print("\nÜRETİLEMEDİ.")
            print("Gerekli: ffmpeg + (Windows'ta) İngilizce SAPI sesi.")
            print("Alternatif: test videosunu elle test/konusma ingilizce.mp4 olarak koyun.")
            return 1

    srt = fixtures.require_srt()
    print(f"\nSRT  : {srt.name} ({srt.stat().st_size} bayt)")

    print("\nHazır. Testleri çalıştırın: py test/run_all.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
