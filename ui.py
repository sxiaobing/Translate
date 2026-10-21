"""Main PySide6 user interface."""

from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from capture import select_and_capture
from ocr import OcrError, recognize_text, warm_up_ocr
from translator import TARGET_LANGUAGES, TranslatorError, translate_text_stream


class _OcrWarmupWorker(QThread):
    ready = Signal()
    failed = Signal(str)

    def run(self) -> None:
        try:
            warm_up_ocr()
        except OcrError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # defensive boundary for backend errors
            self.failed.emit(f"OCR 预热失败：{exc}")
        else:
            self.ready.emit()


class _PipelineWorker(QThread):
    recognized = Signal(str)
    translated_delta = Signal(str)
    succeeded = Signal(str, str)
    failed = Signal(str, str)

    def __init__(self, image: Image.Image, target_language: str) -> None:
        super().__init__()
        self.image = image
        self.target_language = target_language

    def run(self) -> None:
        try:
            original = recognize_text(self.image)
        except OcrError as exc:
            self.failed.emit("", str(exc))
            return
        except Exception as exc:  # defensive boundary for backend errors
            self.failed.emit("", f"OCR 处理失败：{exc}")
            return
        self.recognized.emit(original)
        try:
            translated = translate_text_stream(
                original,
                self.target_language,
                self.translated_delta.emit,
            )
        except TranslatorError as exc:
            self.failed.emit(original, str(exc))
            return
        except Exception as exc:
            self.failed.emit(original, f"翻译处理失败：{exc}")
            return
        self.succeeded.emit(original, translated)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("截图翻译")
        self.resize(860, 620)
        self._worker: _PipelineWorker | None = None
        self._warmup_worker: _OcrWarmupWorker | None = None
        self._closing = False
        self._build_ui()
        QTimer.singleShot(0, self._start_ocr_warmup)

    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        toolbar = QHBoxLayout()
        self.capture_button = QPushButton("框选并翻译")
        self.capture_button.clicked.connect(self._capture_and_translate)
        toolbar.addWidget(self.capture_button)
        toolbar.addWidget(QLabel("目标语言："))
        self.language_combo = QComboBox()
        self.language_combo.addItems(list(TARGET_LANGUAGES.keys()))
        self.language_combo.setCurrentText("简体中文")
        toolbar.addWidget(self.language_combo)
        toolbar.addStretch(1)
        self.copy_button = QPushButton("复制译文")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self._copy_translation)
        toolbar.addWidget(self.copy_button)
        root.addLayout(toolbar)

        self.status_label = QLabel("正在准备本地识别引擎……")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        original_label = QLabel("识别原文")
        root.addWidget(original_label)
        self.original_edit = QPlainTextEdit()
        self.original_edit.setReadOnly(True)
        self.original_edit.setPlaceholderText("框选区域后，识别到的文字会显示在这里。")
        self.original_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.original_edit, 1)

        translated_label = QLabel("翻译结果")
        root.addWidget(translated_label)
        self.translation_edit = QPlainTextEdit()
        self.translation_edit.setReadOnly(True)
        self.translation_edit.setPlaceholderText("译文会显示在这里。")
        self.translation_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.translation_edit, 1)
        self.setCentralWidget(central)

    def _start_ocr_warmup(self) -> None:
        if self._warmup_worker is not None:
            return
        self._warmup_worker = _OcrWarmupWorker(self)
        self._warmup_worker.ready.connect(self._on_warmup_ready)
        self._warmup_worker.failed.connect(self._on_warmup_failed)
        self._warmup_worker.finished.connect(self._on_warmup_finished)
        self._warmup_worker.start()

    def _on_warmup_ready(self) -> None:
        if self._worker is None:
            self.status_label.setText("准备就绪。")

    def _on_warmup_failed(self, message: str) -> None:
        if self._worker is None:
            self.status_label.setText(f"{message} 首次识别时将重试。")

    def _capture_and_translate(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.capture_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.original_edit.clear()
        self.translation_edit.clear()
        self.status_label.setText("请拖动鼠标框选文字区域，按 Esc 可取消。")
        self.showMinimized()
        try:
            image, error = select_and_capture()
        except Exception as exc:
            image, error = None, f"截图失败：{exc}"
        finally:
            self.showNormal()
            self.raise_()
            self.activateWindow()
        if image is None:
            self.capture_button.setEnabled(True)
            self.status_label.setText(error or "已取消框选。")
            return
        self.status_label.setText("正在识别文字，请稍候……")
        self._worker = _PipelineWorker(image, self.language_combo.currentText())
        self._worker.recognized.connect(self._on_recognized)
        self._worker.translated_delta.connect(self._on_translated_delta)
        self._worker.succeeded.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_recognized(self, original: str) -> None:
        self.original_edit.setPlainText(original)
        self.status_label.setText("识别完成，正在翻译……")

    def _on_translated_delta(self, delta: str) -> None:
        self.translation_edit.moveCursor(QTextCursor.MoveOperation.End)
        self.translation_edit.insertPlainText(delta)
        self.copy_button.setEnabled(True)

    def _on_success(self, original: str, translated: str) -> None:
        self.original_edit.setPlainText(original)
        self.translation_edit.setPlainText(translated)
        self.copy_button.setEnabled(bool(translated.strip()))
        self.status_label.setText("翻译完成。")

    def _on_failure(self, original: str, message: str) -> None:
        if original:
            self.original_edit.setPlainText(original)
        partial = self.translation_edit.toPlainText().strip()
        if partial:
            self.translation_edit.setPlainText(f"{partial}\n\n{message}")
            self.copy_button.setEnabled(True)
            self.status_label.setText("翻译中断，已保留部分译文。")
        else:
            self.translation_edit.setPlainText(message)
            self.copy_button.setEnabled(False)
            self.status_label.setText("处理未完成，请根据提示处理后重试。")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt callback name
        running = [
            worker
            for worker in (self._worker, self._warmup_worker)
            if worker is not None and worker.isRunning()
        ]
        if running:
            event.ignore()
            if not self._closing:
                self._closing = True
                self.capture_button.setEnabled(False)
                self.status_label.setText("正在完成后台任务，随后退出……")
                for worker in running:
                    worker.finished.connect(self._quit_after_workers_stop)
            return
        super().closeEvent(event)

    def _quit_after_workers_stop(self) -> None:
        if self._closing and not any(
            worker is not None and worker.isRunning()
            for worker in (self._worker, self._warmup_worker)
        ):
            self.close()

    def _on_worker_finished(self) -> None:
        self.capture_button.setEnabled(True)
        worker = self.sender()
        if isinstance(worker, QThread):
            worker.deleteLater()
        self._worker = None
        if self._closing:
            QTimer.singleShot(0, self._quit_after_workers_stop)

    def _on_warmup_finished(self) -> None:
        worker = self.sender()
        if isinstance(worker, QThread):
            worker.deleteLater()
        self._warmup_worker = None
        if self._closing:
            QTimer.singleShot(0, self._quit_after_workers_stop)

    def _copy_translation(self) -> None:
        text = self.translation_edit.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.status_label.setText("译文已复制到剪贴板。")
