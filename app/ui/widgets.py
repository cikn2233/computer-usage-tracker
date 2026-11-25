from __future__ import annotations

from PyQt6.QtCore import QFileInfo, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFileIconProvider,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

_icon_provider: QFileIconProvider | None = None
_icon_cache: dict[str, QPixmap] = {}


def exe_icon(exe: str, size: int = 16) -> QPixmap:
    """读取 exe 在资源管理器里的真实图标；读不到时回退系统通用文件图标。"""
    global _icon_provider
    key = (exe or "").strip().lower()
    cached = _icon_cache.get(key)
    if cached is not None:
        return cached
    if _icon_provider is None:
        _icon_provider = QFileIconProvider()
    info = QFileInfo(exe) if exe else QFileInfo()
    if exe and info.exists():
        icon = _icon_provider.icon(info)
    else:
        icon = _icon_provider.icon(QFileIconProvider.IconType.File)
    cached = icon.pixmap(32, 32).scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    _icon_cache[key] = cached
    return cached


class RowBackgroundDelegate(QStyledItemDelegate):
    """QSS 样式化 ::item 后 Qt 会忽略模型的 BackgroundRole，这里手动补画行底色。"""

    def paint(self, painter, option, index):
        brush = index.data(Qt.ItemDataRole.BackgroundRole)
        if brush is not None:
            painter.fillRect(option.rect, brush)
        super().paint(painter, option, index)


class StatCard(QFrame):
    def __init__(self, title: str, accent: str = "#3B82F6", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumHeight(108)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        top.addWidget(self.title_label)
        top.addStretch(1)
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background: {accent}; border-radius: 4px;")
        top.addWidget(dot)
        layout.addLayout(top)
        self.value_label = QLabel("—")
        self.value_label.setObjectName("CardValue")
        layout.addWidget(self.value_label)
        self.sub_label = QLabel("")
        self.sub_label.setObjectName("CardSub")
        self.sub_label.setWordWrap(True)
        layout.addWidget(self.sub_label)
        layout.addStretch(1)

    def set_value(self, value: str, sub: str | None = None) -> None:
        self.value_label.setText(value)
        if sub is not None:
            self.sub_label.setText(sub)


class MiniStat(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("MiniCard")
        self.setMinimumHeight(66)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("MiniTitle")
        layout.addWidget(title_label)
        self.value_label = QLabel("—")
        self.value_label.setObjectName("MiniValue")
        layout.addWidget(self.value_label)

    def set_value(self, value: str, color: str | None = None) -> None:
        self.value_label.setText(value)
        self.value_label.setStyleSheet(f"color: {color};" if color else "")


class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("SectionTitle")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("SectionSub")
        if title:
            title_box.addWidget(self.title_label)
        if subtitle:
            title_box.addWidget(self.subtitle_label)
        self.header.addLayout(title_box)
        self.header.addStretch(1)
        outer.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        outer.addLayout(self.body, 1)

    def add_action(self, widget: QWidget) -> None:
        self.header.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        text_box = QVBoxLayout()
        text_box.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("PageTitle")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("PageSub")
        text_box.addWidget(self.title_label)
        text_box.addWidget(self.subtitle_label)
        layout.addLayout(text_box)
        layout.addStretch(1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)


class SegmentedControl(QFrame):
    changed = pyqtSignal(str)

    def __init__(self, options: list[tuple[str, str]], current: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("SegmentBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for value, label in options:
            button = QPushButton(label)
            button.setObjectName("Segment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, v=value: self._on_clicked(v))
            self.group.addButton(button)
            layout.addWidget(button)
            self.buttons[value] = button
        if options:
            self.set_current(current or options[0][0])

    def _on_clicked(self, value: str) -> None:
        self.changed.emit(value)

    def set_current(self, value: str) -> None:
        button = self.buttons.get(value)
        if button is not None:
            button.setChecked(True)

    def current_value(self) -> str:
        for value, button in self.buttons.items():
            if button.isChecked():
                return value
        return next(iter(self.buttons), "")


def make_table(headers: list[str], widths: list[int] | None = None) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(33)
    table.setShowGrid(False)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    table.horizontalHeader().setHighlightSections(False)
    table.horizontalHeader().setDefaultAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    table.horizontalHeader().setStretchLastSection(False)
    for index in range(len(headers)):
        width = widths[index] if widths and index < len(widths) else -1
        if width is None or width < 0:
            table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
        else:
            table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(index, width)
    return table


def make_item(
    text: str,
    color: str | None = None,
    *,
    tooltip: str | None = None,
    align_right: bool = False,
    bold: bool = False,
    background: str | None = None,
) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if color:
        item.setForeground(QColor(color))
    if background:
        item.setBackground(QColor(background))
    if tooltip:
        item.setToolTip(tooltip)
    if align_right:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if bold:
        font: QFont = item.font()
        font.setBold(True)
        item.setFont(font)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


def make_dot(color: str, size: int = 8) -> QLabel:
    dot = QLabel()
    dot.setFixedSize(size, size)
    dot.setStyleSheet(f"background: {color}; border-radius: {size // 2}px;")
    return dot


def hline() -> QFrame:
    from app.ui.theme import current_palette
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {current_palette()['border']}; border: none;")
    return line


class MiniPie(QWidget):
    """轻量手绘环形图，用于侧栏小统计，避免额外 WebView 开销。"""

    def __init__(self, size: int = 120, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self._data: list[tuple[str, float, str]] = []

    def set_data(self, data: list[tuple[str, float, str]]) -> None:
        self._data = [(label, value, color) for label, value, color in data if value > 0]
        self.update()

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        total = sum(v for _, v, _ in self._data)
        rect = QRectF(4, 4, self._size - 8, self._size - 8)
        if total <= 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#E8ECF4"))
            p.drawEllipse(rect)
            p.end()
            return
        start = 90 * 16
        for _label, value, color in self._data:
            span = int(value / total * 360 * 16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawPie(rect, start, -span)
            start -= span
        inner = QRectF(self._size * 0.30, self._size * 0.30, self._size * 0.40, self._size * 0.40)
        from app.ui.theme import current_palette
        p.setBrush(QColor(current_palette()["card"]))
        p.drawEllipse(inner)
        p.end()


class MiniBars(QWidget):
    """轻量手绘柱状 sparkline，用于软件历史时长。"""

    def __init__(self, height: int = 60, parent=None):
        super().__init__(parent)
        self._height = height
        self.setMinimumHeight(height)
        self._values: list[float] = []
        self._labels: list[str] = []
        self._color = "#4080FF"

    def set_data(self, labels: list[str], values: list[float], color: str = "#4080FF") -> None:
        self._labels = labels
        self._values = values
        self._color = color
        self.update()

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter
        from app.ui.theme import current_palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = current_palette()
        n = len(self._values)
        if n == 0:
            p.setPen(QColor(pal["subtle"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无数据")
            p.end()
            return
        max_v = max(self._values) or 1
        w = self.width()
        gap = 4
        bar_w = max(3, (w - gap * (n - 1)) / n)
        base = self._height - 14
        for i, v in enumerate(self._values):
            h = int((v / max_v) * (base - 4)) if max_v else 0
            x = i * (bar_w + gap)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self._color))
            p.drawRoundedRect(QRectF(x, base - h, bar_w, h), 2, 2)
        p.setPen(QColor(pal["subtle"]))
        font = p.font()
        font.setPointSize(7)
        p.setFont(font)
        if n:
            p.drawText(QRectF(0, base, w / 2, 14), Qt.AlignmentFlag.AlignLeft, self._labels[0])
            p.drawText(QRectF(w / 2, base, w / 2, 14), Qt.AlignmentFlag.AlignRight, self._labels[-1])
        p.end()