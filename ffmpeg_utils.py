"""FFmpeg bulma, dogrulama, ses cikarma ve video isleme yardimcilari.

Windows'a ozgu notlar:
  * Tum subprocess cagrilari liste halinde yapilir; shell=True asla kullanilmaz.
  * ffmpeg.exe yoksa anlasilir bir FFmpegError firlatilir.
  * subtitles filtresi icin dosya yolu ayrica kacislanir (escape).
"""

from __future__ import annotations

import errno
import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from errors import CancelledError, FFmpegDownloadError, FFmpegError, FFmpegNotFound

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

FFMPEG_DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/"

ProgressCB = Optional[Callable[[float], None]]


@dataclass
class SubtitleStyle:
    """Burn-in altyazi stili.

    `font_size`, `outline` ve `margin_v` "referans olcek" birimindedir:
    640 piksel yukseklige gore tasarlanmistir. Gercek video yuksekligine
    gore olceklenir (bkz. `scaled`).

    Neden: libass varsayilan olarak PlayResY=288 kullanir ve FontSize'i bu
    kutuya gore olcekler. 1918 piksel yuksekligindeki bir videoda
    FontSize=18 -> 120 piksel dev yazi olur, altyazi ekrani kaplar.
    Bu yuzden PlayResX/PlayResY video boyutuna esitlenir ve punto degeri
    piksele cevrilir.
    """

    font_name: str = "Arial"
    font_size: int = 18
    color: str = "#FFFFFF"
    position: str = "bottom"  # bottom | middle | top
    outline: int = 2
    margin_v: int = 20

    # Referans yukseklik: font_size=18 bu yukseklikte 18 piksele karsilik gelir.
    REFERENCE_HEIGHT = 640

    def primary_colour(self) -> str:
        """#RRGGBB -> libass &HAABBGGRR (renk BGR sirasindadir)."""
        value = (self.color or "#FFFFFF").lstrip("#")
        if len(value) != 6:
            value = "FFFFFF"
        try:
            r, g, b = value[0:2], value[2:4], value[4:6]
            int(value, 16)
        except ValueError:
            r, g, b = "FF", "FF", "FF"
        return f"&H00{b}{g}{r}".upper()

    def alignment(self) -> int:
        return {"bottom": 2, "middle": 5, "top": 8}.get(self.position, 2)

    def scaled(self, video_width: int, video_height: int) -> "SubtitleStyle":
        """Stili gercek video boyutuna olcekler (piksel birimine)."""
        height = max(1, int(video_height or self.REFERENCE_HEIGHT))
        factor = height / float(self.REFERENCE_HEIGHT)

        # Punto -> piksel. Alt sinir 14 px, ust sinir ekranin 1/8'i.
        font_px = int(round(self.font_size * factor))
        font_px = max(14, min(font_px, max(14, height // 8)))

        outline_px = max(1, int(round(self.outline * factor)))
        margin_px = max(8, int(round(self.margin_v * factor)))

        return SubtitleStyle(
            font_name=self.font_name,
            font_size=font_px,
            color=self.color,
            position=self.position,
            outline=outline_px,
            margin_v=margin_px,
        )

    def force_style(self, video_width: int = 0, video_height: int = 0) -> str:
        """libass force_style dizesi.

        video_width/height verilirse PlayRes video boyutuna esitlenir ve
        punto degeri piksele cevrilir; bu, her cozunurlukte dogru boyut verir.
        """
        style = self
        play_res = ""
        if video_width > 0 and video_height > 0:
            style = self.scaled(video_width, video_height)
            play_res = f"PlayResX={int(video_width)},PlayResY={int(video_height)},"

        return (
            f"{play_res}"
            f"FontName={style.font_name},FontSize={int(style.font_size)},"
            f"PrimaryColour={style.primary_colour()},"
            "OutlineColour=&H00000000,BackColour=&H80000000,"
            f"BorderStyle=1,Outline={int(style.outline)},Shadow=0,"
            f"Alignment={style.alignment()},MarginV={int(style.margin_v)}"
        )


# --------------------------------------------------------------------------
# FFmpeg bulma / dogrulama
# --------------------------------------------------------------------------

def _candidate_bin_dirs() -> list[Path]:
    project_dir = Path(__file__).resolve().parent
    dirs: list[Path] = []
    env = os.environ
    if env.get("FFMPEG_HOME"):
        dirs.append(Path(env["FFMPEG_HOME"]) / "bin")
    dirs.extend(
        [
            project_dir / "ffmpeg" / "bin",
            project_dir / "tools" / "ffmpeg" / "bin",
            Path(r"C:\ffmpeg\bin"),
        ]
    )
    if env.get("LOCALAPPDATA"):
        dirs.append(Path(env["LOCALAPPDATA"]) / "Microsoft" / "WinGet" / "Links")
    if env.get("ProgramFiles"):
        dirs.append(Path(env["ProgramFiles"]) / "ffmpeg" / "bin")
    if env.get("ProgramData"):
        dirs.append(Path(env["ProgramData"]) / "chocolatey" / "bin")
    return dirs


def _verify_ffmpeg(exe: str) -> bool:
    try:
        result = subprocess.run(
            [exe, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            timeout=25,
            creationflags=CREATE_NO_WINDOW,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return False
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0 and "ffmpeg version" in output.lower()


def find_ffmpeg(explicit_path: str | None = None) -> tuple[str, str]:
    """(ffmpeg, ffprobe) tam yollarini dondurur.

    Sirasi: elle secilen > gomulu > uygulama klasoru > otomatik indirilen >
    PATH > eski kurulumlar. Bulamazsa FFmpegError firlatilir.
    """
    import ffmpeg_bootstrap

    location = ffmpeg_bootstrap.find_existing(explicit_path)
    if location is not None:
        return location.as_tuple()

    # Geriye donuk uyumluluk: eski kurulum yerleri.
    checked: list[str] = []
    if explicit_path:
        candidates = [explicit_path]
    else:
        candidates = []
        which = shutil.which("ffmpeg")
        if which:
            candidates.append(which)
        for directory in _candidate_bin_dirs():
            candidates.append(str(directory / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")))

    for exe in candidates:
        if not exe or not Path(exe).exists():
            continue
        checked.append(exe)
        if _verify_ffmpeg(exe):
            ffprobe = _find_ffprobe(exe)
            if not ffprobe:
                raise FFmpegError(
                    "ffmpeg bulundu ancak ffprobe bulunamadı.\n"
                    f"ffmpeg konumu: {exe}\n"
                    "FFmpeg'i tam paket olarak (ffmpeg + ffprobe) yeniden kurun."
                )
            return exe, ffprobe

    message = (
        "FFmpeg bulunamadı. Bu program altyazıyı videoya işlemek ve sesi "
        "çıkarmak için FFmpeg'e ihtiyaç duyar.\n\n"
        "Kurulum seçenekleri:\n"
        "  1) Ayarlar'daki 'FFmpeg'i İndir' düğmesi (otomatik)\n"
        "  2) winget install Gyan.FFmpeg\n"
        f"  3) {FFMPEG_DOWNLOAD_URL} adresinden indirip PATH'e ekleyin\n"
        "  4) 'ffmpeg.exe Yolu Seç…' ile dosyayı elle gösterin\n"
    )
    if checked:
        message += "\nDenenen yollar:\n" + "\n".join(f"  - {p}" for p in checked)
    raise FFmpegNotFound(message)


def _find_ffprobe(ffmpeg_exe: str) -> str | None:
    sibling = Path(ffmpeg_exe).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if sibling.exists():
        return str(sibling)
    return shutil.which("ffprobe")


# --------------------------------------------------------------------------
# ffprobe sorgulari
# --------------------------------------------------------------------------

def probe_media(ffprobe: str, path: str | Path) -> dict:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            timeout=120,
            creationflags=CREATE_NO_WINDOW,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FFmpegError(f"Dosya okunamadı: {path}\n{exc}") from exc

    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-5:]
        raise FFmpegError(
            "Video dosyası çözümlenemedi veya bozuk.\n" + "\n".join(tail)
        )
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise FFmpegError("ffprobe çıktısı okunamadı.") from exc


def has_audio_stream(ffprobe: str, path: str | Path) -> bool:
    info = probe_media(ffprobe, path)
    return any(s.get("codec_type") == "audio" for s in info.get("streams", []))


def audio_streams(ffprobe: str, path: str | Path) -> list[dict]:
    """Ses akislarini sirali listeler.

    `audio_index` 0 tabanlidir ve `-map 0:a:<n>` icin kullanilir; `index`
    ise dosyadaki genel akis indeksidir (ffprobe'un verdigi deger).
    """
    info = probe_media(ffprobe, path)
    tracks: list[dict] = []
    audio_index = 0
    for stream in info.get("streams", []):
        if stream.get("codec_type") != "audio":
            continue
        tags = stream.get("tags") or {}
        disposition = stream.get("disposition") or {}
        try:
            index = int(stream.get("index", 0))
        except (TypeError, ValueError):
            index = 0
        try:
            channels = int(stream.get("channels") or 0)
        except (TypeError, ValueError):
            channels = 0
        tracks.append(
            {
                "audio_index": audio_index,
                "index": index,
                "codec": (stream.get("codec_name") or "").strip().lower(),
                "channels": channels,
                "language": (tags.get("language") or "").strip().lower(),
                "title": (tags.get("title") or "").strip(),
                "default": bool(disposition.get("default")),
            }
        )
        audio_index += 1
    return tracks


def has_video_stream(ffprobe: str, path: str | Path) -> bool:
    info = probe_media(ffprobe, path)
    return any(
        s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
        for s in info.get("streams", [])
    )


# Metne cevrilebilen altyazi codec'leri. Gorsel tabanli olanlar (PGS,
# VobSub, DVB) ffmpeg ile SRT'ye cevrilemez; kullaniciya net soylenir.
TEXT_SUBTITLE_CODECS = frozenset(
    {
        "subrip",
        "srt",
        "ass",
        "ssa",
        "mov_text",
        "webvtt",
        "text",
        "microdvd",
        "subviewer",
        "subviewer1",
        "sami",
        "realtext",
        "jacosub",
        "mpl2",
        "pjs",
        "stl",
        "vplayer",
        "eia_608",
    }
)
IMAGE_SUBTITLE_CODECS = frozenset(
    {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"}
)


def subtitle_streams(ffprobe: str, path: str | Path) -> list[dict]:
    """Videodaki gomulu altyazi akislarini listeler (sirali)."""
    info = probe_media(ffprobe, path)
    streams: list[dict] = []
    for stream in info.get("streams", []):
        if stream.get("codec_type") != "subtitle":
            continue
        tags = stream.get("tags") or {}
        disposition = stream.get("disposition") or {}
        codec = (stream.get("codec_name") or "").strip().lower()
        try:
            index = int(stream.get("index", 0))
        except (TypeError, ValueError):
            continue
        streams.append(
            {
                "index": index,
                "codec": codec,
                "language": (tags.get("language") or "").strip().lower(),
                "title": (tags.get("title") or "").strip(),
                "default": bool(disposition.get("default")),
                "forced": bool(disposition.get("forced")),
                "text_based": codec in TEXT_SUBTITLE_CODECS,
                "image_based": codec in IMAGE_SUBTITLE_CODECS,
            }
        )
    return streams


def extract_subtitle_stream(
    ffmpeg: str,
    ffprobe: str,
    source: str | Path,
    stream_index: int,
    dest_srt: str | Path,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Gomulu altyazi akisini SRT dosyasina cikarir.

    Gorsel tabanli akislar (PGS/VobSub) metne cevrilemedigi icin net hata
    verir; bos/bozuk bir SRT uretmez.
    """
    streams = {stream["index"]: stream for stream in subtitle_streams(ffprobe, source)}
    stream = streams.get(int(stream_index))
    if stream is None:
        raise FFmpegError(
            f"Altyazı akışı bulunamadı (indeks {stream_index}). "
            f"Mevcut akışlar: {sorted(streams) or 'yok'}"
        )
    if not stream["text_based"]:
        codec = stream["codec"] or "bilinmeyen"
        raise FFmpegError(
            f"Bu altyazı akışı görüntü tabanlı ({codec}) ve metne çevrilemiyor.\n"
            "Metin tabanlı bir akış seçin (SRT/ASS/mov_text) veya altyazıyı "
            "videodan bağımsız bir .srt dosyası olarak edinin."
        )

    destination = Path(dest_srt)
    destination.parent.mkdir(parents=True, exist_ok=True)
    duration = media_duration(ffprobe, source)
    cmd = [
        ffmpeg,
        "-i",
        str(source),
        "-map",
        f"0:{int(stream_index)}",
        "-c:s",
        "srt",
        str(destination),
    ]
    _run_ffmpeg(cmd, duration=duration, cancel_event=cancel_event)
    if not destination.exists() or destination.stat().st_size == 0:
        raise FFmpegError(
            "Altyazı akışı çıkarılamadı: çıktı boş. Akış bozuk olabilir."
        )
    return destination


def media_duration(ffprobe: str, path: str | Path) -> float:
    info = probe_media(ffprobe, path)
    duration = 0.0
    try:
        duration = float(info.get("format", {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        for stream in info.get("streams", []):
            try:
                duration = max(duration, float(stream.get("duration") or 0.0))
            except (TypeError, ValueError):
                continue
    return duration


def _parse_fraction(value: str | None) -> float:
    """'30000/1001' -> 29.97"""
    if not value:
        return 0.0
    if "/" not in value:
        try:
            return float(value)
        except ValueError:
            return 0.0
    try:
        numerator, denominator = value.split("/", 1)
        denominator_value = float(denominator)
        if denominator_value == 0:
            return 0.0
        return float(numerator) / denominator_value
    except (ValueError, TypeError):
        return 0.0


def media_size(ffprobe: str, path: str | Path) -> tuple[int, int, float]:
    """(genislik, yukseklik, fps) dondurur. Video akisi yoksa (0, 0, 0)."""
    try:
        info = probe_media(ffprobe, path)
    except FFmpegError:
        return 0, 0, 0.0

    for stream in info.get("streams", []):
        if stream.get("codec_type") != "video":
            continue
        if stream.get("disposition", {}).get("attached_pic"):
            continue
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        fps = _parse_fraction(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
        return width, height, fps
    return 0, 0, 0.0


# --------------------------------------------------------------------------
# FFmpeg calistirma + ilerleme
# --------------------------------------------------------------------------

def _terminate(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
    except OSError:
        return
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass


def _run_ffmpeg(
    cmd: list[str],
    duration: float = 0.0,
    progress_cb: ProgressCB = None,
    cancel_event: threading.Event | None = None,
    cwd: str | None = None,
) -> None:
    """FFmpeg'i calistirir, -progress ciktisini okuyup yuzde uretir."""
    full_cmd = [cmd[0], "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats"] + cmd[1:]
    try:
        proc = subprocess.Popen(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        raise FFmpegError(f"FFmpeg başlatılamadı: {exc}") from exc

    stderr_lines: list[str] = []

    def _drain(stream) -> None:
        try:
            for line in stream:
                stderr_lines.append(line.rstrip())
                if len(stderr_lines) > 500:
                    del stderr_lines[:200]
        except Exception:
            pass

    reader = threading.Thread(target=_drain, args=(proc.stderr,), daemon=True)
    reader.start()

    cancelled = False
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            line = raw.strip()
            if not line or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key in ("out_time_us", "out_time_ms") and duration > 0:
                try:
                    micros = int(value)
                except ValueError:
                    continue
                fraction = (micros / 1_000_000.0) / duration
                if progress_cb:
                    progress_cb(max(0.0, min(1.0, fraction)))
    finally:
        if cancelled:
            _terminate(proc)
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            _terminate(proc)
        reader.join(timeout=5)
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except Exception:
                pass

    if cancelled or (cancel_event is not None and cancel_event.is_set()):
        raise CancelledError("İşlem iptal edildi.")
    if proc.returncode != 0:
        tail = "\n".join(stderr_lines[-25:]).strip()
        raise FFmpegError(
            f"FFmpeg hata kodu {proc.returncode} döndürdü.\n{tail}"
        )


def extract_audio(
    ffmpeg: str,
    source: str | Path,
    dest_wav: str | Path,
    duration: float,
    progress_cb: ProgressCB = None,
    cancel_event: threading.Event | None = None,
    audio_index: int = 0,
) -> Path:
    """Sesi 16 kHz mono PCM WAV olarak cikarir.

    `audio_index` videodaki kacinci ses kanalinin okunacagi (0 tabanli).
    Varsayilan 0 (ilk kanal). Gecersiz indeks net hata verir; ffmpeg'in
    ham "stream map" mesaji kullaniciya gosterilmez.
    """
    dest = Path(dest_wav)
    dest.parent.mkdir(parents=True, exist_ok=True)
    track = max(0, int(audio_index))
    cmd = [
        ffmpeg,
        "-i",
        str(source),
        "-vn",
        "-map",
        f"0:a:{track}",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(dest),
    ]
    try:
        _run_ffmpeg(cmd, duration, progress_cb, cancel_event)
    except FFmpegError as exc:
        text = str(exc).lower()
        if "does not contain any stream" in text or "stream map" in text:
            if track > 0:
                raise FFmpegError(
                    f"Seçilen ses kanalı bulunamadı (#{track + 1}).\n"
                    "Videoda bu numarada bir ses kanalı yok; başka bir kanal seçin."
                ) from exc
            raise FFmpegError(
                "Bu videoda ses kanalı bulunamadı. Altyazı üretmek için ses "
                "içeren bir video seçin."
            ) from exc
        raise
    if not dest.exists() or dest.stat().st_size == 0:
        raise FFmpegError("Ses çıkarılamadı: geçici WAV dosyası oluşmadı.")
    return dest


# --------------------------------------------------------------------------
# subtitles filtresi icin yol kacisi
# --------------------------------------------------------------------------

def escape_filter_path(path: str | Path) -> str:
    """FFmpeg filtergraph icinde guvenli yol uretir.

    - Ters slash'lar ileri slash'a cevrilir.
    - ':' karakteri '\\:' olarak kacislanir (C:\\ gibi surucu harfleri).
    - ',', ';', '[', ']' ve tek tirnak kacislanir.
    """
    text = str(path).replace("\\", "/")
    out: list[str] = []
    for char in text:
        if char == ":":
            out.append("\\:")
        elif char == "'":
            out.append("\\'")
        elif char in "\\,;[]":
            out.append("\\" + char)
        else:
            out.append(char)
    return "".join(out)


def build_subtitles_filter(
    srt_path: str | Path,
    style: SubtitleStyle,
    video_width: int = 0,
    video_height: int = 0,
) -> str:
    escaped = escape_filter_path(srt_path)
    force = style.force_style(video_width, video_height)
    return f"subtitles=filename='{escaped}':force_style='{force}'"


def h264_level_for(width: int, height: int, fps: float = 30.0, refs: int = 5) -> str:
    """Cozunurluk, kare hizi ve referans kare sayisina gore H.264 level'i.

    Kaynak 1080x1918@30 iken level 4.0 sinirda kalir (8160 makroblok/kare,
    4.0'in ust siniri 8192). Ayrica ref=5 icin DPB (karar belleği) yeterli
    degildir; 4.0 ile 6 kare saklanamaz. Bu yuzden level 5.0 gerekir.
    Yanlis (dusuk) level bazi cozuculerde yirtilma/bloklanmaya yol acar.
    """
    macroblocks = ((int(width) + 15) // 16) * ((int(height) + 15) // 16)
    fps = float(fps or 30.0)
    needed_dpb_frames = max(2, int(refs) + 2)

    # (level, max_makroblok/kare, max_makroblok/sn, DPB makroblok)
    table = [
        ("4.0", 8192, 245760, 32768),
        ("4.1", 8192, 245760, 32768),
        ("4.2", 8704, 522240, 34816),
        ("5.0", 22080, 589824, 86016),
        ("5.1", 36864, 983040, 184320),
        ("5.2", 36864, 2073600, 184320),
        ("6.0", 139264, 4177920, 696320),
    ]
    per_second = macroblocks * fps
    for level, max_frame, max_per_second, dpb in table:
        if macroblocks > max_frame or per_second > max_per_second:
            continue
        if macroblocks * needed_dpb_frames > dpb:
            continue
        return level
    return "6.1"


# Burn-in kalite ayarlari.
#
# Neden bu degerler: kaynak video zaten H.264 ile sikistirilmis. crf 20 +
# preset medium + ref=3 ile yeniden kodlamak ikinci nesil kayip yaratir ve
# karanlik/bulanik bolgelerde 8x8 bloklanma olusur (olculdu: bloklanma
# farki +0.209). Bu ayarlarla fark +0.038'e indi (%82 iyilesti):
#   aq-mode=3  -> karanlik sahnelere daha fazla bit ayirir
#   deblock=1,1 -> bloklanma artefaktlarini cozer (alpha/beta guclu)
#   ref=5      -> daha iyi tahmin, daha az artik
#   psy-rd     -> ince dokuyu korur (subjective kalite)
BURN_IN_PRESET = "slow"
BURN_IN_CRF = 18
BURN_IN_X264_PARAMS = "ref=5:aq-mode=3:deblock=1,1:psy-rd=1.0,0.15"


def burn_in_subtitles(
    ffmpeg: str,
    video: str | Path,
    srt_path: str | Path,
    output: str | Path,
    style: SubtitleStyle,
    duration: float,
    progress_cb: ProgressCB = None,
    cancel_event: threading.Event | None = None,
    video_width: int = 0,
    video_height: int = 0,
    fps: float = 0.0,
    crf: int = BURN_IN_CRF,
    preset: str = BURN_IN_PRESET,
) -> Path:
    """Altyaziyi videoya yakar (libx264, ses kopyalanir).

    video_width/height verilirse altyazi olcegi ve H.264 level'i video
    boyutuna gore secilir. Verilmezse ffprobe ile olculur.
    """
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    srt = Path(srt_path).resolve()
    video_path = Path(video).resolve()

    width = int(video_width or 0)
    height = int(video_height or 0)
    frame_rate = float(fps or 0.0)
    if not (width and height):
        try:
            info = probe_media(_find_ffprobe(ffmpeg) or "ffprobe", video_path)
            stream = next(
                (s for s in info.get("streams", []) if s.get("codec_type") == "video"),
                None,
            )
            if stream:
                width = int(stream.get("width") or 0)
                height = int(stream.get("height") or 0)
                if not frame_rate:
                    frame_rate = _parse_fraction(
                        stream.get("avg_frame_rate") or stream.get("r_frame_rate")
                    )
        except Exception:
            width = height = 0

    level = h264_level_for(width, height, frame_rate or 30.0) if (width and height) else ""

    def _cmd(vf_value: str) -> list[str]:
        base = [
            ffmpeg,
            "-i",
            str(video_path),
            "-vf",
            vf_value,
            # Video: yalnızca ilk görüntü akışı yeniden kodlanır.
            "-map",
            "0:v:0",
            # Ses: TÜM kanallar korunur (çoklu dil/parça kaybolmasın).
            "-map",
            "0:a?",
            # Altyazı/veri akışları da kopyalanır (varsa).
            "-map",
            "0:s?",
            "-map_metadata",
            "0",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(int(crf)),
            "-x264-params",
            BURN_IN_X264_PARAMS,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
        ]
        if level:
            base += ["-level", level]
        if out.suffix.lower() in (".mp4", ".m4v"):
            # MP4 altyazı taşıyıcısı mov_text olmalı; yoksa kopyalama hata verir.
            base += ["-c:s", "mov_text"]
        else:
            base += ["-c:s", "copy"]
        if out.suffix.lower() in (".mp4", ".m4v"):
            base += ["-movflags", "+faststart"]
        base.append(str(out))
        return base

    try:
        _run_ffmpeg(
            _cmd(build_subtitles_filter(srt, style, width, height)),
            duration,
            progress_cb,
            cancel_event,
        )
    except CancelledError:
        raise
    except FFmpegError as exc:
        text = str(exc).lower()
        filter_problem = any(
            key in text
            for key in ("subtitle", "filter", "unable to parse", "no option name", "invalid argument")
        )
        if not filter_problem:
            raise
        # Ikinci deneme: goreli dosya adi + calisma dizini. Windows'ta
        # surucu harfi ve bosluk sorunlarina karsi kesin cozum.
        _run_ffmpeg(
            _cmd(
                f"subtitles=filename={srt.name}:"
                f"force_style='{style.force_style(width, height)}'"
            ),
            duration,
            progress_cb,
            cancel_event,
            cwd=str(srt.parent),
        )
    return out


def add_soft_subtitles(
    ffmpeg: str,
    video: str | Path,
    srt_path: str | Path,
    output: str | Path,
    language_tag: str = "tur",
    duration: float = 0.0,
    progress_cb: ProgressCB = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Altyaziyi yeniden kodlamadan (soft) videoya ekler."""
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    is_mp4 = out.suffix.lower() in (".mp4", ".m4v", ".mov")
    codec = "mov_text" if is_mp4 else "srt"
    cmd = [
        ffmpeg,
        "-i",
        str(video),
        "-i",
        str(srt_path),
        "-map",
        "0",
        "-map",
        "1:0",
        "-c",
        "copy",
        "-c:s",
        codec,
        "-metadata:s:s:0",
        f"language={language_tag}",
        "-disposition:s:0",
        "default",
    ]
    if is_mp4:
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(out))
    _run_ffmpeg(cmd, duration, progress_cb, cancel_event)
    if not out.exists() or out.stat().st_size == 0:
        raise FFmpegError("Altyazı videoya eklenemedi (çıktı dosyası oluşmadı).")
    return out


# --------------------------------------------------------------------------
# Disk alani
# --------------------------------------------------------------------------

def ensure_free_space(directory: str | Path, required_bytes: int) -> None:
    """Yetersiz disk alaninda anlasilir hata firlatir."""
    target = Path(directory)
    try:
        usage = shutil.disk_usage(str(target))
    except OSError:
        return
    if usage.free < required_bytes:
        need_gb = required_bytes / (1024 ** 3)
        free_gb = usage.free / (1024 ** 3)
        message = (
            "Disk alanı yetersiz.\n"
            f"Gereken: yaklaşık {need_gb:.2f} GB\n"
            f"Boş alan: {free_gb:.2f} GB\n"
            f"Konum: {target}"
        )
        error = OSError(errno.ENOSPC, message)
        raise error
