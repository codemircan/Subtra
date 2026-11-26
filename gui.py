"""PySide6 arayuzu: tek video, kuyruk, SRT cevirme ve ayarlar sekmeleri."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QButtonGroup,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import app_paths
import error_report
import ffmpeg_bootstrap
import ffmpeg_utils
import logging_setup
from ffmpeg_utils import FFMPEG_DOWNLOAD_URL, SubtitleStyle
from hardware import hardware_info, recommended_model_size
from languages import (
    TARGET_LANGUAGES,
    WHISPER_LANGUAGE_NAMES_TR,
    language_label,
    target_options,
)
from translator import VCREDIST_URL, check_ctranslate2_runtime
from worker import (
    SUPPORTED_EXTENSIONS,
    BatchWorker,
    JobSettings,
    ModelCache,
    VideoWorker,
)

APP_TITLE = "Subtra — Otomatik Altyazı ve Çeviri"
VIDEO_FILTER = "Video dosyaları (*.mp4 *.mkv *.avi *.mov *.webm);;Tüm dosyalar (*.*)"
SRT_FILTER = "Altyazı dosyaları (*.srt);;Tüm dosyalar (*.*)"

MODEL_HINTS = {
    "tiny": "en hızlı, düşük kalite (~75 MB)",
    "base": "hızlı, temel kalite (~145 MB)",
    "small": "dengeli (önerilen, ~484 MB)",
    "medium": "yüksek kalite, CPU'da yavaş (~1.5 GB)",
}

QUEUE_COLUMNS = ("Dosya", "Hedef dil", "Durum", "Çıktı")


# --------------------------------------------------------------------------
# Yardimci widget'lar
# --------------------------------------------------------------------------

class DropArea(QFrame):
    """Sürükle-bırak alanı (tek veya çoklu dosya)."""

    files_dropped = Signal(list)
    clicked = Signal()

    def __init__(self, hint: str, extensions: set[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._extensions = extensions
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("dropArea")
        self.setMinimumHeight(76)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "#dropArea { border: 2px dashed #6b7280; border-radius: 8px; "
            "background: rgba(107,114,128,0.08); }"
            "#dropArea[dragActive=\"true\"] { border-color: #2563eb; "
            "background: rgba(37,99,235,0.12); }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        self._label = QLabel(hint)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

    def _set_drag(self, active: bool) -> None:
        self.setProperty("dragActive", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def _local_files(self, event) -> list[str]:
        if not event.mimeData().hasUrls():
            return []
        found: list[str] = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                if Path(path).suffix.lower() in self._extensions:
                    found.append(path)
        return found

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._local_files(event):
            event.acceptProposedAction()
            self._set_drag(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_drag(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_drag(False)
        files = self._local_files(event)
        if files:
            self.files_dropped.emit(files)
            event.acceptProposedAction()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def set_text(self, text: str) -> None:
        self._label.setText(text)


def _make_hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("color: #6b7280;")
    label.setWordWrap(True)
    return label


class FFmpegDownloadWorker(QThread):
    """FFmpeg'i arka planda indirir (arayuz donmaz)."""

    progress = Signal(int, str)
    log = Signal(str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            location = ffmpeg_bootstrap.download_ffmpeg(
                progress_cb=lambda fraction, label: self.progress.emit(
                    int(max(0.0, min(1.0, fraction)) * 100), label
                ),
                log_cb=lambda message: self.log.emit(message),
                cancel_event=self._cancel,
            )
            self.finished_ok.emit(location.ffmpeg)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


# --------------------------------------------------------------------------
# Ana pencere
# --------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(940, 860)

        self._settings = QSettings("Subtra", "Subtra")
        self._ffmpeg_path: str = self._settings.value("ffmpeg_path", "", str) or ""
        self._color = self._settings.value("subtitle_color", "#FFFFFF", str) or "#FFFFFF"

        self._worker: VideoWorker | None = None
        self._batch: BatchWorker | None = None
        self._model_cache = ModelCache(app_paths.resolve_models_dir(), log_cb=self._log)
        self._last_video = ""
        self._last_srt = ""
        self._engine_ok: bool | None = None
        self._last_error = ""
        self._busy = False
        self._ffmpeg_download: FFmpegDownloadWorker | None = None

        self._build_ui()
        self._load_settings()
        self._refresh_ffmpeg_status(silent=True)
        self._refresh_hardware()
        self._refresh_cache_table()

        self._log_timer = self.startTimer(250)

    # ------------------------------------------------------------------
    # Arayuz kurulumu
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QLabel("Video → Dil Tespiti → Altyazı → Çeviri")
        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        title.setFont(font)
        root.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_single_tab(), "Video")
        self.tabs.addTab(self._build_queue_tab(), "Kuyruk")
        self.tabs.addTab(self._build_srt_tab(), "SRT Çevir")
        self.tabs.addTab(self._build_settings_tab(), "Ayarlar")
        root.addWidget(self.tabs, 3)

        # Durum -------------------------------------------------------------
        status_box = QGroupBox("Durum")
        status_layout = QVBoxLayout(status_box)
        status_layout.setContentsMargins(8, 6, 8, 6)
        self.stage_label = QLabel("Hazır")
        self.stage_label.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(self.stage_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        status_layout.addWidget(self.progress)

        self.detected_label = QLabel("Tespit edilen dil: —")
        status_layout.addWidget(self.detected_label)
        root.addWidget(status_box)

        # Log ---------------------------------------------------------------
        log_box = QGroupBox("Log")
        log_layout = QVBoxLayout(log_box)
        log_layout.setContentsMargins(8, 6, 8, 6)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(4000)
        self.log_view.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")
        self.log_view.setMinimumHeight(90)
        log_layout.addWidget(self.log_view)

        log_row = QHBoxLayout()
        self.copy_report_button = QPushButton("Hata Raporunu Kopyala")
        self.copy_report_button.clicked.connect(self._copy_report)
        self.save_report_button = QPushButton("Raporu Kaydet…")
        self.save_report_button.clicked.connect(self._save_report)
        self.open_logs_button = QPushButton("Log Klasörünü Aç")
        self.open_logs_button.clicked.connect(self._open_logs)
        self.open_output_button = QPushButton("Çıktı Klasörünü Aç")
        self.open_output_button.setEnabled(False)
        self.open_output_button.clicked.connect(self._open_output_folder)
        log_row.addWidget(self.copy_report_button)
        log_row.addWidget(self.save_report_button)
        log_row.addWidget(self.open_logs_button)
        log_row.addStretch(1)
        log_row.addWidget(self.open_output_button)
        log_layout.addLayout(log_row)
        root.addWidget(log_box, 2)

    # -- sekme 1: tek video ------------------------------------------------
    def _build_single_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.single_drop = DropArea(
            "Videoyu buraya sürükleyip bırakın\nveya aşağıdan seçin",
            SUPPORTED_EXTENSIONS,
        )
        self.single_drop.files_dropped.connect(lambda files: self._set_single_input(files[0]))
        self.single_drop.clicked.connect(self._choose_single_file)
        layout.addWidget(self.single_drop)

        row = QHBoxLayout()
        choose = QPushButton("Dosya Seç…")
        choose.clicked.connect(self._choose_single_file)
        self.single_file_label = _make_hint("Seçili dosya yok")
        self.single_file_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(choose)
        row.addWidget(self.single_file_label, 1)
        layout.addLayout(row)

        options = QGroupBox("İş seçenekleri")
        options_layout = QVBoxLayout(options)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Whisper modeli:"))
        self.model_combo = QComboBox()
        for key in ("tiny", "base", "small", "medium"):
            self.model_combo.addItem(key, key)
        self.model_combo.currentIndexChanged.connect(self._update_model_hint)
        model_row.addWidget(self.model_combo)
        model_row.addStretch(1)
        options_layout.addLayout(model_row)
        self.model_hint = _make_hint("")
        options_layout.addWidget(self.model_hint)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Hedef dil:"))
        self.target_combo = QComboBox()
        for code, name in target_options():
            self.target_combo.addItem(name, code)
        target_row.addWidget(self.target_combo)
        target_row.addWidget(_make_hint("Videodaki dil otomatik tespit edilir."), 1)
        options_layout.addLayout(target_row)

        options_layout.addWidget(QLabel("Çıktı:"))
        self.mode_group = QButtonGroup(self)
        self.radio_burn = QRadioButton("Altyazıyı videoya yak (burn-in, yeniden kodlar)")
        self.radio_soft = QRadioButton("Yumuşak altyazı olarak ekle (yeniden kodlamaz)")
        self.radio_srt = QRadioButton("Sadece .srt altyazı dosyası")
        for index, radio in enumerate((self.radio_burn, self.radio_soft, self.radio_srt)):
            self.mode_group.addButton(radio, index)
            options_layout.addWidget(radio)
        self.mode_group.idToggled.connect(self._update_style_enabled)

        style_row = QHBoxLayout()
        self.style_box = QGroupBox("Altyazı stili (burn-in)")
        inner = QHBoxLayout(self.style_box)
        inner.addWidget(QLabel("Boyut:"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(8, 60)
        self.size_spin.setValue(18)
        self.size_spin.setSuffix(" pt")
        inner.addWidget(self.size_spin)
        inner.addSpacing(8)
        inner.addWidget(QLabel("Renk:"))
        self.color_button = QPushButton("   ")
        self.color_button.setFixedWidth(52)
        self.color_button.clicked.connect(self._pick_color)
        inner.addWidget(self.color_button)
        inner.addSpacing(8)
        inner.addWidget(QLabel("Konum:"))
        self.position_combo = QComboBox()
        self.position_combo.addItem("Alt", "bottom")
        self.position_combo.addItem("Orta", "middle")
        self.position_combo.addItem("Üst", "top")
        inner.addWidget(self.position_combo)
        inner.addStretch(1)
        style_row.addWidget(self.style_box, 1)
        options_layout.addLayout(style_row)
        layout.addWidget(options)

        actions = QHBoxLayout()
        self.start_button = QPushButton("Başlat")
        self.start_button.setMinimumHeight(38)
        self.start_button.clicked.connect(self._start_single)
        self.cancel_button = QPushButton("İptal")
        self.cancel_button.setMinimumHeight(38)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_current)
        actions.addWidget(self.start_button, 2)
        actions.addWidget(self.cancel_button, 1)
        layout.addLayout(actions)
        layout.addStretch(1)
        return page

    # -- sekme 2: kuyruk ---------------------------------------------------
    def _build_queue_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.queue_drop = DropArea(
            "Birden fazla videoyu buraya bırakın\nveya aşağıdan ekleyin",
            SUPPORTED_EXTENSIONS,
        )
        self.queue_drop.files_dropped.connect(self._add_to_queue)
        self.queue_drop.clicked.connect(self._choose_queue_files)
        layout.addWidget(self.queue_drop)

        row = QHBoxLayout()
        add_button = QPushButton("Dosya Ekle…")
        add_button.clicked.connect(self._choose_queue_files)
        remove_button = QPushButton("Seçileni Kaldır")
        remove_button.clicked.connect(self._remove_selected_queue)
        clear_button = QPushButton("Listeyi Temizle")
        clear_button.clicked.connect(self._clear_queue)
        row.addWidget(add_button)
        row.addWidget(remove_button)
        row.addWidget(clear_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.queue_table = QTableWidget(0, len(QUEUE_COLUMNS))
        self.queue_table.setHorizontalHeaderLabels(list(QUEUE_COLUMNS))
        self.queue_table.verticalHeader().setVisible(False)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        header = self.queue_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.queue_table.setColumnWidth(1, 110)
        self.queue_table.setColumnWidth(2, 100)
        layout.addWidget(self.queue_table, 1)

        # Dosya başına hedef dil: satır seçilip buradan değiştirilir.
        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Seçili satırın hedef dili:"))
        self.queue_target_combo = QComboBox()
        for code, name in target_options():
            self.queue_target_combo.addItem(name, code)
        target_row.addWidget(self.queue_target_combo)
        self.queue_apply_target = QPushButton("Uygula")
        self.queue_apply_target.clicked.connect(self._apply_queue_target)
        target_row.addWidget(self.queue_apply_target)
        self.queue_apply_all = QPushButton("Tümüne Uygula")
        self.queue_apply_all.clicked.connect(self._apply_queue_target_all)
        target_row.addWidget(self.queue_apply_all)
        target_row.addWidget(
            _make_hint("Her dosya farklı dile çevrilebilir; transkript bir kez çıkarılır."), 1
        )
        layout.addLayout(target_row)

        self.queue_summary = _make_hint("Kuyruk boş. İş seçenekleri 'Video' sekmesinden alınır.")
        layout.addWidget(self.queue_summary)

        actions = QHBoxLayout()
        self.queue_start_button = QPushButton("Kuyruğu Başlat")
        self.queue_start_button.setMinimumHeight(38)
        self.queue_start_button.clicked.connect(self._start_queue)
        self.queue_stop_button = QPushButton("Durdur")
        self.queue_stop_button.setMinimumHeight(38)
        self.queue_stop_button.setEnabled(False)
        self.queue_stop_button.clicked.connect(self._cancel_current)
        actions.addWidget(self.queue_start_button, 2)
        actions.addWidget(self.queue_stop_button, 1)
        layout.addLayout(actions)
        return page

    # -- sekme 3: SRT cevir ------------------------------------------------
    def _build_srt_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.srt_drop = DropArea(
            "Var olan .srt dosyasını buraya bırakın\n(transkripsiyon atlanır, yalnızca çeviri yapılır)",
            {".srt"},
        )
        self.srt_drop.files_dropped.connect(lambda files: self._set_srt_input(files[0]))
        self.srt_drop.clicked.connect(self._choose_srt_file)
        layout.addWidget(self.srt_drop)

        row = QHBoxLayout()
        srt_button = QPushButton("SRT Seç…")
        srt_button.clicked.connect(self._choose_srt_file)
        self.srt_file_label = _make_hint("Seçili altyazı yok")
        self.srt_file_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(srt_button)
        row.addWidget(self.srt_file_label, 1)
        layout.addLayout(row)

        video_row = QHBoxLayout()
        video_button = QPushButton("Video Seç (isteğe bağlı)…")
        video_button.clicked.connect(self._choose_srt_video)
        self.srt_video_label = _make_hint("Video seçilmezse yalnızca .srt yazılır")
        self.srt_video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        video_row.addWidget(video_button)
        video_row.addWidget(self.srt_video_label, 1)
        layout.addLayout(video_row)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Kaynak dil:"))
        self.srt_lang_combo = QComboBox()
        self.srt_lang_combo.addItem("Otomatik tahmin", "")
        for code, name in sorted(WHISPER_LANGUAGE_NAMES_TR.items(), key=lambda item: item[1]):
            self.srt_lang_combo.addItem(name, code)
        lang_row.addWidget(self.srt_lang_combo)
        lang_row.addStretch(1)
        layout.addLayout(lang_row)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Hedef dil:"))
        self.srt_target_combo = QComboBox()
        for code, name in target_options():
            self.srt_target_combo.addItem(name, code)
        target_row.addWidget(self.srt_target_combo)
        self.srt_target_hint = _make_hint(
            "Bu sekme kendi hedef dilini kullanır; 'Video' sekmesindeki seçimden bağımsızdır."
        )
        target_row.addWidget(self.srt_target_hint, 1)
        layout.addLayout(target_row)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Çıktı:"))
        self.srt_output_combo = QComboBox()
        self.srt_output_combo.addItem("Sadece .srt altyazı", "srt")
        self.srt_output_combo.addItem("Videoya yak (burn-in)", "burn")
        self.srt_output_combo.addItem("Yumuşak altyazı olarak ekle", "soft")
        out_row.addWidget(self.srt_output_combo)
        self.srt_output_hint = _make_hint(
            "Video seçmediyseniz yalnızca .srt yazılır."
        )
        out_row.addWidget(self.srt_output_hint, 1)
        layout.addLayout(out_row)

        actions = QHBoxLayout()
        self.srt_start_button = QPushButton("Çevir ve Altyazı Üret")
        self.srt_start_button.setMinimumHeight(38)
        self.srt_start_button.clicked.connect(self._start_srt)
        actions.addWidget(self.srt_start_button, 2)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)
        return page

    # -- sekme 4: ayarlar --------------------------------------------------
    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        # Donanim -----------------------------------------------------------
        hardware_box = QGroupBox("Donanım")
        hardware_layout = QVBoxLayout(hardware_box)
        self.hardware_label = QLabel("—")
        hardware_layout.addWidget(self.hardware_label)
        self.pipeline_hint = _make_hint("")
        hardware_layout.addWidget(self.pipeline_hint)
        layout.addWidget(hardware_box)

        # Performans --------------------------------------------------------
        perf_box = QGroupBox("Performans")
        perf_layout = QVBoxLayout(perf_box)

        threads_row = QHBoxLayout()
        threads_row.addWidget(QLabel("CPU thread:"))
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(0, 64)
        self.threads_spin.setSpecialValueText("Otomatik")
        threads_row.addWidget(self.threads_spin)
        threads_row.addSpacing(12)
        threads_row.addWidget(QLabel("num_workers:"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 8)
        threads_row.addWidget(self.workers_spin)
        threads_row.addStretch(1)
        perf_layout.addLayout(threads_row)
        perf_layout.addWidget(
            _make_hint(
                "Otomatik: fiziksel çekirdek sayısı kullanılır. num_workers > 1 "
                "bellek tüketimini artırır."
            )
        )

        pipeline_row = QHBoxLayout()
        pipeline_row.addWidget(QLabel("Transkripsiyon + çeviri paralel:"))
        self.pipeline_combo = QComboBox()
        self.pipeline_combo.addItem("Otomatik (önerilen)", "auto")
        self.pipeline_combo.addItem("Her zaman açık", "on")
        self.pipeline_combo.addItem("Kapalı", "off")
        pipeline_row.addWidget(self.pipeline_combo)
        pipeline_row.addStretch(1)
        perf_layout.addLayout(pipeline_row)
        perf_layout.addWidget(
            _make_hint(
                "Paralel çalışma yalnızca 6+ fiziksel çekirdekte gerçek kazanç sağlar; "
                "altında Whisper ile NLLB birbirinin thread'lerini çalar."
            )
        )
        self.pipeline_effective = _make_hint("")
        perf_layout.addWidget(self.pipeline_effective)
        layout.addWidget(perf_box)

        # Altyazi kalitesi --------------------------------------------------
        quality_box = QGroupBox("Altyazı kalitesi")
        quality_layout = QVBoxLayout(quality_box)
        cps_row = QHBoxLayout()
        cps_row.addWidget(QLabel("Okuma hızı sınırı (CPS):"))
        self.cps_spin = QSpinBox()
        self.cps_spin.setRange(0, 40)
        self.cps_spin.setValue(18)
        cps_row.addWidget(self.cps_spin)
        cps_row.addWidget(_make_hint("0 = kapalı. Önerilen 17–20 (karakter/saniye)."), 1)
        quality_layout.addLayout(cps_row)

        self.words_check = QCheckBox("Kelime düzeyinde zaman damgası (daha doğru bölme, ~%15 daha yavaş)")
        quality_layout.addWidget(self.words_check)

        crf_row = QHBoxLayout()
        crf_row.addWidget(QLabel("Burn-in kalitesi (CRF):"))
        self.crf_spin = QSpinBox()
        self.crf_spin.setRange(12, 30)
        self.crf_spin.setValue(18)
        crf_row.addWidget(self.crf_spin)
        self.crf_hint = _make_hint("")
        crf_row.addWidget(self.crf_hint, 1)
        quality_layout.addLayout(crf_row)

        # Whisper batch (hız) ------------------------------------------------
        batch_row = QHBoxLayout()
        batch_row.addWidget(QLabel("Whisper batch boyutu:"))
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(0, 32)
        self.batch_spin.setSpecialValueText("Kapalı")
        self.batch_spin.setValue(0)
        batch_row.addWidget(self.batch_spin)
        self.batch_hint = _make_hint("")
        batch_row.addWidget(self.batch_hint, 1)
        quality_layout.addLayout(batch_row)

        # Transkript önbelleği ----------------------------------------------
        self.cache_check = QCheckBox(
            "Transkript önbelleği (aynı videoyu başka dile çevirirken Whisper'ı atla)"
        )
        self.cache_check.setChecked(True)
        quality_layout.addWidget(self.cache_check)

        cache_row = QHBoxLayout()
        self.cache_info = _make_hint("")
        cache_row.addWidget(self.cache_info, 1)
        self.cache_clear_button = QPushButton("Transkript Önbelleğini Temizle")
        self.cache_clear_button.clicked.connect(self._clear_transcript_cache)
        cache_row.addWidget(self.cache_clear_button)
        quality_layout.addLayout(cache_row)

        self.preview_check = QCheckBox(
            "Videoya işlemeden önce altyazıyı göster (düzeltme imkânı)"
        )
        self.preview_check.setChecked(True)
        self.preview_check.setToolTip(
            "SRT üretildikten sonra durur, metni/zamanlamayı düzeltmenize izin verir."
        )
        quality_layout.addWidget(self.preview_check)

        self.overwrite_check = QCheckBox("Var olan çıktı dosyalarının üzerine yaz")
        self.overwrite_check.setChecked(True)
        self.overwrite_check.setToolTip(
            "Kapalıysa mevcut dosyalar korunur; yeni çıktı _2, _3… ekiyle yazılır."
        )
        quality_layout.addWidget(self.overwrite_check)

        layout.addWidget(quality_box)

        # FFmpeg ------------------------------------------------------------
        ffmpeg_box = QGroupBox("FFmpeg")
        ffmpeg_layout = QVBoxLayout(ffmpeg_box)
        self.ffmpeg_label = QLabel("FFmpeg: kontrol ediliyor…")
        ffmpeg_layout.addWidget(self.ffmpeg_label)
        ffmpeg_row = QHBoxLayout()
        self.ffmpeg_download_button = QPushButton("FFmpeg'i İndir")
        self.ffmpeg_download_button.clicked.connect(self._download_ffmpeg)
        self.ffmpeg_choose_button = QPushButton("ffmpeg.exe Yolu Seç…")
        self.ffmpeg_choose_button.clicked.connect(self._choose_ffmpeg)
        self.ffmpeg_page_button = QPushButton("İndirme Sayfası")
        self.ffmpeg_page_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(FFMPEG_DOWNLOAD_URL))
        )
        ffmpeg_row.addWidget(self.ffmpeg_download_button)
        ffmpeg_row.addWidget(self.ffmpeg_choose_button)
        ffmpeg_row.addWidget(self.ffmpeg_page_button)
        ffmpeg_row.addStretch(1)
        ffmpeg_layout.addLayout(ffmpeg_row)
        layout.addWidget(ffmpeg_box)

        # Ceviri motoru -----------------------------------------------------
        engine_box = QGroupBox("Çeviri motoru (CTranslate2)")
        engine_layout = QVBoxLayout(engine_box)
        self.engine_label = QLabel("Kontrol edilmedi")
        self.engine_label.setStyleSheet("color: #6b7280;")
        engine_layout.addWidget(self.engine_label)
        engine_row = QHBoxLayout()
        self.engine_check_button = QPushButton("Kontrol Et")
        self.engine_check_button.clicked.connect(lambda: self._check_engine(announce=True))
        self.vcredist_button = QPushButton("VC++ Paketi İndir")
        self.vcredist_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(VCREDIST_URL))
        )
        engine_row.addWidget(self.engine_check_button)
        engine_row.addWidget(self.vcredist_button)
        engine_row.addStretch(1)
        engine_layout.addLayout(engine_row)
        layout.addWidget(engine_box)

        # Model onbellegi ---------------------------------------------------
        cache_box = QGroupBox("Model önbelleği")
        cache_layout = QVBoxLayout(cache_box)
        self.cache_table = QTableWidget(0, 2)
        self.cache_table.setHorizontalHeaderLabels(["Model", "Boyut"])
        self.cache_table.verticalHeader().setVisible(False)
        self.cache_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cache_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        cache_header = self.cache_table.horizontalHeader()
        cache_header.setSectionResizeMode(0, QHeaderView.Stretch)
        cache_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.cache_table.setMinimumHeight(120)
        self.cache_table.setMaximumHeight(150)
        cache_layout.addWidget(self.cache_table)

        cache_row = QHBoxLayout()
        self.cache_refresh_button = QPushButton("Yenile")
        self.cache_refresh_button.clicked.connect(self._refresh_cache_table)
        self.cache_delete_button = QPushButton("Seçileni Sil")
        self.cache_delete_button.clicked.connect(self._delete_selected_model)
        self.cache_folder_button = QPushButton("Klasörü Aç")
        self.cache_folder_button.clicked.connect(self._open_models_folder)
        self.cache_total_label = _make_hint("")
        cache_row.addWidget(self.cache_refresh_button)
        cache_row.addWidget(self.cache_delete_button)
        cache_row.addWidget(self.cache_folder_button)
        cache_row.addWidget(self.cache_total_label, 1)
        cache_layout.addLayout(cache_row)
        layout.addWidget(cache_box)

        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(page)
        return scroll

    # ------------------------------------------------------------------
    # Ayar yukleme / kaydetme
    # ------------------------------------------------------------------
    def _load_settings(self) -> None:
        recommended = recommended_model_size()
        model = self._settings.value("model_size", recommended, str)
        index = self.model_combo.findData(model)
        self.model_combo.setCurrentIndex(index if index >= 0 else self.model_combo.findData(recommended))

        target = self._settings.value("target_lang", "tr", str)
        index = self.target_combo.findData(target)
        if index >= 0:
            self.target_combo.setCurrentIndex(index)

        mode = self._settings.value("output_mode", "burn", str)
        mapping = {"burn": self.radio_burn, "soft": self.radio_soft, "srt": self.radio_srt}
        mapping.get(mode, self.radio_burn).setChecked(True)

        try:
            self.size_spin.setValue(int(self._settings.value("font_size", 18)))
        except (TypeError, ValueError):
            self.size_spin.setValue(18)

        position = self._settings.value("subtitle_position", "bottom", str)
        index = self.position_combo.findData(position)
        if index >= 0:
            self.position_combo.setCurrentIndex(index)

        try:
            self.threads_spin.setValue(int(self._settings.value("cpu_threads", 0)))
        except (TypeError, ValueError):
            self.threads_spin.setValue(0)
        try:
            self.workers_spin.setValue(int(self._settings.value("num_workers", 1)))
        except (TypeError, ValueError):
            self.workers_spin.setValue(1)

        pipeline = self._settings.value("pipeline_mode", "auto", str)
        index = self.pipeline_combo.findData(pipeline)
        if index >= 0:
            self.pipeline_combo.setCurrentIndex(index)

        try:
            self.cps_spin.setValue(int(self._settings.value("max_cps", 18)))
        except (TypeError, ValueError):
            self.cps_spin.setValue(18)

        words = self._settings.value("word_timestamps", True, bool)
        self.words_check.setChecked(words)

        try:
            self.crf_spin.setValue(int(self._settings.value("burn_crf", 18)))
        except (TypeError, ValueError):
            self.crf_spin.setValue(18)
        self.crf_spin.valueChanged.connect(self._update_crf_hint)
        self._update_crf_hint()

        try:
            self.batch_spin.setValue(int(self._settings.value("whisper_batch_size", 0)))
        except (TypeError, ValueError):
            self.batch_spin.setValue(0)
        self.batch_spin.valueChanged.connect(self._update_batch_hint)
        self._update_batch_hint()

        cached = self._settings.value("use_transcript_cache", True, bool)
        self.cache_check.setChecked(cached)
        self.cache_check.stateChanged.connect(self._refresh_cache_info)
        self._refresh_cache_info()

        self.preview_check.setChecked(
            not self._settings.value("skip_preview", False, bool)
        )
        self.overwrite_check.setChecked(
            self._settings.value("overwrite_output", True, bool)
        )

        source_lang = self._settings.value("srt_source_lang", "", str)
        index = self.srt_lang_combo.findData(source_lang)
        if index >= 0:
            self.srt_lang_combo.setCurrentIndex(index)

        srt_target = self._settings.value("srt_target_lang", "tr", str)
        index = self.srt_target_combo.findData(srt_target)
        if index >= 0:
            self.srt_target_combo.setCurrentIndex(index)

        srt_output = self._settings.value("srt_output_mode", "srt", str)
        index = self.srt_output_combo.findData(srt_output)
        if index >= 0:
            self.srt_output_combo.setCurrentIndex(index)

        self._apply_color_button()
        self._update_style_enabled()
        self._update_model_hint()
        self.pipeline_combo.currentIndexChanged.connect(self._update_pipeline_hint)
        self._update_pipeline_hint()

    def _save_settings(self) -> None:
        self._settings.setValue("model_size", self.model_combo.currentData())
        self._settings.setValue("target_lang", self.target_combo.currentData())
        self._settings.setValue("output_mode", self._current_mode())
        self._settings.setValue("font_size", self.size_spin.value())
        self._settings.setValue("subtitle_position", self.position_combo.currentData())
        self._settings.setValue("subtitle_color", self._color)
        self._settings.setValue("ffmpeg_path", self._ffmpeg_path)
        self._settings.setValue("cpu_threads", self.threads_spin.value())
        self._settings.setValue("num_workers", self.workers_spin.value())
        self._settings.setValue("pipeline_mode", self.pipeline_combo.currentData())
        self._settings.setValue("max_cps", self.cps_spin.value())
        self._settings.setValue("word_timestamps", self.words_check.isChecked())
        self._settings.setValue("burn_crf", self.crf_spin.value())
        self._settings.setValue("whisper_batch_size", self.batch_spin.value())
        self._settings.setValue("use_transcript_cache", self.cache_check.isChecked())
        self._settings.setValue("skip_preview", not self.preview_check.isChecked())
        self._settings.setValue("overwrite_output", self.overwrite_check.isChecked())
        self._settings.setValue("srt_source_lang", self.srt_lang_combo.currentData())
        self._settings.setValue("srt_target_lang", self.srt_target_combo.currentData())
        self._settings.setValue("srt_output_mode", self.srt_output_combo.currentData())

    # ------------------------------------------------------------------
    # Kucuk yardimcilar
    # ------------------------------------------------------------------
    def _current_mode(self) -> str:
        if self.radio_soft.isChecked():
            return "soft"
        if self.radio_srt.isChecked():
            return "srt"
        return "burn"

    def _update_model_hint(self) -> None:
        key = self.model_combo.currentData() or "small"
        hint = f"CPU'da hız/kalite: {MODEL_HINTS.get(key, '')}"

        # RAM uyarısı: seçim engellenmez ama kullanıcı bilgilendirilir.
        try:
            import hardware

            available = hardware.available_ram_mb()
            need = (
                hardware.MODEL_RAM_MB.get(key, 400)
                + hardware.NLLB_RAM_MB
                + hardware.OVERHEAD_RAM_MB
            )
            if available and available < need:
                hint += (
                    f"\n⚠ Bu makinede {available} MB boş bellek var, tahmini ihtiyaç "
                    f"~{need} MB. Daha küçük model önerilir."
                )
                self.model_hint.setStyleSheet("color: #b45309;")
            else:
                self.model_hint.setStyleSheet("color: #6b7280;")
        except Exception:
            self.model_hint.setStyleSheet("color: #6b7280;")

        self.model_hint.setText(hint)

    def _update_style_enabled(self, *_args) -> None:
        self.style_box.setEnabled(self._current_mode() == "burn" and not getattr(self, "_busy", False))

    def _update_batch_hint(self) -> None:
        """Batch boyutunun hız/bellek etkisini açıklar."""
        value = self.batch_spin.value()
        if value <= 1:
            text = "kapalı — pencere pencere işlenir"
        elif value <= 8:
            text = "açık — CPU'da ölçülen kazanç: tiny 1.8×, small 1.2×"
        else:
            text = "yüksek — daha hızlı olabilir ama bellek tüketimi artar"
        self.batch_hint.setText(f"{text}. Varsayılan kapalı; sorun çıkarsa kapalı bırakın.")

    def _refresh_cache_info(self, *_args) -> None:
        """Transkript önbelleğinin boyutunu ve kayıt sayısını gösterir."""
        import app_paths
        import transcript_cache

        directory = app_paths.transcripts_dir()
        files = list(directory.glob("*.json"))
        size = transcript_cache.total_size(directory)
        enabled = self.cache_check.isChecked()

        if not enabled:
            self.cache_info.setText(
                f"Önbellek kapalı — {len(files)} kayıt ({size / 1024 / 1024:.1f} MB) kullanılmıyor."
            )
        elif not files:
            self.cache_info.setText("Önbellek boş — ilk videoda dolacak.")
        else:
            self.cache_info.setText(
                f"{len(files)} transkript önbellekte ({size / 1024 / 1024:.1f} MB). "
                "Aynı video tekrar işlenirse transkripsiyon atlanır."
            )
        self.cache_clear_button.setEnabled(bool(files) and not self._is_busy())

    def _clear_transcript_cache(self) -> None:
        import app_paths
        import transcript_cache

        directory = app_paths.transcripts_dir()
        files = list(directory.glob("*.json"))
        if not files:
            QMessageBox.information(self, "Önbellek boş", "Silinecek transkript yok.")
            return
        answer = QMessageBox.question(
            self,
            "Transkript önbelleğini temizle",
            f"{len(files)} transkript silinsin mi?\n\n"
            "Silinirse aynı videolar için Whisper yeniden çalışır.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        removed = transcript_cache.clear(directory)
        self._append_log(f"Transkript önbelleği temizlendi: {removed} kayıt.")
        self._refresh_cache_info()

    def _update_crf_hint(self) -> None:
        """CRF degerinin kalite/boyut etkisini aciklar."""
        value = self.crf_spin.value()
        if value <= 16:
            text = "çok yüksek kalite, büyük dosya"
        elif value <= 19:
            text = "yüksek kalite (önerilen)"
        elif value <= 23:
            text = "dengeli"
        elif value <= 27:
            text = "düşük kalite — karanlık sahnelerde bloklanma olabilir"
        else:
            text = "çok düşük kalite — bloklanma kaçınılmaz"
        self.crf_hint.setText(f"{text}. Karanlık/bulanık videolarda 16–18 kullanın.")

    def _update_pipeline_hint(self) -> None:
        info = hardware_info()
        mode = self.pipeline_combo.currentData()
        effective = info.pipeline_worthwhile if mode == "auto" else (mode == "on")
        whisper, nllb = info.thread_budget(effective)
        state = "açık" if effective else "kapalı"
        self.pipeline_effective.setText(
            f"Bu bilgisayarda etkin durum: {state} — Whisper {whisper} thread, NLLB {nllb} thread."
        )
        if mode == "on" and not info.pipeline_worthwhile:
            self.pipeline_effective.setStyleSheet("color: #b45309;")
            self.pipeline_effective.setText(
                self.pipeline_effective.text()
                + " Uyarı: bu donanımda paralel çalışma süreyi kısaltmayabilir."
            )
        else:
            self.pipeline_effective.setStyleSheet("color: #6b7280;")

    def _refresh_hardware(self) -> None:
        info = hardware_info()
        self.hardware_label.setText(f"Donanım: {info.describe()}")
        self.pipeline_hint.setText(
            "Paralel çalışma için 6+ fiziksel çekirdek önerilir "
            f"(bu bilgisayarda {'uygun' if info.pipeline_worthwhile else 'uygun değil'})."
        )
        self._update_pipeline_hint()

    def _apply_color_button(self) -> None:
        self.color_button.setStyleSheet(
            f"background-color: {self._color}; border: 1px solid #6b7280; border-radius: 4px;"
        )

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._color), self, "Altyazı rengi")
        if color.isValid():
            self._color = color.name(QColor.HexRgb)
            self._apply_color_button()

    def _style(self) -> SubtitleStyle:
        return SubtitleStyle(
            font_name="Arial",
            font_size=self.size_spin.value(),
            color=self._color,
            position=self.position_combo.currentData() or "bottom",
            outline=2,
            margin_v=20,
        )

    def _log(self, message: str) -> None:
        logging_setup.get_logger("ui").info(message)

    def _append_log(self, message: str) -> None:
        """Is akisi mesajini panele VE log dosyasina yazar.

        Panel zaten bu mesaji gosterdigi icin `log_to_file` kullanilir;
        arayuz kuyruguna eklenirse tekrar olur.
        """
        self.log_view.appendPlainText(message)
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())
        logging_setup.log_to_file(message)

    def timerEvent(self, event) -> None:  # noqa: N802
        messages = logging_setup.poll_messages(400)
        if messages:
            for message in messages:
                self.log_view.appendPlainText(message)
            bar = self.log_view.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _is_busy(self) -> bool:
        return (
            (self._worker is not None and self._worker.isRunning())
            or (self._batch is not None and self._batch.isRunning())
        )

    # ------------------------------------------------------------------
    # FFmpeg
    # ------------------------------------------------------------------
    def _refresh_ffmpeg_status(self, silent: bool = False, announce: bool = False) -> bool:
        location = ffmpeg_bootstrap.find_existing(self._ffmpeg_path or None)
        if location is None:
            self.ffmpeg_label.setText("FFmpeg: bulunamadı — indirebilir veya yol seçebilirsiniz")
            self.ffmpeg_label.setStyleSheet("color: #b91c1c; font-weight: bold;")
            self.ffmpeg_download_button.setEnabled(not self._is_busy())
            if announce:
                self._append_log("FFmpeg bulunamadı.")
            return False

        self.ffmpeg_label.setText(f"FFmpeg: hazır — {location.ffmpeg}  ({location.source})")
        self.ffmpeg_label.setStyleSheet("color: #15803d;")
        self.ffmpeg_download_button.setEnabled(False)
        if not silent:
            self._log(f"FFmpeg bulundu: {location.ffmpeg}")
        return True

    def _choose_ffmpeg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "ffmpeg.exe dosyasını seçin",
            "",
            "ffmpeg (ffmpeg.exe);;Çalıştırılabilir dosyalar (*.exe);;Tüm dosyalar (*.*)",
        )
        if not path:
            return
        self._ffmpeg_path = path
        self._save_settings()
        if self._refresh_ffmpeg_status(silent=True):
            self._append_log(f"FFmpeg yolu ayarlandı: {path}")
        else:
            QMessageBox.warning(
                self, "Geçersiz FFmpeg", "Seçilen dosya çalıştırılabilir bir ffmpeg değil."
            )

    def _download_ffmpeg(self) -> None:
        if self._is_busy() or getattr(self, "_ffmpeg_download", None) is not None:
            return
        answer = QMessageBox.question(
            self,
            "FFmpeg indirilsin mi?",
            "FFmpeg otomatik olarak indirilecek (~90 MB) ve şu klasöre kurulacak:\n\n"
            f"{app_paths.ffmpeg_dir()}\n\nDevam edilsin mi?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return

        self.ffmpeg_download_button.setEnabled(False)
        self.stage_label.setText("FFmpeg indiriliyor…")
        self.progress.setValue(0)

        worker = FFmpegDownloadWorker(self)
        self._ffmpeg_download = worker
        worker.progress.connect(self._on_ffmpeg_progress)
        worker.log.connect(self._append_log)
        worker.finished_ok.connect(self._on_ffmpeg_downloaded)
        worker.failed.connect(self._on_ffmpeg_failed)
        worker.finished.connect(self._on_ffmpeg_download_done)
        worker.start()

    def _on_ffmpeg_progress(self, percent: int, label: str) -> None:
        self.progress.setValue(percent)
        self.stage_label.setText(f"FFmpeg: {label}")

    def _on_ffmpeg_downloaded(self, ffmpeg_path: str) -> None:
        self._append_log(f"FFmpeg hazır: {ffmpeg_path}")
        self._ffmpeg_path = ""
        self._save_settings()
        self._refresh_ffmpeg_status(silent=True)
        self.stage_label.setText("FFmpeg hazır")
        self.progress.setValue(0)

    def _on_ffmpeg_failed(self, message: str) -> None:
        self._append_log(f"FFmpeg indirme hatası: {message}")
        self.stage_label.setText("FFmpeg indirilemedi")
        self.progress.setValue(0)
        self._last_error = message
        QMessageBox.critical(self, "FFmpeg indirilemedi", message)

    def _on_ffmpeg_download_done(self) -> None:
        self._ffmpeg_download = None
        self._refresh_ffmpeg_status(silent=True)
        self.ffmpeg_download_button.setEnabled(
            not self._is_busy()
            and ffmpeg_bootstrap.find_existing(self._ffmpeg_path or None) is None
        )

    def _check_engine(self, announce: bool = False) -> bool:
        problem = check_ctranslate2_runtime()
        if problem is None:
            self._engine_ok = True
            self.engine_label.setText("Çeviri motoru: hazır")
            self.engine_label.setStyleSheet("color: #15803d;")
            if announce:
                self._append_log("CTranslate2 çalışma kontrolü başarılı.")
            return True

        self._engine_ok = False
        self.engine_label.setText("Çeviri motoru: ÇALIŞMIYOR (VC++ paketi gerekli)")
        self.engine_label.setStyleSheet("color: #b91c1c; font-weight: bold;")
        self._append_log("CTranslate2 çalışma kontrolü BAŞARISIZ.")
        if announce:
            box = QMessageBox(self)
            box.setWindowTitle("Çeviri motoru çalışmıyor")
            box.setIcon(QMessageBox.Critical)
            box.setText(problem)
            open_button = box.addButton("VC++ İndirme Sayfasını Aç", QMessageBox.AcceptRole)
            box.addButton("Kapat", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is open_button:
                QDesktopServices.openUrl(QUrl(VCREDIST_URL))
        return False

    # ------------------------------------------------------------------
    # Model onbellegi
    # ------------------------------------------------------------------
    def _refresh_cache_table(self) -> None:
        try:
            items = self._model_cache.inventory()
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"Önbellek okunamadı: {exc}")
            return

        self.cache_table.setRowCount(len(items))
        total = 0
        for row, item in enumerate(items):
            name_item = QTableWidgetItem(item["label"])
            name_item.setData(Qt.UserRole, item["key"])
            size_item = QTableWidgetItem(_format_size(item["size"]))
            self.cache_table.setItem(row, 0, name_item)
            self.cache_table.setItem(row, 1, size_item)
            total += item["size"]
        self.cache_total_label.setText(
            f"{len(items)} model, toplam {_format_size(total)} — konum: {self._model_cache.models_root}"
        )

    def _delete_selected_model(self) -> None:
        rows = self.cache_table.selectionModel().selectedRows() if self.cache_table.selectionModel() else []
        if not rows:
            QMessageBox.information(self, "Seçim yok", "Silmek için listeden bir model seçin.")
            return
        row = rows[0].row()
        item = self.cache_table.item(row, 0)
        if item is None:
            return
        key = item.data(Qt.UserRole)
        label = item.text()
        answer = QMessageBox.question(
            self,
            "Modeli sil",
            f"'{label}' modeli silinsin mi?\n\nGerekirse tekrar indirilir.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        ok, message = self._model_cache.delete(key)
        self._append_log(message)
        if not ok:
            QMessageBox.warning(self, "Silinemedi", message)
        self._refresh_cache_table()

    def _open_models_folder(self) -> None:
        _open_folder(self._model_cache.models_root)

    # ------------------------------------------------------------------
    # Tek video akisi
    # ------------------------------------------------------------------
    def _choose_single_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Video seçin", "", VIDEO_FILTER)
        if path:
            self._set_single_input(path)

    def _set_single_input(self, path: str) -> None:
        if Path(path).suffix.lower() not in SUPPORTED_EXTENSIONS:
            QMessageBox.warning(
                self,
                "Desteklenmeyen dosya",
                "Desteklenen türler:\n" + ", ".join(sorted(SUPPORTED_EXTENSIONS)),
            )
            return
        self._single_input = path
        self.single_file_label.setText(path)
        self.single_file_label.setStyleSheet("")
        self.single_drop.set_text(f"Seçili video:\n{Path(path).name}")
        self._append_log(f"Video seçildi: {path}")

    def _base_settings(
        self,
        input_path: str = "",
        input_srt: str = "",
        target_lang: str | None = None,
        output_mode: str | None = None,
    ) -> JobSettings:
        return JobSettings(
            input_path=input_path,
            input_srt=input_srt,
            model_size=self.model_combo.currentData() or "small",
            target_lang=target_lang or self.target_combo.currentData() or "tr",
            output_mode=output_mode or self._current_mode(),
            style=self._style(),
            ffmpeg_path=self._ffmpeg_path,
            models_dir=str(self._model_cache.models_root),
            max_cps=float(self.cps_spin.value()),
            word_timestamps=self.words_check.isChecked(),
            pipeline_mode=self.pipeline_combo.currentData() or "auto",
            cpu_threads=self.threads_spin.value(),
            num_workers=self.workers_spin.value(),
            burn_crf=self.crf_spin.value(),
            batch_size=self.batch_spin.value(),
            use_transcript_cache=self.cache_check.isChecked(),
            skip_preview=not self.preview_check.isChecked(),
            overwrite=self.overwrite_check.isChecked(),
            source_lang=self.srt_lang_combo.currentData() or "",
        )

    def _preflight(self, needs_engine: bool = True) -> bool:
        self._save_settings()
        if not self._refresh_ffmpeg_status(silent=True) and not self._confirm_ffmpeg():
            return False
        if needs_engine and self._engine_ok is not True:
            self._append_log("Çeviri motoru kontrol ediliyor…")
            if not self._check_engine(announce=True):
                return False
        return True

    def _confirm_ffmpeg(self) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("FFmpeg bulunamadı")
        box.setIcon(QMessageBox.Warning)
        box.setText(
            "FFmpeg kurulu değil. Ses çıkarmak ve altyazıyı videoya işlemek "
            "için gereklidir.\n\nOtomatik indirebilir veya dosyayı elle gösterebilirsiniz."
        )
        download = box.addButton("Otomatik İndir", QMessageBox.AcceptRole)
        choose = box.addButton("ffmpeg.exe Yolu Seç…", QMessageBox.ActionRole)
        box.addButton("Vazgeç", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is download:
            self.tabs.setCurrentIndex(3)
            self._download_ffmpeg()
            return self._refresh_ffmpeg_status(silent=True)
        if clicked is choose:
            self._choose_ffmpeg()
            return self._refresh_ffmpeg_status(silent=True)
        return False

    def _start_single(self) -> None:
        if self._is_busy():
            return
        path = getattr(self, "_single_input", "")
        if not path or not Path(path).exists():
            QMessageBox.information(self, "Video seçilmedi", "Lütfen önce bir video dosyası seçin.")
            return
        if not self._preflight():
            return

        self._reset_run_ui()
        settings = self._base_settings(input_path=path)
        self._start_worker(settings)

    def _start_srt(self) -> None:
        if self._is_busy():
            return
        srt = getattr(self, "_srt_input", "")
        if not srt or not Path(srt).exists():
            QMessageBox.information(self, "SRT seçilmedi", "Lütfen önce bir .srt dosyası seçin.")
            return

        target = self.srt_target_combo.currentData() or "tr"
        source = self.srt_lang_combo.currentData() or ""
        if source and source == target:
            QMessageBox.information(
                self,
                "Aynı dil",
                "Kaynak dil ile hedef dil aynı. Lütfen farklı bir hedef dil seçin.",
            )
            return

        video = getattr(self, "_srt_video", "")
        mode = self.srt_output_combo.currentData() or "srt"
        if mode != "srt" and not video:
            self._append_log("Video seçilmedi: yalnızca .srt üretilecek.")
            mode = "srt"
        if not self._preflight():
            return

        self._reset_run_ui()
        self._append_log(
            f"SRT çevirisi: kaynak={'otomatik' if not source else source}, hedef={target}"
        )
        settings = self._base_settings(
            input_path=video,
            input_srt=srt,
            target_lang=target,
            output_mode=mode,
        )
        self._start_worker(settings)

    def _start_worker(self, settings: JobSettings) -> None:
        self._worker = VideoWorker(settings, models=self._model_cache)
        self._worker.log.connect(self._append_log)
        self._worker.stage_changed.connect(self.stage_label.setText)
        self._worker.progress_changed.connect(self.progress.setValue)
        self._worker.language_detected.connect(self._on_language)
        self._worker.preview_requested.connect(self._on_preview_single)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)
        self._set_busy(True)
        self._append_log("İş başlatıldı.")
        self._worker.start()

    # ------------------------------------------------------------------
    # Kuyruk akisi
    # ------------------------------------------------------------------
    def _choose_queue_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Videoları seçin", "", VIDEO_FILTER)
        if files:
            self._add_to_queue(files)

    def _add_to_queue(self, files: list[str]) -> None:
        # Anahtar (yol, hedef dil): aynı video farklı dillere eklenebilir,
        # aynı yol+dil ikinci kez eklenmez.
        existing = set()
        for row in range(self.queue_table.rowCount()):
            item = self.queue_table.item(row, 0)
            if item is not None:
                existing.add((item.data(Qt.UserRole), self._queue_target(row)))

        default_target = self.target_combo.currentData() or "tr"
        added = 0
        skipped = 0
        for path in files:
            if Path(path).suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if (path, default_target) in existing:
                skipped += 1
                continue
            row = self.queue_table.rowCount()
            self.queue_table.insertRow(row)
            name_item = QTableWidgetItem(Path(path).name)
            name_item.setData(Qt.UserRole, path)
            name_item.setToolTip(path)
            self.queue_table.setItem(row, 0, name_item)
            self.queue_table.setItem(row, 1, self._target_item(default_target))
            self.queue_table.setItem(row, 2, QTableWidgetItem("Bekliyor"))
            self.queue_table.setItem(row, 3, QTableWidgetItem("—"))
            existing.add((path, default_target))
            added += 1
        self.queue_table.resizeRowsToContents()
        self._update_queue_summary()
        if added:
            self._append_log(f"Kuyruğa {added} dosya eklendi.")
        if skipped:
            self._append_log(
                f"{skipped} dosya zaten aynı hedef dille kuyrukta; atlandı."
            )

    @staticmethod
    def _target_item(code: str) -> QTableWidgetItem:
        """Hedef dil hücresi: görünen ad, veri olarak kod."""
        from languages import target_label

        item = QTableWidgetItem(target_label(code))
        item.setData(Qt.UserRole, code)
        item.setToolTip(f"Hedef dil: {code}\nDeğiştirmek için satırı seçip aşağıdaki listeden uygulayın.")
        return item

    def _queue_target(self, row: int) -> str:
        item = self.queue_table.item(row, 1)
        if item is not None:
            code = item.data(Qt.UserRole)
            if code:
                return str(code)
        return self.target_combo.currentData() or "tr"

    def _apply_queue_target(self) -> None:
        model = self.queue_table.selectionModel()
        rows = [index.row() for index in model.selectedRows()] if model else []
        if not rows:
            QMessageBox.information(
                self, "Seçim yok", "Hedef dilini değiştirmek için önce satır(lar) seçin."
            )
            return
        code = self.queue_target_combo.currentData() or "tr"
        for row in rows:
            self.queue_table.setItem(row, 1, self._target_item(code))
        self._append_log(
            f"{len(rows)} satırın hedef dili değiştirildi: "
            f"{TARGET_LANGUAGES[code]['label'] if code in TARGET_LANGUAGES else code}"
        )
        self._update_queue_summary()

    def _apply_queue_target_all(self) -> None:
        code = self.queue_target_combo.currentData() or "tr"
        for row in range(self.queue_table.rowCount()):
            self.queue_table.setItem(row, 1, self._target_item(code))
        self._append_log("Tüm kuyruğun hedef dili güncellendi.")
        self._update_queue_summary()

    def _remove_selected_queue(self) -> None:
        model = self.queue_table.selectionModel()
        if model is None:
            return
        rows = sorted((index.row() for index in model.selectedRows()), reverse=True)
        for row in rows:
            self.queue_table.removeRow(row)
        self._update_queue_summary()
    def _clear_queue(self) -> None:
        if self._is_busy():
            return
        self.queue_table.setRowCount(0)
        self._update_queue_summary()

    def _update_queue_summary(self) -> None:
        count = self.queue_table.rowCount()
        if count == 0:
            self.queue_summary.setText(
                "Kuyruk boş. İş seçenekleri 'Video' sekmesinden alınır."
            )
        else:
            languages = {self._queue_target(row) for row in range(count)}
            self.queue_summary.setText(
                f"{count} dosya sırada ({len(languages)} farklı hedef dil). "
                "Modeller bir kez yüklenir; aynı video tekrar işlenirse "
                "transkript önbellekten alınır."
            )

    def _queue_paths(self) -> list[str]:
        paths: list[str] = []
        for row in range(self.queue_table.rowCount()):
            item = self.queue_table.item(row, 0)
            if item is not None:
                paths.append(item.data(Qt.UserRole))
        return paths

    def _queue_jobs(self) -> list:
        """Kuyruk satırlarından iş listesi (her satır kendi hedef diliyle)."""
        jobs = []
        for row in range(self.queue_table.rowCount()):
            item = self.queue_table.item(row, 0)
            if item is None:
                continue
            path = item.data(Qt.UserRole)
            jobs.append(self._base_settings(input_path=path, target_lang=self._queue_target(row)))
        return jobs

    def _start_queue(self) -> None:
        if self._is_busy():
            return
        paths = self._queue_paths()
        if not paths:
            QMessageBox.information(self, "Kuyruk boş", "Lütfen önce kuyruğa video ekleyin.")
            return
        if not self._preflight():
            return

        self._save_settings()
        jobs = self._queue_jobs()
        for row in range(self.queue_table.rowCount()):
            self._set_queue_status(row, "Bekliyor", "—")

        self._reset_run_ui()
        self._batch = BatchWorker(jobs, models=self._model_cache)
        self._batch.log.connect(self._append_log)
        self._batch.stage_changed.connect(self.stage_label.setText)
        self._batch.progress_changed.connect(self.progress.setValue)
        self._batch.language_detected.connect(self._on_language)
        self._batch.preview_requested.connect(self._on_preview_batch)
        self._batch.item_started.connect(self._on_item_started)
        self._batch.item_finished.connect(self._on_item_finished)
        self._batch.item_failed.connect(self._on_item_failed)
        self._batch.item_cancelled.connect(self._on_item_cancelled)
        self._batch.batch_finished.connect(self._on_batch_finished)
        self._batch.all_cancelled.connect(self._on_cancelled)
        self._set_busy(True)
        self._append_log(f"Kuyruk başlatıldı: {len(jobs)} dosya.")
        self._batch.start()

    def _set_queue_status(self, row: int, status: str, output: str = "—") -> None:
        if 0 <= row < self.queue_table.rowCount():
            status_item = QTableWidgetItem(status)
            if status == "Tamamlandı":
                status_item.setForeground(QColor("#15803d"))
            elif status == "Hata":
                status_item.setForeground(QColor("#b91c1c"))
            elif status == "İşleniyor":
                status_item.setForeground(QColor("#2563eb"))
            self.queue_table.setItem(row, 2, status_item)
            if output != "—":
                self.queue_table.setItem(row, 3, QTableWidgetItem(output))

    def _on_item_started(self, index: int, path: str) -> None:
        self._set_queue_status(index, "İşleniyor")
        self._append_log(f"[{index + 1}] Başladı: {Path(path).name}")
        self.queue_table.selectRow(index)

    def _on_item_finished(self, index: int, video: str, srt: str, summary: str) -> None:
        output = Path(video).name if video else Path(srt).name
        self._set_queue_status(index, "Tamamlandı", output)
        self._last_video = video
        self._last_srt = srt
        self._append_log(f"[{index + 1}] Tamamlandı: {output}")

    def _on_item_failed(self, index: int, message: str) -> None:
        self._set_queue_status(index, "Hata", "—")
        self._last_error = message
        self._append_log(f"[{index + 1}] HATA: {message}")

    def _on_item_cancelled(self, index: int) -> None:
        self._set_queue_status(index, "İptal edildi", "—")

    def _on_batch_finished(self, ok: int, failed: int, elapsed: str) -> None:
        self._set_busy(False)
        self.stage_label.setText(f"Kuyruk bitti — {ok} başarılı, {failed} hatalı")
        self.progress.setValue(100)
        self.open_output_button.setEnabled(True)
        self._append_log(f"Kuyruk tamamlandı: {ok} başarılı, {failed} hatalı, süre {elapsed}.")

        box = QMessageBox(self)
        box.setWindowTitle("Kuyruk tamamlandı")
        box.setIcon(QMessageBox.Information if failed == 0 else QMessageBox.Warning)
        box.setText(
            f"Başarılı: {ok}\nHatalı: {failed}\nSüre: {elapsed}"
            + ("\n\nHata ayrıntıları log panelinde." if failed else "")
        )
        open_button = box.addButton("Klasörü Aç", QMessageBox.AcceptRole)
        report_button = box.addButton("Hata Raporu", QMessageBox.ActionRole)
        box.addButton("Kapat", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_button:
            self._open_output_folder()
        elif box.clickedButton() is report_button:
            self._copy_report()

    # ------------------------------------------------------------------
    # SRT sekmesi
    # ------------------------------------------------------------------
    def _choose_srt_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "SRT dosyası seçin", "", SRT_FILTER)
        if path:
            self._set_srt_input(path)

    def _set_srt_input(self, path: str) -> None:
        if Path(path).suffix.lower() != ".srt":
            QMessageBox.warning(self, "Desteklenmeyen dosya", "Lütfen bir .srt dosyası seçin.")
            return
        self._srt_input = path
        self.srt_file_label.setText(path)
        self.srt_file_label.setStyleSheet("")
        self.srt_drop.set_text(f"Seçili altyazı:\n{Path(path).name}")
        self._append_log(f"SRT seçildi: {path}")

    def _choose_srt_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Video seçin", "", VIDEO_FILTER)
        if path and Path(path).suffix.lower() in SUPPORTED_EXTENSIONS:
            self._srt_video = path
            self.srt_video_label.setText(path)
            self.srt_video_label.setStyleSheet("")
            self._append_log(f"SRT için video seçildi: {path}")

    # ------------------------------------------------------------------
    # Durum / sonuc
    # ------------------------------------------------------------------
    def _reset_run_ui(self) -> None:
        self.progress.setValue(0)
        self.detected_label.setText("Tespit edilen dil: —")
        self.stage_label.setText("Hazır")
        self._last_error = ""

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (
            self.start_button,
            self.queue_start_button,
            self.srt_start_button,
            self.model_combo,
            self.target_combo,
            self.srt_target_combo,
            self.srt_output_combo,
            self.radio_burn,
            self.radio_soft,
            self.radio_srt,
            self.engine_check_button,
            self.ffmpeg_choose_button,
            self.cache_delete_button,
            self.cache_refresh_button,
            self.queue_apply_target,
            self.queue_apply_all,
            self.cache_clear_button,
        ):
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.queue_stop_button.setEnabled(busy)
        self.ffmpeg_download_button.setEnabled(not busy and ffmpeg_bootstrap.find_existing(self._ffmpeg_path or None) is None)
        if busy:
            self.style_box.setEnabled(False)
            self.open_output_button.setEnabled(False)
        else:
            self._update_style_enabled()

    def _cancel_current(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self.cancel_button.setEnabled(False)
            self.stage_label.setText("İptal ediliyor…")
            self._worker.cancel()
        if self._batch is not None and self._batch.isRunning():
            self.queue_stop_button.setEnabled(False)
            self.stage_label.setText("İptal ediliyor…")
            self._batch.cancel_all()

    def _on_language(self, code: str, label: str, confidence: float) -> None:
        self.detected_label.setText(
            f"Tespit edilen dil: {label} ({code or '?'}) — güven: %{confidence * 100:.1f}"
        )

    # ------------------------------------------------------------------
    # Altyazı önizlemesi (render öncesi onay)
    # ------------------------------------------------------------------
    def _preview_skipped(self) -> bool:
        """Kullanıcı 'bir daha sorma' dedi mi?"""
        return self._settings.value("skip_preview", False, bool)

    def _show_preview(self, srt_path: str, summary: str, index: int | None = None) -> tuple[bool, bool]:
        """Diyaloğu gösterir; (devam, sadece_srt) döndürür."""
        from PySide6.QtWidgets import QDialog

        from subtitle_preview import SubtitlePreviewDialog

        if self._preview_skipped():
            return (True, False)

        dialog = SubtitlePreviewDialog(srt_path, summary, self)
        result = dialog.exec()
        if dialog.dont_ask_again:
            self._settings.setValue("skip_preview", True)
            self._append_log("Bir daha sorma seçildi; sonraki işlerde önizleme atlanacak.")
        if result != QDialog.DialogCode.Accepted:
            return (False, False)
        return (True, dialog.skip_video)

    def _on_preview_single(self, srt_path: str, summary: str) -> None:
        worker = self._worker
        if worker is None:
            return
        self._append_log(f"Altyazı önizlemesi: {Path(srt_path).name}")
        proceed, only_srt = self._show_preview(srt_path, summary)
        if not proceed:
            self._append_log("Önizlemede vazgeçildi.")
        elif only_srt:
            self._append_log("Yalnızca .srt üretilecek.")
        worker.submit_preview_result(proceed, only_srt)

    def _on_preview_batch(self, index: int, srt_path: str, summary: str) -> None:
        batch = self._batch
        if batch is None:
            return
        self._append_log(f"[{index + 1}] Altyazı önizlemesi: {Path(srt_path).name}")
        proceed, only_srt = self._show_preview(srt_path, summary, index)
        if not proceed:
            self._append_log(f"[{index + 1}] Önizlemede vazgeçildi.")
        elif only_srt:
            self._append_log(f"[{index + 1}] Yalnızca .srt üretilecek.")
        batch.submit_preview_result(proceed, only_srt)

    def _on_finished(self, video: str, srt: str, summary: str) -> None:
        self._last_video = video
        self._last_srt = srt
        self._set_busy(False)
        self.progress.setValue(100)
        self.stage_label.setText("Tamamlandı")
        self.open_output_button.setEnabled(True)
        self._append_log("İşlem tamamlandı.")

        lines = [summary, ""]
        if video:
            lines.append(f"Video: {video}")
        lines.append(f"Altyazı: {srt}")
        box = QMessageBox(self)
        box.setWindowTitle("Tamamlandı")
        box.setIcon(QMessageBox.Information)
        box.setText("\n".join(lines))
        open_button = box.addButton("Klasörü Aç", QMessageBox.AcceptRole)
        box.addButton("Kapat", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_button:
            self._open_output_folder()

    def _on_failed(self, message: str) -> None:
        self._set_busy(False)
        self.stage_label.setText("Hata")
        self._last_error = message
        self._append_log(f"HATA: {message}")

        box = QMessageBox(self)
        box.setWindowTitle("İşlem başarısız")
        box.setIcon(QMessageBox.Critical)
        box.setText(message)
        report_button = box.addButton("Hata Raporunu Kopyala", QMessageBox.AcceptRole)
        box.addButton("Kapat", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is report_button:
            self._copy_report()

    def _on_cancelled(self) -> None:
        self._set_busy(False)
        self.progress.setValue(0)
        self.stage_label.setText("İptal edildi")
        self._append_log("İşlem iptal edildi, geçici dosyalar temizlendi.")

    # ------------------------------------------------------------------
    # Rapor / klasor
    # ------------------------------------------------------------------
    def _build_report(self) -> str:
        return error_report.build_report(
            error_text=self._last_error or None,
            settings=self._settings,
            extra=self.log_view.toPlainText()[-4000:] or None,
        )

    def _copy_report(self) -> None:
        from PySide6.QtWidgets import QApplication

        report = self._build_report()
        QApplication.clipboard().setText(report)
        self._append_log("Hata raporu panoya kopyalandı.")
        QMessageBox.information(
            self,
            "Kopyalandı",
            "Hata raporu panoya kopyalandı. Bir destek talebine yapıştırabilirsiniz.",
        )

    def _save_report(self) -> None:
        default = str(app_paths.data_dir() / "hata-raporu.txt")
        path, _ = QFileDialog.getSaveFileName(
            self, "Raporu kaydet", default, "Metin dosyası (*.txt);;Tüm dosyalar (*.*)"
        )
        if not path:
            return
        try:
            error_report.save_report(self._build_report(), path)
            self._append_log(f"Rapor kaydedildi: {path}")
            QMessageBox.information(self, "Kaydedildi", f"Rapor kaydedildi:\n{path}")
        except OSError as exc:
            QMessageBox.critical(self, "Kaydedilemedi", str(exc))

    def _open_logs(self) -> None:
        _open_folder(app_paths.logs_dir())

    def _open_output_folder(self) -> None:
        target = self._last_video or self._last_srt
        if not target:
            paths = self._queue_paths()
            if paths:
                target = paths[0]
        if not target:
            target = getattr(self, "_single_input", "")
        if target:
            _open_folder(Path(target).parent)

    # ------------------------------------------------------------------
    # Kapatma
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        if self._is_busy():
            answer = QMessageBox.question(
                self,
                "İşlem sürüyor",
                "Devam eden bir işlem var. İptal edip çıkmak istiyor musunuz?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self._cancel_current()
            if self._worker is not None:
                self._worker.wait(20000)
            if self._batch is not None:
                self._batch.wait(20000)

        self.killTimer(self._log_timer)
        self._save_settings()
        try:
            self._model_cache.release_all()
        except Exception:
            pass
        event.accept()


# --------------------------------------------------------------------------
# Modul yardimcilari
# --------------------------------------------------------------------------

def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _open_folder(path: str | Path) -> None:
    target = Path(path)
    if not target.exists():
        target = target.parent
    try:
        os.startfile(str(target))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
