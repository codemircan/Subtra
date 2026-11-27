"""Subtra — giriş noktası.

Çalıştırma:
    py main.py          (konsollu, hata mesajları görünür)
    pyw main.py         (konsolsuz, önerilen)

DPI hakkında not:
    Qt 6, Windows'ta varsayılan olarak `PER_MONITOR_AWARE_V2` DPI bağlamını
    kendisi ayarlar (en iyi seçenek: çoklu monitörde net metin). Uygulama
    ayrıca `SetProcessDpiAwareness()` çağırırsa Qt bunu "zaten ayarlanmış"
    görüp uyarı basar ve bizim ayarımız daha zayıf olduğu için bulanıklık
    oluşur. Bu yüzden DPI ayarına hiç dokunmuyoruz.
"""

from __future__ import annotations

import ctypes
import os
import sys
import traceback


def _has_console() -> bool:
    """Gerçek bir konsol penceresi var mı? (pyw ile çalışırken yok)"""
    stream = sys.stderr
    if stream is None:
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def _show_error_box(title: str, message: str) -> None:
    """Konsol yokken hatayı MessageBox ile gösterir."""
    if os.name != "nt":
        return
    try:
        MB_ICONERROR = 0x10
        ctypes.windll.user32.MessageBoxW(None, message, title, MB_ICONERROR)
    except (AttributeError, OSError):
        pass


def _check_dependencies() -> list[str]:
    missing: list[str] = []
    for module, package in (
        ("PySide6", "PySide6"),
        ("faster_whisper", "faster-whisper"),
        ("ctranslate2", "ctranslate2"),
        ("requests", "requests"),
        ("tokenizers", "tokenizers"),
    ):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    return missing


def _fatal(message: str) -> int:
    """Konsol varsa stderr'e, yoksa MessageBox'a yazar; her durumda loglar."""
    try:
        if sys.stderr is not None:
            sys.stderr.write(message + "\n")
    except Exception:
        pass

    try:
        import logging_setup

        logging_setup.get_logger("fatal").error(message)
    except Exception:
        pass

    if not _has_console():
        _show_error_box("Subtra", message.strip())
    return 1


def _self_check() -> int:
    """`Subtra.exe --self-check`: frozen ortami dogrular, pencere acmaz.

    Destek icin: kullanici 'uygulama acilmiyor' dediginde bu cikti tek
    basina sebebi gosterir (eksik DLL, gomulmemis modul, yazilamayan klasor).

    `console=False` exe'de stdout yoktur; rapor her zaman
    `%LOCALAPPDATA%\\Subtra\\selfcheck.txt` dosyasina da yazilir ve konsol
    yoksa MessageBox ile gosterilir.
    """
    import io
    import json
    from contextlib import redirect_stdout

    from PySide6.QtGui import QGuiApplication

    lines: list[str] = []

    def emit(text: str = "") -> None:
        lines.append(text)
        try:
            print(text, flush=True)
        except Exception:  # noqa: BLE001
            pass

    emit(f"Subtra self-check (surum {_version()})")
    emit(f"  frozen      : {getattr(sys, 'frozen', False)}")
    emit(f"  executable  : {sys.executable}")

    result: dict[str, object] = {"version": _version()}

    # 1) Gomulu moduller
    modules: dict[str, bool] = {}
    for name in (
        "PySide6",
        "faster_whisper",
        "ctranslate2",
        "tokenizers",
        "sentencepiece",
        "requests",
        "psutil",
        "numpy",
        "glossary",
        "subtitle_preview",
        "transcript_cache",
    ):
        try:
            __import__(name)
            modules[name] = True
        except Exception as exc:  # noqa: BLE001
            modules[name] = f"{type(exc).__name__}: {exc}"
    result["modules"] = modules
    emit("  moduller    :")
    for name, state in modules.items():
        emit(f"    {'OK  ' if state is True else 'FAIL'} {name}"
             + ("" if state is True else f"  ({state})"))

    # 2) Yazilabilir veri klasoru
    data_dir = ""
    try:
        import app_paths

        data_dir = str(app_paths.data_dir())
        probe = app_paths.data_dir() / "_selfcheck.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        result["data_dir"] = data_dir
        emit(f"  veri klasoru: OK  ({data_dir})")
    except Exception as exc:  # noqa: BLE001
        result["data_dir"] = f"{type(exc).__name__}: {exc}"
        emit(f"  veri klasoru: FAIL  ({exc})")

    # 3) Simge (assets gomuldu mu)
    icon = _app_icon()
    if icon is None and QGuiApplication.instance() is None:
        QGuiApplication(sys.argv[:1])
        icon = _app_icon()
    result["icon"] = bool(icon is not None and not icon.isNull())
    emit(f"  simge       : {'OK' if result['icon'] else 'FAIL'}")

    # 4) CTranslate2 calisma zamani (VC++ redist / DLL)
    try:
        import translator

        error = translator.check_ctranslate2_runtime()
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    result["ctranslate2_runtime"] = error or "OK"
    emit(f"  ctranslate2 : {'OK' if not error else 'FAIL'}  ({error or 'calisiyor'})")

    # 5) FFmpeg
    try:
        import ffmpeg_bootstrap

        location = ffmpeg_bootstrap.find_existing()
        result["ffmpeg"] = location.ffmpeg if location else None
        emit(f"  ffmpeg      : {'OK  ' + location.ffmpeg if location else 'YOK (ilk kullanimda indirilir)'}")
    except Exception as exc:  # noqa: BLE001
        result["ffmpeg"] = f"{type(exc).__name__}: {exc}"
        emit(f"  ffmpeg      : FAIL  ({exc})")

    # 6) Modeller
    try:
        import app_paths as _paths
        from transcriber import cached_whisper_models
        from translator import is_nllb_cached

        models_dir = _paths.resolve_models_dir()
        whisper = sorted(cached_whisper_models(models_dir))
        result["whisper_models"] = whisper
        result["nllb"] = is_nllb_cached(models_dir)
        emit(f"  whisper     : {', '.join(whisper) if whisper else 'yok (indirilecek)'}")
        emit(f"  nllb        : {'var' if result['nllb'] else 'yok (indirilecek)'}")
    except Exception as exc:  # noqa: BLE001
        result["models"] = f"{type(exc).__name__}: {exc}"
        emit(f"  modeller    : FAIL  ({exc})")

    failed = [name for name, state in modules.items() if state is not True]
    if not result.get("icon"):
        failed.append("icon")
    if str(result.get("data_dir", "")).startswith(
        ("OSError", "PermissionError", "FileNotFoundError")
    ):
        failed.append("data_dir")
    if result.get("ctranslate2_runtime") != "OK":
        failed.append("ctranslate2")
    ok = not failed
    emit("")
    emit("SONUC: " + ("GECTI" if ok else f"BASARISIZ -> {failed}"))
    emit(json.dumps(result, ensure_ascii=False, indent=1))

    report = lines[:]
    if data_dir:
        try:
            from pathlib import Path

            target = Path(data_dir) / "selfcheck.txt"
            target.write_text("\n".join(report) + "\n", encoding="utf-8")
            emit(f"rapor        : {target}")
        except Exception:  # noqa: BLE001
            pass

    # MessageBox YALNIZCA gercek bir konsol yoksa ve bu bir frozen exe ise.
    # Boru/yonlendirme altinda da stdout yoktur; orada kutu acmak testi
    # kilitler. Bu yuzden karar `_has_console()` yerine frozen olmaya bagli.
    if getattr(sys, "frozen", False) and sys.stdout is None:
        _show_error_box(
            "Subtra self-check: " + ("GECTI" if ok else "BASARISIZ"),
            "\n".join(report)[:2000],
        )
    return 0 if ok else 1


def _ct2_probe() -> int:
    """CTranslate2 calisma zamani probu (ayri surecte calisir).

    Erisim ihlali olursa surec coker; cagiran taraf bunu cikis koduyla
    gorur. Basarida 0, aksi halde 1 dondurur. Konsol olmadigi icin cikti
    beklenmez.
    """
    try:
        import ctranslate2

        try:
            ctranslate2.Translator("__yok_boyle_bir_model__", device="cpu")
        except Exception:  # noqa: BLE001  (model yok: beklenen)
            pass
    except Exception:  # noqa: BLE001
        return 1
    return 0


def _smoke_test(argv: list[str]) -> int:
    """`Subtra.exe --smoke-test <video>`: uctan uca kucuk bir is calistirir.

    Paketlenmis exe'nin gercekten altyazi urettigini kanitlar: Whisper
    modelini yukler, transkripsiyon + (gerekirse) ceviri yapar, SRT yazar.
    Pencere acmaz. Rapor `%LOCALAPPDATA%\\Subtra\\smoke.txt` dosyasina yazilir.
    """
    import json
    import time
    from pathlib import Path

    lines: list[str] = []

    def emit(text: str = "") -> None:
        lines.append(text)
        try:
            print(text, flush=True)
        except Exception:  # noqa: BLE001
            pass

    video = ""
    target = "tr"
    model = "tiny"
    rest = [item for item in argv[1:] if item != "--smoke-test"]
    if rest:
        video = rest[0]
    if len(rest) > 1:
        target = rest[1]
    if len(rest) > 2:
        model = rest[2]

    emit(f"Subtra smoke-test (surum {_version()}, frozen={bool(getattr(sys, 'frozen', False))})")
    emit(f"  video : {video}")
    emit(f"  hedef : {target}   model: {model}")

    result: dict[str, object] = {"video": video, "target": target, "model": model}
    ok = False
    started = time.time()
    try:
        import app_paths
        from worker import JobRunner, JobSettings, ModelCache

        models_dir = app_paths.resolve_models_dir()
        emit(f"  models: {models_dir}")

        settings = JobSettings(
            input_path=video,
            model_size=model,
            target_lang=target,
            output_mode="srt",
            models_dir=str(models_dir),
            skip_preview=True,
            use_transcript_cache=False,
            word_timestamps=True,
        )

        def log(message: str) -> None:
            emit(f"    {message}")

        from worker import JobHooks

        job = JobRunner(settings, ModelCache(models_dir), JobHooks(log=log))
        video_out, srt_out, summary = job.run()
        srt_path = Path(srt_out)
        text = srt_path.read_text(encoding="utf-8") if srt_path.exists() else ""
        result.update(
            {
                "srt": srt_out,
                "cue_count": text.count("-->"),
                "bytes": len(text.encode("utf-8")),
                "seconds": round(time.time() - started, 1),
            }
        )
        emit(f"  SRT   : {srt_out}")
        emit(f"  satir : {result['cue_count']}  ({result['bytes']} bayt)")
        emit("  ozet  : " + summary.replace("\n", " | "))
        ok = bool(result["cue_count"]) and result["bytes"] > 50
    except Exception as exc:  # noqa: BLE001
        import traceback

        result["error"] = f"{type(exc).__name__}: {exc}"
        emit(f"  HATA  : {type(exc).__name__}: {exc}")
        for line in traceback.format_exc().splitlines()[-6:]:
            emit(f"    {line}")

    emit("")
    emit("SONUC: " + ("GECTI" if ok else "BASARISIZ"))
    emit(json.dumps(result, ensure_ascii=False, indent=1))

    try:
        from pathlib import Path as _Path

        import app_paths as _paths

        report = _paths.data_dir() / "smoke.txt"
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        emit(f"rapor : {report}")
    except Exception:  # noqa: BLE001
        pass
    return 0 if ok else 1


def main() -> int:
    if "--ct2-probe" in sys.argv:
        return _ct2_probe()
    if "--self-check" in sys.argv:
        return _self_check()
    if "--smoke-test" in sys.argv:
        return _smoke_test(sys.argv)

    missing = _check_dependencies()
    if missing:
        return _fatal(
            "Eksik paket(ler): " + ", ".join(missing) + "\n"
            "Kurulum: py -m pip install -r requirements.txt\n"
        )

    import logging_setup

    logger = logging_setup.setup_logging()
    logger.info("Uygulama başlıyor (sürüm %s)", _version())

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QMessageBox

    from gui import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Subtra")
    app.setApplicationDisplayName("Subtra")
    app.setOrganizationName("Subtra")
    app.setAttribute(Qt.AA_DontUseNativeMenuBar, False)
    app.setFont(QFont("Segoe UI", 9))

    icon = _app_icon()
    if icon is not None:
        app.setWindowIcon(icon)

    try:
        window = MainWindow()
        window.show()
    except Exception:  # noqa: BLE001
        detail = traceback.format_exc()
        logger.exception("Arayüz başlatılamadı")
        QMessageBox.critical(
            None,
            "Başlatma hatası",
            "Arayüz başlatılamadı:\n\n" + detail,
        )
        return 1

    exit_code = app.exec()
    logger.info("Uygulama kapandı (kod %s)", exit_code)
    return exit_code


def _version() -> str:
    try:
        import error_report

        return error_report.app_version()
    except Exception:
        return "?"


def _app_icon():
    """assets/app.ico varsa QIcon dondurur (yoksa None).

    QIcon olusturmak icin QGuiApplication gerekir; --self-check gibi pencere
    acmayan yollarda uygulama henuz yoksa simge None doner (sorun degil).
    """
    try:
        from PySide6.QtGui import QGuiApplication, QIcon

        import app_paths

        if QGuiApplication.instance() is None:
            return None
        for root in (app_paths.bundled_root(), app_paths.app_root()):
            candidate = root / "assets" / "app.ico"
            if candidate.exists():
                return QIcon(str(candidate))
    except Exception:  # noqa: BLE001
        pass
    return None


if __name__ == "__main__":
    sys.exit(main())
