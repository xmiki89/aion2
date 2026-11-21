"""Custom painted widgets: roster rows, stat cards, back-hit bar, skill table."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .engine import MemberStat, Snapshot


def fmt(value: float | int) -> str:
    return f"{int(round(value)):,}"


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _font(size: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont("Segoe UI")
    font.setPointSizeF(size)
    font.setWeight(weight)
    return font


# --------------------------------------------------------------------- roster row


class RosterRow(QWidget):
    clicked = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._data: dict | None = None
        self._hover = False

    def set_data(self, data: dict) -> None:
        self._data = data
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802, ANN001
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802, ANN001
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._data and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._data["key"])

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        data = self._data
        if not data:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        height = self.height()
        radius = 8.0
        base_rect = QRectF(0.8, 0.8, width - 1.6, height - 1.6)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1D1D22" if not self._hover else "#22222A"))
        painter.drawRoundedRect(base_rect, radius, radius)

        color = QColor(data["color"])
        fill_width = max(0.0, (width - 3.0) * float(data["fill"]))
        if fill_width > 3:
            alpha = 120 if data["selected"] else (86 if self._hover else 66)
            gradient = QLinearGradient(1, 0, max(fill_width, 2), 0)
            gradient.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), alpha))
            gradient.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), int(alpha * 0.42)))
            painter.setBrush(gradient)
            painter.drawRoundedRect(QRectF(1.5, 1.5, fill_width, height - 3), radius - 1, radius - 1)

        if data["selected"]:
            pen = QPen(QColor("#4C6FFF"))
            pen.setWidthF(1.4)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(base_rect, radius, radius)

        rank_font = _font(8.5)
        name_font = _font(9.8, QFont.Weight.DemiBold)
        class_font = _font(9.2)
        number_font = _font(9.2)
        dps_font = _font(9.6, QFont.Weight.DemiBold)

        right = width - 14
        share_width = 46
        dps_width = 100
        dmg_width = 92
        share_x = right - share_width
        dps_x = share_x - 16 - dps_width
        dmg_x = dps_x - 12 - dmg_width

        text_main = QColor("#FFFFFF" if data["selected"] else "#E9EAEF")
        text_muted = QColor("#C7CAD3" if not data["selected"] else "#E4E7F2")

        painter.setFont(rank_font)
        painter.setPen(QColor("#9A9DA6" if not data["selected"] else "#D6DAE6"))
        painter.drawText(
            QRectF(12, 0, 18, height),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            str(data["rank"]),
        )

        painter.setBrush(QColor(data["color"]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(37, height / 2 - 3.6, 7.2, 7.2))

        painter.setFont(name_font)
        painter.setPen(text_main)
        name_metrics = QFontMetrics(name_font)
        name_text = name_metrics.elidedText(data["name"], Qt.TextElideMode.ElideRight, 150)
        name_width = name_metrics.horizontalAdvance(name_text)
        painter.drawText(
            QRectF(50, 0, name_width + 2, height),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            name_text,
        )

        painter.setFont(class_font)
        painter.setPen(text_muted)
        class_text = f"{data['cls']} · {data['role']}"
        available = int(dmg_x - (50 + name_width + 12))
        if available > 20:
            class_metrics = QFontMetrics(class_font)
            painter.drawText(
                QRectF(50 + name_width + 10, 0, available, height),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                class_metrics.elidedText(class_text, Qt.TextElideMode.ElideRight, available),
            )

        painter.setFont(number_font)
        painter.setPen(text_main)
        painter.drawText(
            QRectF(dmg_x, 0, dmg_width, height),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            fmt(data["metric"]),
        )

        value = fmt(data["dps"])
        suffix = " /s"
        value_font = QFont(dps_font)
        suffix_font = _font(8.2)
        value_width = QFontMetrics(value_font).horizontalAdvance(value)
        suffix_width = QFontMetrics(suffix_font).horizontalAdvance(suffix)
        start = dps_x + dps_width - value_width - suffix_width
        painter.setFont(value_font)
        painter.setPen(QColor("#FFFFFF" if data["selected"] else "#F2F3F6"))
        painter.drawText(
            QRectF(start, 0, value_width + 1, height),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            value,
        )
        painter.setFont(suffix_font)
        painter.setPen(QColor("#A9ADB8" if not data["selected"] else "#D6DAE6"))
        painter.drawText(
            QRectF(start + value_width, 0, suffix_width + 1, height),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            suffix,
        )

        painter.setFont(number_font)
        painter.setPen(text_muted)
        painter.drawText(
            QRectF(share_x, 0, share_width, height),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            pct(data["share"]),
        )


# ------------------------------------------------------------------ stat elements


class StatCard(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setMinimumHeight(74)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("statTitle")
        self.value = QLabel("—")
        self.value.setObjectName("statValue")
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addStretch(1)

    def set_value(self, text: str) -> None:
        self.value.setText(text)


class SegmentBar(QWidget):
    """Blue back-hit share + gold front/flank remainder."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(10)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._share = 0.0

    def set_share(self, share: float) -> None:
        self._share = max(0.0, min(1.0, share))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = float(self.width())
        height = float(self.height())
        radius = height / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#D9BE7E"))
        painter.drawRoundedRect(QRectF(0, 0, width, height), radius, radius)
        back_width = max(height, width * self._share)
        if back_width > 0:
            painter.setBrush(QColor("#4C7DF0"))
            painter.drawRoundedRect(QRectF(0, 0, back_width, height), radius, radius)


# ------------------------------------------------------------------- skill table

_COLUMNS = (
    ("Skill", 0, Qt.AlignmentFlag.AlignLeft),
    ("Hits ▲", 62, Qt.AlignmentFlag.AlignRight),
    ("Damage ▼", 104, Qt.AlignmentFlag.AlignRight),
    ("Share ▲", 70, Qt.AlignmentFlag.AlignRight),
    ("BACK % ▲", 84, Qt.AlignmentFlag.AlignRight),
    ("MULT % ▲", 80, Qt.AlignmentFlag.AlignRight),
)


class SkillTable(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(210)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.rows: list[list[str]] = []
        self.offset = 0

    def set_rows(self, rows: list[list[str]]) -> None:
        self.rows = rows
        self.offset = min(self.offset, max(0, len(rows) - self._visible_rows()))
        self.update()

    def _row_height(self) -> int:
        return 34

    def _header_height(self) -> int:
        return 30

    def _visible_rows(self) -> int:
        space = self.height() - self._header_height()
        return max(0, space // self._row_height())

    def wheelEvent(self, event) -> None:  # noqa: N802, ANN001
        delta = -1 if event.angleDelta().y() > 0 else 1
        max_offset = max(0, len(self.rows) - self._visible_rows())
        new_offset = max(0, min(max_offset, self.offset + delta))
        if new_offset != self.offset:
            self.offset = new_offset
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        header_h = self._header_height()
        row_h = self._row_height()

        positions: list[tuple[str, int, int, Qt.AlignmentFlag]] = []
        cursor = width - 4
        for index in range(len(_COLUMNS) - 1, 0, -1):
            label, col_width, align = _COLUMNS[index]
            positions.append((label, cursor - col_width, col_width, align))
            cursor -= col_width
        positions.append((_COLUMNS[0][0], 2, max(0, cursor - 2), _COLUMNS[0][2]))
        positions.reverse()

        header_font = _font(8.6)
        painter.setFont(header_font)
        painter.setPen(QColor("#8C8F99"))
        for label, x, w, align in positions:
            painter.drawText(
                QRectF(x, 0, w, header_h),
                int(align | Qt.AlignmentFlag.AlignVCenter),
                label,
            )

        separator = QColor("#222227")
        painter.setPen(QPen(separator, 1))

        if not self.rows:
            painter.setFont(_font(9.5))
            painter.setPen(QColor("#6F727C"))
            painter.drawText(
                QRectF(0, header_h, width, row_h * 2),
                int(Qt.AlignmentFlag.AlignCenter),
                "Nessun dato di combattimento",
            )
        else:
            body_font = _font(9.5)
            painter.setFont(body_font)
            for index in range(self.offset, min(len(self.rows), self.offset + self._visible_rows())):
                row = self.rows[index]
                top = header_h + (index - self.offset) * row_h
                painter.setPen(QPen(separator, 1))
                painter.drawLine(0, top + row_h, width, top + row_h)
                for col, (label, x, w, align) in enumerate(positions):
                    text = row[col] if col < len(row) else ""
                    painter.setPen(QColor("#E9EAEE" if col == 0 else "#D6D9E0"))
                    painter.drawText(
                        QRectF(x, top, w, row_h),
                        int(align | Qt.AlignmentFlag.AlignVCenter),
                        text,
                    )


# ------------------------------------------------------------------- roster page


class RosterPage(QWidget):
    player_clicked = pyqtSignal(str)
    tab_selected = pyqtSignal(str)
    merge_changed = pyqtSignal(bool)
    brawler_changed = pyqtSignal(bool)
    update_clicked = pyqtSignal()
    overlay_toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.selected_key: str | None = None
        self.rows: list[RosterRow] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # --- summary card
        header = QFrame()
        header.setObjectName("card")
        header.setFixedHeight(74)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 9, 18, 12)
        header_layout.setSpacing(20)

        self.total_value = QLabel("0")
        self.total_value.setObjectName("cardValue")
        self.dps_value = QLabel("0")
        self.dps_value.setObjectName("cardValue")
        self.dps_value.setTextFormat(Qt.TextFormat.RichText)
        self.roster_value = QLabel("0 Global Classes")
        self.roster_value.setObjectName("cardValue")

        for label_text, value_widget in (
            ("Total Party Damage", self.total_value),
            ("Combined Party DPS", self.dps_value),
            ("Active Roster", self.roster_value),
        ):
            column = QVBoxLayout()
            column.setSpacing(3)
            label = QLabel(label_text)
            label.setObjectName("cardLabel")
            column.addWidget(label)
            column.addWidget(value_widget)
            header_layout.addLayout(column, 1)

        root.addWidget(header)

        # --- tabs
        tab_row = QHBoxLayout()
        tab_row.setSpacing(0)
        tab_bar = QFrame()
        tab_bar.setObjectName("tabBar")
        tab_bar.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        tab_layout = QHBoxLayout(tab_bar)
        tab_layout.setContentsMargins(5, 5, 5, 5)
        tab_layout.setSpacing(2)

        self.tab_buttons: dict[str, QPushButton] = {}
        for key, text in (
            ("damage", "Damage Done"),
            ("healing", "Healing Done"),
            ("taken", "Damage Taken"),
        ):
            button = QPushButton(text)
            button.setObjectName("tab")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, k=key: self.select_tab(k))
            tab_layout.addWidget(button)
            self.tab_buttons[key] = button
        self.tab_buttons["damage"].setChecked(True)

        tab_row.addWidget(tab_bar)
        tab_row.addStretch(1)
        root.addLayout(tab_row)

        # --- chips
        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        self.brawler_chip = QPushButton("Include Brawler (KR/TW)")
        self.brawler_chip.setObjectName("chip")
        self.brawler_chip.setCheckable(True)
        self.brawler_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.brawler_chip.toggled.connect(self.brawler_changed.emit)

        self.merge_chip = QPushButton("Merge Pet Damage")
        self.merge_chip.setObjectName("chip")
        self.merge_chip.setCheckable(True)
        self.merge_chip.setChecked(True)
        self.merge_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.merge_chip.toggled.connect(self.merge_changed.emit)

        self.overlay_chip = QPushButton("Overlay")
        self.overlay_chip.setObjectName("chip")
        self.overlay_chip.setCheckable(True)
        self.overlay_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.overlay_chip.setToolTip("Mostra il meter sopra il gioco (Ctrl+Shift+O)")
        self.overlay_chip.toggled.connect(self.overlay_toggled.emit)

        self.you_label = QLabel("Tu: in attesa")
        self.you_label.setObjectName("youChip")

        self.update_button = QPushButton("Aggiorna")
        self.update_button.setObjectName("updateChip")
        self.update_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_button.setVisible(False)
        self.update_button.clicked.connect(self.update_clicked.emit)

        self.badge = QLabel("DEMO")
        self.badge.setObjectName("badgeDemo")

        chip_row.addWidget(self.brawler_chip)
        chip_row.addWidget(self.merge_chip)
        chip_row.addWidget(self.overlay_chip)
        chip_row.addWidget(self.you_label)
        chip_row.addStretch(1)
        chip_row.addWidget(self.update_button)
        chip_row.addWidget(self.badge)
        root.addLayout(chip_row)

        # --- rows
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.viewport().setStyleSheet("background: transparent;")
        holder = QWidget()
        holder.setAutoFillBackground(False)
        holder.setStyleSheet("background: transparent;")
        self.rows_layout = QVBoxLayout(holder)
        self.rows_layout.setContentsMargins(0, 0, 4, 0)
        self.rows_layout.setSpacing(8)
        self.rows_layout.addStretch(1)
        self.scroll.setWidget(holder)
        root.addWidget(self.scroll, 1)

        # --- empty state (nothing detected yet)
        self.empty_widget = QWidget()
        empty_layout = QVBoxLayout(self.empty_widget)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.setSpacing(0)
        empty_layout.addStretch(1)
        self.empty_title = QLabel("In attesa di Aion 2")
        self.empty_title.setObjectName("emptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_sub = QLabel(
            "Apri il gioco: quando viene rilevato il personaggio vedrai la classe, e i membri "
            "che entrano nel dungeon compariranno qui da soli."
        )
        self.empty_sub.setObjectName("emptySub")
        self.empty_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_sub.setWordWrap(True)
        self.empty_hint = QLabel("")
        self.empty_hint.setObjectName("emptyHint")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setWordWrap(True)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addSpacing(6)
        empty_layout.addWidget(self.empty_sub)
        empty_layout.addSpacing(12)
        empty_layout.addWidget(self.empty_hint)
        empty_layout.addStretch(1)
        root.addWidget(self.empty_widget, 1)
        self.empty_widget.setVisible(False)

        # --- footer
        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.status_label = QLabel("…")
        self.status_label.setObjectName("status")
        self.meta_label = QLabel("")
        self.meta_label.setObjectName("status")
        footer.addWidget(self.status_label, 1)
        footer.addWidget(self.meta_label)
        root.addLayout(footer)

    # -- interaction
    def select_tab(self, key: str) -> None:
        for name, button in self.tab_buttons.items():
            button.setChecked(name == key)
        self.tab_selected.emit(key)

    def set_selected(self, key: str | None) -> None:
        self.selected_key = key
        for row in self.rows:
            data = row._data  # noqa: SLF001
            if data:
                data["selected"] = data["key"] == key
                row.update()

    def _ensure_rows(self, count: int) -> None:
        while len(self.rows) < count:
            row = RosterRow()
            row.clicked.connect(self.player_clicked.emit)
            self.rows_layout.insertWidget(len(self.rows), row)
            self.rows.append(row)
        for index, row in enumerate(self.rows):
            row.setVisible(index < count)

    # -- rendering
    def set_you(self, text: str) -> None:
        self.you_label.setText(text)

    def set_overlay_checked(self, checked: bool) -> None:
        self.overlay_chip.setChecked(checked)

    def set_update(self, version: str | None, text: str | None = None) -> None:
        if not version:
            self.update_button.setVisible(False)
            return
        self.update_button.setText(text or f"Aggiorna a {version}")
        self.update_button.setVisible(True)

    def set_update_text(self, text: str) -> None:
        self.update_button.setText(text)

    def set_feed_hint(self, text: str) -> None:
        self.empty_hint.setText(text)

    def set_snapshot(self, snap: Snapshot) -> None:
        self.total_value.setText(fmt(snap.total))
        self.dps_value.setText(
            f'{fmt(snap.dps)} <span style="color:#8C8F99;font-size:14px">/s</span>'
        )
        self.roster_value.setText(f"{len(snap.members)} Global Classes")
        self.scroll.setVisible(bool(snap.members))
        self.empty_widget.setVisible(not snap.members)
        self._ensure_rows(len(snap.members))
        for row, member in zip(self.rows, snap.members):
            row.set_data(
                {
                    "key": member.key,
                    "rank": member.rank,
                    "name": member.name,
                    "cls": member.cls,
                    "role": member.role,
                    "color": member.color,
                    "metric": member.metric,
                    "dps": member.dps,
                    "share": member.share,
                    "fill": member.fill,
                    "selected": member.key == self.selected_key,
                }
            )
        self.meta_label.setText(f"{snap.duration:.0f}s di combattimento")

    def set_status(self, text: str, live: bool) -> None:
        self.status_label.setText(text)
        self.badge.setText("LIVE" if live else "DEMO")
        self.badge.setObjectName("badgeLive" if live else "badgeDemo")
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)


# ------------------------------------------------------------------- detail page


class DetailPage(QWidget):
    back_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        top = QHBoxLayout()
        self.back_button = QPushButton("‹   Roster")
        self.back_button.setObjectName("back")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(self.back_requested.emit)
        top.addWidget(self.back_button)
        top.addStretch(1)
        root.addLayout(top)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.dot = QLabel("●")
        self.dot.setStyleSheet("font-size: 11px;")
        self.name = QLabel("—")
        self.name.setObjectName("dName")
        self.spec = QLabel("")
        self.spec.setObjectName("dSpec")
        self.dps_value = QLabel("0")
        self.dps_value.setObjectName("dDps")
        self.dps_meta = QLabel("DPS (0.0%)")
        self.dps_meta.setObjectName("dDpsMeta")

        header.addWidget(self.dot)
        header.addWidget(self.name)
        header.addSpacing(4)
        header.addWidget(self.spec)
        header.addStretch(1)
        header.addWidget(self.dps_value)
        header.addSpacing(3)
        header.addWidget(self.dps_meta)
        root.addLayout(header)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.card_crit = StatCard("Crit Rate")
        self.card_double = StatCard("Double Hit")
        self.card_multi = StatCard("Multi-Hit")
        self.card_back = StatCard("Back Attack")
        for card in (self.card_crit, self.card_double, self.card_multi, self.card_back):
            cards.addWidget(card, 1)
        root.addLayout(cards)

        backhit = QFrame()
        backhit.setObjectName("card")
        backhit_layout = QVBoxLayout(backhit)
        backhit_layout.setContentsMargins(16, 11, 16, 14)
        backhit_layout.setSpacing(9)
        backhit_top = QHBoxLayout()
        self.back_title = QLabel("Back Hit: 0.0%")
        self.back_title.setObjectName("bhTitle")
        self.front_title = QLabel("Front / Flank: 0.0%")
        self.front_title.setObjectName("bhMeta")
        backhit_top.addWidget(self.back_title)
        backhit_top.addStretch(1)
        backhit_top.addWidget(self.front_title)
        backhit_layout.addLayout(backhit_top)
        self.bar = SegmentBar()
        backhit_layout.addWidget(self.bar)
        root.addWidget(backhit)

        self.table = SkillTable()
        root.addWidget(self.table, 1)

    def set_member(self, member: MemberStat) -> None:
        self.dot.setStyleSheet(f"font-size: 11px; color: {member.color};")
        self.name.setText(f"{member.name} — {member.cls}")
        self.spec.setText(f"{member.spec}   ·   {member.role}")
        self.dps_value.setText(fmt(member.dps))
        self.dps_meta.setText(f"DPS ({pct(member.share)})")
        self.card_crit.set_value(pct(member.crit))
        self.card_double.set_value(pct(member.double))
        self.card_multi.set_value(pct(member.multi))
        self.card_back.set_value(pct(member.back))
        self.back_title.setText(f"Back Hit: {pct(member.back)}")
        self.front_title.setText(f"Front / Flank: {pct(max(0.0, 1.0 - member.back))}")
        self.bar.set_share(member.back)
        self.table.set_rows(
            [
                [
                    skill.name,
                    f"{skill.hits:,}",
                    fmt(skill.amount),
                    pct(skill.share),
                    pct(skill.back_pct),
                    pct(skill.mult_pct),
                ]
                for skill in member.skills
            ]
        )
