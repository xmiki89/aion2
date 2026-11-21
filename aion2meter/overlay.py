"""Compact always-on-top overlay that floats above the game."""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path

from PyQt6.QtCore import QPoint, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QMenu, QWidget

from .engine import Snapshot

HEADER_H = 26
ROW_H = 23
PAD = 8
MAX_ROWS = 8


def settings_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Aion2DamageMeter"
    return base / "overlay.json"


def _font(size: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont("Segoe UI")
    font.setPointSizeF(size)
    font.setWeight(weight)
    return font


def fmt(value: float | int) -> str:
    return f"{int(round(value)):,}"


class OverlayWindow(QWidget):
    open_requested = pyqtSignal()
    hidden_by_user = pyqtSignal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle("Aion 2 Damage Meter — Overlay")
        self.setMouseTracking(True)

        self._members: list[dict] = []
        self._total = 0.0
        self._live = False
        self._runtime = 0.0
        self._opacity = 0.92
        self._drag_origin: QPoint | None = None
        self._width = 360
        self.resize(self._width, HEADER_H + ROW_H * MAX_ROWS + PAD * 2)

        # games like to re-stack their own windows: nudge ours back on top periodically
        self._top_timer = QTimer(self)
        self._top_timer.setInterval(2000)
        self._top_timer.timeout.connect(self._keep_on_top)

    # ------------------------------------------------------------------ state
    def load_settings(self) -> None:
        path = settings_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        try:
            x = int(data.get("x", 60))
            y = int(data.get("y", 60))
            self.move(x, y)
        except (TypeError, ValueError):
            pass
        try:
            self.set_opacity_level(float(data.get("opacity", 0.92)))
        except (TypeError, ValueError):
            pass
        try:
            self._width = max(260, min(560, int(data.get("width", 360))))
            self.resize(self._width, self.height())
        except (TypeError, ValueError):
            pass

    def save_settings(self) -> None:
        path = settings_path()
        payload = {
            "x": self.x(),
            "y": self.y(),
            "width": self._width,
            "opacity": round(self._opacity, 2),
            "visible": self.isVisible(),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    def set_opacity_level(self, value: float) -> None:
        self._opacity = max(0.35, min(1.0, value))
        self.setWindowOpacity(self._opacity)
        self.update()

    @property
    def opacity_level(self) -> float:
        return self._opacity

    def set_snapshot(self, snap: Snapshot, live: bool) -> None:
        members = snap.members[:MAX_ROWS]
        data: list[dict] = []
        top = members[0].metric if members else 0
        for member in members:
            data.append(
                {
                    "name": member.name,
                    "cls": member.cls,
                    "role": member.role,
                    "color": member.color,
                    "dps": member.dps,
                    "share": member.share,
                    "fill": (member.metric / top) if top else 0.0,
                    "metric": member.metric,
                }
            )
        changed = (
            data != self._members
            or live != self._live
            or abs(snap.dps - self._total) > 0.5
            or abs(snap.duration - self._runtime) > 0.5
        )
        self._members = data
        self._live = live
        self._total = snap.dps
        self._runtime = snap.duration
        rows = max(1, len(data))
        height = HEADER_H + ROW_H * rows + PAD * 2
        if self.height() != height:
            self.setFixedHeight(height)
        if changed and self.isVisible():
            self.update()

    # ------------------------------------------------------------------ paint
    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = float(self.width())
        height = float(self.height())

        card = QRectF(0.5, 0.5, width - 1, height - 1)
        painter.setPen(QPen(QColor(255, 255, 255, 22), 1))
        painter.setBrush(QColor(14, 15, 18, 232))
        painter.drawRoundedRect(card, 10, 10)

        painter.setFont(_font(7.4, QFont.Weight.DemiBold))
        painter.setPen(QColor(140, 143, 153))
        painter.drawText(
            QRectF(PAD, 4, 160, HEADER_H - 8),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            "AION 2 · DAMAGE",
        )

        dot_color = QColor("#4FD98A") if self._live else QColor("#E7B966")
        painter.setBrush(dot_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(width - PAD - 8, HEADER_H / 2 - 2, 5, 5))

        painter.setFont(_font(8.2, QFont.Weight.DemiBold))
        painter.setPen(QColor("#F2F3F6"))
        painter.drawText(
            QRectF(PAD, 4, width - PAD * 2 - 16, HEADER_H - 8),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            f"{fmt(self._total)} /s",
        )

        if not self._members:
            painter.setFont(_font(8.0))
            painter.setPen(QColor(140, 143, 153))
            painter.drawText(
                QRectF(0, HEADER_H, width, ROW_H),
                int(Qt.AlignmentFlag.AlignCenter),
                "In attesa del combattimento…",
            )
            return

        for index, member in enumerate(self._members):
            top = PAD + HEADER_H + index * ROW_H
            row_rect = QRectF(PAD, top, width - PAD * 2, ROW_H - 3)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 12))
            painter.drawRoundedRect(row_rect, 5, 5)

            color = QColor(member["color"])
            fill_width = max(0.0, row_rect.width() * float(member["fill"]))
            if fill_width > 2:
                gradient = QLinearGradient(row_rect.left(), 0, row_rect.left() + fill_width, 0)
                gradient.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), 110))
                gradient.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 40))
                painter.setBrush(gradient)
                painter.drawRoundedRect(
                    QRectF(row_rect.left(), row_rect.top(), fill_width, row_rect.height()), 5, 5
                )

            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(
                QRectF(row_rect.left() + 6, row_rect.center().y() - 2.4, 4.8, 4.8)
            )

            name_font = _font(8.0, QFont.Weight.DemiBold)
            painter.setFont(name_font)
            painter.setPen(QColor("#FFFFFF"))
            metrics = QFontMetrics(name_font)
            name = metrics.elidedText(member["name"], Qt.TextElideMode.ElideRight, 120)
            painter.drawText(
                QRectF(row_rect.left() + 15, row_rect.top(), 122, row_rect.height()),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                name,
            )

            painter.setFont(_font(7.2))
            painter.setPen(QColor(176, 180, 191))
            class_text = f"{member['cls']} · {member['role']}"
            painter.drawText(
                QRectF(row_rect.left() + 140, row_rect.top(), 96, row_rect.height()),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                QFontMetrics(_font(7.2)).elidedText(class_text, Qt.TextElideMode.ElideRight, 96),
            )

            painter.setFont(_font(7.8, QFont.Weight.DemiBold))
            painter.setPen(QColor("#F2F3F6"))
            painter.drawText(
                QRectF(row_rect.right() - 132, row_rect.top(), 88, row_rect.height()),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"{fmt(member['dps'])}",
            )

            painter.setFont(_font(7.2))
            painter.setPen(QColor(176, 180, 191))
            painter.drawText(
                QRectF(row_rect.right() - 42, row_rect.top(), 36, row_rect.height()),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"{member['share'] * 100:.1f}%",
            )

    # -------------------------------------------------------------- interaction
    def mousePressEvent(self, event) -> None:  # noqa: N802, ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif event.button() == Qt.MouseButton.RightButton:
            self._context_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._drag_origin is not None:
            self._drag_origin = None
            self.save_settings()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802, ANN001
        self.open_requested.emit()

    def wheelEvent(self, event) -> None:  # noqa: N802, ANN001
        step = 0.06 if event.angleDelta().y() > 0 else -0.06
        self.set_opacity_level(self._opacity + step)
        self.save_settings()

    def _context_menu(self, position: QPoint) -> None:  # noqa: C901
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background:#17171C; color:#E9EAEF; border:1px solid #2A2A31; padding:4px; }"
            "QMenu::item { padding:5px 18px; }"
            "QMenu::item:selected { background:#26262E; }"
        )
        menu.addAction("Apri finestra", self.open_requested.emit)
        opacity_menu = menu.addMenu("Trasparenza")
        for label, value in (
            ("100%", 1.0),
            ("90%", 0.9),
            ("80%", 0.8),
            ("70%", 0.7),
            ("55%", 0.55),
        ):
            action = opacity_menu.addAction(label)
            action.triggered.connect(lambda _checked=False, v=value: self._set_opacity_and_save(v))
        menu.addSeparator()
        menu.addAction("Nascondi overlay", self.hide_for_user)
        menu.exec(position)

    def _set_opacity_and_save(self, value: float) -> None:
        self.set_opacity_level(value)
        self.save_settings()

    def showEvent(self, event) -> None:  # noqa: N802, ANN001
        super().showEvent(event)
        self._keep_on_top()
        self._top_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802, ANN001
        self._top_timer.stop()
        super().hideEvent(event)

    def _keep_on_top(self) -> None:
        if os.name != "nt" or not self.isVisible():
            return
        try:
            hwnd = int(self.winId())
            # HWND_TOPMOST + SWP_NOSIZE|SWP_NOMOVE|SWP_NOACTIVATE|SWP_SHOWWINDOW
            ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)
        except (OSError, ValueError, AttributeError):
            pass

    def hide_for_user(self) -> None:
        self.save_settings()
        self.hide()
        self.hidden_by_user.emit()

    def closeEvent(self, event) -> None:  # noqa: N802, ANN001
        self.save_settings()
        super().closeEvent(event)
