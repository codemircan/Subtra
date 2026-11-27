"""Subtra simgesini uretir: assets/app.ico (+ PNG onizlemeler).

Kullanim:
    py tools/make_icon.py           # uret
    py tools/make_icon.py --check   # dosya var mi ve gecerli mi

Neden Qt? Projede Pillow yok; Qt zaten bagimli ve PNG uretimi birebir
ayni. ICO dosyasi elle paketlenir (PNG sikistirmali girisler, Vista+),
boylece 16/24/32/48/64/128/256 piksel surumler tek dosyada olur.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ICON = ASSETS / "app.ico"
PREVIEW = ASSETS / "app_256.png"

SIZES = (16, 24, 32, 48, 64, 128, 256)

BG_TOP = "#1B2450"
BG_BOTTOM = "#3B4FD8"
BAR_COLOR = "#FFFFFF"
ACCENT = "#FFB020"


def _render(size: int) -> bytes:
    """Tek boyutu PNG bayt dizisi olarak dondurur."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QBuffer, QByteArray, QPointF, QRectF, Qt
    from PySide6.QtGui import (
        QColor,
        QGuiApplication,
        QImage,
        QLinearGradient,
        QPainter,
        QPainterPath,
        QPolygonF,
    )

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    assert app is not None

    scale = 4  # kenar yumusatma icin buyuk ciz, sonra kucult
    canvas = size * scale
    image = QImage(canvas, canvas, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    # Arka plan: yuvarlatilmis kare + dikey gecis
    gradient = QLinearGradient(0, 0, 0, canvas)
    gradient.setColorAt(0.0, QColor(BG_TOP))
    gradient.setColorAt(1.0, QColor(BG_BOTTOM))
    background = QPainterPath()
    background.addRoundedRect(QRectF(0, 0, canvas, canvas), canvas * 0.22, canvas * 0.22)
    painter.fillPath(background, gradient)

    # Oynat ucgeni (video isareti)
    triangle = QPolygonF(
        [
            QPointF(canvas * 0.39, canvas * 0.17),
            QPointF(canvas * 0.39, canvas * 0.40),
            QPointF(canvas * 0.60, canvas * 0.285),
        ]
    )
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(ACCENT))
    painter.drawPolygon(triangle)

    # Iki altyazi cubugu
    painter.setBrush(QColor(BAR_COLOR))

    def bar(x: float, y: float, width: float, height: float) -> None:
        rect = QRectF(canvas * x, canvas * y, canvas * width, canvas * height)
        painter.drawRoundedRect(rect, rect.height() / 2.0, rect.height() / 2.0)

    bar(0.16, 0.56, 0.68, 0.115)
    bar(0.16, 0.74, 0.46, 0.115)

    painter.end()

    image = image.scaled(
        size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
    )
    byte_array = QByteArray()
    buffer = QBuffer(byte_array)
    buffer.open(QBuffer.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(byte_array.data())


def _pack_ico(images: dict[int, bytes]) -> bytes:
    """PNG girisli ICO dosyasi paketler."""
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    entries = bytearray()
    offset = 6 + 16 * count
    payload = bytearray()
    for size in sorted(images):
        data = images[size]
        entries += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,
            size if size < 256 else 0,
            0, 0, 1, 32, len(data), offset,
        )
        payload += data
        offset += len(data)
    return bytes(header + entries + payload)


def build() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    images = {size: _render(size) for size in SIZES}
    ICON.write_bytes(_pack_ico(images))
    PREVIEW.write_bytes(images[256])
    print(f"  yazildi: {ICON} ({ICON.stat().st_size / 1024:.1f} KB, {len(SIZES)} boyut)")
    print(f"  yazildi: {PREVIEW} ({PREVIEW.stat().st_size / 1024:.1f} KB)")


def check() -> int:
    if not ICON.exists():
        print("  FAIL: assets/app.ico yok")
        return 1
    raw = ICON.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", raw[:6])
    ok = reserved == 0 and kind == 1 and count == len(SIZES)
    sizes = []
    for index in range(count):
        entry = raw[6 + 16 * index : 6 + 16 * (index + 1)]
        width, _height, _colors, _res, _planes, _bpp, length, offset = struct.unpack(
            "<BBBBHHII", entry
        )
        sizes.append(width or 256)
        ok = ok and raw[offset : offset + 8] == b"\x89PNG\r\n\x1a\n" and length > 0
    print(f"  ICO gecerli: {ok} | boyutlar: {sizes}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    build()
    sys.exit(check())
