"""Interactive screen selection and capture."""

from __future__ import annotations

from typing import Optional

import mss
from PIL import Image
from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget


class SelectionOverlay(QWidget):
    """A transparent, full-screen drag-to-select overlay."""

    closed = Signal()

    def __init__(self, geometry: QRect) -> None:
        super().__init__()
        self.setGeometry(geometry)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._drag_start: Optional[QPoint] = None
        self._selection = QRect()
        self.cancelled = False

    @property
    def selection(self) -> QRect:
        return self._selection.normalized()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt callback name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 105))
        if not self._selection.isNull():
            # Clear the selected area so the desktop remains visible while dragging.
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(self._selection, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor(40, 150, 255), 2))
            painter.drawRect(self._selection)
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            self._selection = QRect(self._drag_start, self._drag_start)
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_start is not None:
            self._selection = QRect(self._drag_start, event.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start is not None:
            self._selection = QRect(self._drag_start, event.position().toPoint()).normalized()
            self._drag_start = None
            self.update()
            if self._selection.width() < 5 or self._selection.height() < 5:
                self._selection = QRect()
            self.close()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled = True
            self._selection = QRect()
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.closed.emit()
        super().closeEvent(event)


def _selection_to_mss_region(
    selection: QRect,
    device_pixel_ratio: float,
    monitor: dict[str, int],
) -> dict[str, int]:
    """Convert overlay-local Qt logical pixels to MSS physical pixels."""

    ratio = max(device_pixel_ratio, 0.01)
    return {
        "left": monitor["left"] + round(selection.x() * ratio),
        "top": monitor["top"] + round(selection.y() * ratio),
        "width": max(1, round(selection.width() * ratio)),
        "height": max(1, round(selection.height() * ratio)),
    }


def _grab_with_qt(screen, selection: QRect) -> Image.Image:
    """Fallback capture through Qt when the MSS GDI backend is unavailable."""

    pixmap = screen.grabWindow(
        0,
        selection.x(),
        selection.y(),
        selection.width(),
        selection.height(),
    )
    if pixmap.isNull():
        raise RuntimeError("Qt 未能读取屏幕内容")
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
    stride = image.bytesPerLine()
    return Image.frombytes(
        "RGB",
        (image.width(), image.height()),
        bytes(image.constBits()),
        "raw",
        "RGB",
        stride,
    )


def select_and_capture() -> tuple[Image.Image | None, str | None]:
    """Show the overlay and return ``(image, error)``.

    The overlay is closed before MSS captures pixels, so its translucent layer
    cannot appear in the returned image. ``(None, None)`` means the user
    cancelled or selected an area smaller than the minimum size.
    """

    app = QApplication.instance()
    if app is None:
        return None, "无法启动截图界面。"
    screen = app.primaryScreen()
    if screen is None:
        return None, "未找到可用的显示器。"

    overlay = SelectionOverlay(screen.geometry())
    loop = QEventLoop()
    overlay.closed.connect(loop.quit)
    overlay.show()
    overlay.raise_()
    overlay.activateWindow()
    overlay.setFocus()
    loop.exec()

    selection = overlay.selection
    cancelled = overlay.cancelled
    overlay.hide()
    app.processEvents()
    if cancelled or selection.isNull():
        overlay.deleteLater()
        return None, None

    device_pixel_ratio = screen.devicePixelRatio()
    overlay.deleteLater()
    app.processEvents()

    mss_error = None
    try:
        with mss.mss() as sct:
            primary_monitor = next(
                (monitor for monitor in sct.monitors[1:] if monitor.get("is_primary")),
                sct.monitors[1],
            )
            region = _selection_to_mss_region(selection, device_pixel_ratio, primary_monitor)
            shot = sct.grab(region)
        image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        return image, None
    except Exception as exc:  # pragma: no cover - depends on desktop backend
        mss_error = exc

    try:
        return _grab_with_qt(screen, selection), None
    except Exception as exc:  # pragma: no cover - depends on desktop backend
        return None, f"截图失败：{mss_error}；备用截图也失败：{exc}"
