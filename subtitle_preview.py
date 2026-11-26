"""Altyazı önizleme ve düzenleme diyaloğu.

Neden: çeviri kötüyse (yanlış terim, bozuk cümle) kullanıcı bunu ancak video
yakıldıktan sonra görüyordu — tekrar işlemek gerekiyordu. Bu diyalog, SRT
diske yazıldıktan ve video render edilmeden ÖNCE düzeltme imkânı verir.

Tasarım:
  * Kuyruk/tek iş akışına `render_cb` kancası ile bağlanır: worker SRT'yi
    yazdıktan sonra durur, callback'ten onay ister.
  * Kullanıcı düzenlerse SRT yeniden yazılır (aynı yol).
  * "Atla" seçilirse yalnızca .srt kalır, video üretilmez.
  * Kalıcı "onay sormadan devam et" seçeneği (ayarlarda saklanır).

Metin biçimi: SRT'nin kendisi düzenlenebilir (zaman damgaları dahil). Böylece
kullanıcı hem metni hem zamanlamayı düzeltebilir; okurken mevcut `read_srt`
kullanılmaz, dosya olduğu gibi gösterilir.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import subtitles as subtitles_mod


class SubtitlePreviewDialog(QDialog):
    """SRT içeriğini gösterir, düzenlemeye izin verir.

    Sonuç:
      exec() -> QDialog.Accepted  : devam et (düzenleme varsa kaydedildi)
             -> QDialog.Rejected  : vazgeç (iş iptal)
      `skip_video`            : True ise yalnızca .srt üret
      `dont_ask_again`        : True ise ayarı güncelle
    """

    def __init__(
        self,
        srt_path: str | Path,
        summary: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Altyazı önizlemesi")
        self.resize(760, 620)

        self.srt_path = Path(srt_path)
        self.skip_video = False
        self.dont_ask_again = False
        self._original = ""
        self._edited = False

        layout = QVBoxLayout(self)

        info = QLabel(
            "Altyazı üretildi. Videoya işlemeden önce kontrol edebilirsiniz.\n"
            "Metni veya zaman damgalarını düzeltebilirsiniz; değişiklikler "
            "kaydedilir."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        if summary:
            summary_label = QLabel(summary.replace("\n", "  |  "))
            summary_label.setStyleSheet("color: #6b7280;")
            summary_label.setWordWrap(True)
            layout.addWidget(summary_label)

        self.editor = QPlainTextEdit()
        font = QFont("Consolas")
        font.setPointSize(9)
        self.editor.setFont(font)
        self.editor.setTabChangesFocus(False)
        layout.addWidget(self.editor, 1)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #b45309;")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        options = QHBoxLayout()
        self.only_srt_check = QCheckBox("Yalnızca .srt üret (videoyu işleme)")
        options.addWidget(self.only_srt_check)
        options.addStretch(1)
        self.dont_ask_check = QCheckBox("Bir daha sorma")
        options.addWidget(self.dont_ask_check)
        layout.addLayout(options)

        self.buttons = QDialogButtonBox()
        self.apply_button = QPushButton("Düzeltmeyi Uygula")
        self.revert_button = QPushButton("Özgün Metne Dön")
        self.continue_button = self.buttons.addButton(
            "Onayla ve Devam Et", QDialogButtonBox.AcceptRole
        )
        self.cancel_button = self.buttons.addButton(
            "Vazgeç", QDialogButtonBox.RejectRole
        )
        self.buttons.addButton(self.apply_button, QDialogButtonBox.ActionRole)
        self.buttons.addButton(self.revert_button, QDialogButtonBox.ActionRole)
        layout.addWidget(self.buttons)

        self.apply_button.clicked.connect(self._apply)
        self.revert_button.clicked.connect(self._revert)
        self.continue_button.clicked.connect(self._accept)
        self.cancel_button.clicked.connect(self.reject)
        self.editor.textChanged.connect(self._on_text_changed)

        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        try:
            self._original = self.srt_path.read_text(encoding="utf-8")
        except OSError as exc:
            self._original = ""
            self.status.setText(f"SRT okunamadı: {exc}")
        self.editor.setPlainText(self._original)
        self._edited = False
        self._update_buttons()

    def _current_text(self) -> str:
        return self.editor.toPlainText().replace("\r\n", "\n").strip()

    def _on_text_changed(self) -> None:
        self._edited = self._current_text() != self._original.strip()
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.apply_button.setEnabled(self._edited)
        self.revert_button.setEnabled(self._edited)
        if self._edited:
            self.status.setText("Kaydedilmemiş değişiklik var — 'Düzeltmeyi Uygula'.")
        else:
            self.status.setText("")

    # ------------------------------------------------------------------
    def _validate(self, text: str) -> tuple[bool, str]:
        """SRT geçerli mi? (boş, zaman damgası, sıralama)"""
        if not text.strip():
            return False, "Altyazı boş olamaz."
        entries = _parse_srt_text(text)
        if not entries:
            return False, (
                "Geçerli altyazı bloğu bulunamadı.\n"
                "Her blokta '00:00:01,000 --> 00:00:02,000' biçiminde bir "
                "zaman satırı olmalı."
            )
        for index, entry in enumerate(entries):
            if entry["end"] <= entry["start"]:
                return False, (
                    f"{index + 1}. blokta bitiş zamanı başlangıçtan önce/sonra değil."
                )
        return True, ""

    def _apply(self) -> None:
        text = self._current_text()
        ok, message = self._validate(text)
        if not ok:
            QMessageBox.warning(self, "Geçersiz altyazı", message)
            return
        try:
            self.srt_path.write_text(text + "\n", encoding="utf-8", newline="\n")
        except OSError as exc:
            QMessageBox.critical(self, "Kaydedilemedi", f"SRT yazılamadı:\n{exc}")
            return

        self._original = text
        self._edited = False
        self._update_buttons()
        self.status.setStyleSheet("color: #15803d;")
        self.status.setText(f"Kaydedildi: {self.srt_path.name}")
        self.status.setStyleSheet("color: #b45309;")

    def _revert(self) -> None:
        self.editor.setPlainText(self._original)

    def _accept(self) -> None:
        text = self._current_text()
        ok, message = self._validate(text)
        if not ok:
            answer = QMessageBox.question(
                self,
                "Geçersiz altyazı",
                f"{message}\n\nYine de devam edilsin mi?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        elif self._edited:
            self._apply()

        self.skip_video = self.only_srt_check.isChecked()
        self.dont_ask_again = self.dont_ask_check.isChecked()
        self.accept()


def _parse_srt_text(text: str) -> list[dict]:
    """Metinden SRT girdilerini çıkarır (dosyaya yazmadan)."""
    import re

    pattern = re.compile(
        r"(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})"
    )
    entries: list[dict] = []
    for match in pattern.finditer(text):
        entries.append(
            {
                "start": subtitles_mod.parse_timestamp(match.group(1)),
                "end": subtitles_mod.parse_timestamp(match.group(2)),
            }
        )
    return entries


def parse_srt_text(text: str) -> list[dict]:
    """Dışa açık yardımcı (testler için)."""
    return _parse_srt_text(text)
