"""İndirme devam ettirme (Range) testi — gerçek HTTP sunucusu ile.

Senaryo:
  1. İlk istek yarıda kesilir (.part korunmalı)
  2. İkinci istek Range ile devam eder (206)
  3. Dosya bütünlüğü doğrulanır (SHA256)
  4. Sunucu Range desteklemiyorsa (200) baştan yazar
"""

import hashlib
import io
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from transcriber import ModelDownloadError, _download_with_resume  # noqa: E402

PAYLOAD = bytes((i * 37 + 11) % 256 for i in range(400_000))
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()
CUT_AFTER = 150_000       # ilk istekte bu kadar bayt gönderip keseceğiz

state = {"requests": [], "cut_done": False, "ignore_range": False}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        try:
            self._handle()
        except (ConnectionResetError, BrokenPipeError, OSError):
            self.close_connection = True

    def _handle(self):
        range_header = self.headers.get("Range")
        state["requests"].append(range_header)

        start = 0
        if range_header and not state["ignore_range"]:
            try:
                start = int(range_header.split("=")[1].split("-")[0])
            except (IndexError, ValueError):
                start = 0

        body = PAYLOAD[start:]
        if range_header and not state["ignore_range"] and start > 0:
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(PAYLOAD)-1}/{len(PAYLOAD)}")
        else:
            self.send_response(200)
            start = 0
            body = PAYLOAD

        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

        # İlk istekte yarıda kes (ağ kopması taklidi)
        if not state["cut_done"] and start == 0:
            state["cut_done"] = True
            self.wfile.write(body[:CUT_AFTER])
            self.wfile.flush()
            time.sleep(0.2)
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return

        self.wfile.write(body)


def start_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


class FakeSession:
    """requests.Session yerine ince sarmalayıcı."""

    def get(self, url, stream=True, timeout=120, headers=None):
        import requests

        return requests.get(url, stream=stream, timeout=timeout, headers=headers or {})


def check(label: str, ok: bool) -> bool:
    print(f"  {'OK  ' if ok else 'FAIL'} {label}")
    return ok


def main() -> int:
    import tempfile

    server, port = start_server()
    url = f"http://127.0.0.1:{port}/model.bin"
    work = Path(tempfile.mkdtemp(prefix="resume_test_"))
    part = work / "model.bin.part"
    results = []

    print("=" * 70)
    print("1) İlk indirme yarıda kesiliyor")
    print("=" * 70)
    session = FakeSession()
    try:
        _download_with_resume(
            session, url, part, len(PAYLOAD), "model.bin",
            None, None, None, 0, len(PAYLOAD),
        )
        print("  (beklenmedik: kesilmedi)")
    except ModelDownloadError as exc:
        print(f"  Beklenen hata: {str(exc).splitlines()[0]}")
    except Exception as exc:  # noqa: BLE001
        print(f"  Beklenmeyen: {type(exc).__name__}: {exc}")

    exists = part.exists()
    size = part.stat().st_size if exists else 0
    results.append(check(f".part korundu ({size} bayt)", exists and size > 0))
    results.append(check("kısmi ilerleme kaydedildi (0 < boyut < toplam)",
                         exists and 0 < size < len(PAYLOAD)))
    print(f"  kayıp: {len(PAYLOAD) - size} bayt "
          f"(parça boyutu {64*1024}, en fazla bu kadar kaybolur)")

    print("\n" + "=" * 70)
    print("2) Devam ettirme (Range)")
    print("=" * 70)
    state["requests"].clear()
    written = _download_with_resume(
        session, url, part, len(PAYLOAD), "model.bin",
        lambda m: print("   LOG", m), None, None, 0, len(PAYLOAD),
    )
    print(f"  istek başlıkları: {state['requests']}")
    results.append(check("Range başlığı gönderildi", any(r for r in state["requests"])))
    results.append(check("tüm istekler Range içeriyor",
                         all(r for r in state["requests"]) if state["requests"] else False))

    data = part.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    results.append(check(f"boyut doğru ({len(data)} bayt)", len(data) == len(PAYLOAD)))
    results.append(check("SHA256 eşleşiyor (bozulma yok)", digest == PAYLOAD_SHA))

    print("\n" + "=" * 70)
    print("3) Sunucu Range desteklemiyorsa (200) baştan yazar")
    print("=" * 70)
    state["ignore_range"] = True
    state["cut_done"] = True
    part.unlink(missing_ok=True)
    part.write_bytes(PAYLOAD[:1000])  # yanlış kısmi veri
    written = _download_with_resume(
        session, url, part, len(PAYLOAD), "model.bin", None, None, None, 0, len(PAYLOAD),
    )
    data = part.read_bytes()
    results.append(check("baştan yazıldı, boyut doğru", len(data) == len(PAYLOAD)))
    results.append(check("SHA256 eşleşiyor", hashlib.sha256(data).hexdigest() == PAYLOAD_SHA))

    print("\n" + "=" * 70)
    print("4) İptal → .part silinir")
    print("=" * 70)
    state["ignore_range"] = False
    part.unlink(missing_ok=True)
    cancel = threading.Event()
    cancel.set()
    try:
        _download_with_resume(
            session, url, part, len(PAYLOAD), "model.bin", None, None, cancel, 0, len(PAYLOAD),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  iptal: {type(exc).__name__}")
    results.append(check("iptalde .part silindi", not part.exists()))

    server.shutdown()
    import shutil

    shutil.rmtree(work, ignore_errors=True)

    print("\n" + "=" * 70)
    print(f"{sum(results)}/{len(results)} kontrol geçti")
    print("İNDİRME DEVAM ETTİRME TESTİ " + ("GEÇTİ" if all(results) else "BAŞARISIZ"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
