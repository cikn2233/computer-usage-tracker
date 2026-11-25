from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import QApplication, QCheckBox

# 柔和治愈系配色：主色柔和蓝 #4080FF，辅以浅薄荷绿 / 浅桃橙 / 浅灰。
# 所有界面颜色都来自下面的调色板，方便后续自行微调。
PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#F5F7FB",
        "card": "#FFFFFF",
        "border": "#E8ECF4",
        "text": "#2A3342",
        "muted": "#6B7686",
        "subtle": "#9AA4B2",
        "primary": "#4080FF",
        "primary_hover": "#3570EE",
        "primary_pressed": "#2C60D8",
        "primary_disabled": "#BBD2FA",
        "primary_soft": "#E9F1FF",
        "green": "#3BA776",
        "amber": "#E0913A",
        "red": "#E0655A",
        "mint": "#57B894",
        "peach": "#F0A868",
        "sky": "#5AA9E6",
        "active": "#4080FF",
        "idle": "#F0A868",
        "lock": "#A0A8B8",
        "sidebar_bg": "#FBFCFE",
        "sidebar_border": "#E8ECF4",
        "sidebar_text": "#5A6472",
        "sidebar_muted": "#9AA4B2",
        "sidebar_hover": "#F0F4FA",
        "sidebar_active_bg": "#E9F1FF",
        "sidebar_active_text": "#2C60D8",
        "sidebar_accent": "#4080FF",
        "sidebar_box_bg": "#F4F7FC",
        "sidebar_box_border": "#E8ECF4",
        "input_bg": "#FFFFFF",
        "input_border": "#DDE3ED",
        "input_focus": "#9CC0FF",
        "table_grid": "#F0F3F8",
        "table_alt": "#FAFBFE",
        "table_select": "#E9F1FF",
        "header_bg": "#F7F9FC",
        "mini_bg": "#F7F9FC",
        "mini_border": "#EDF1F7",
        "scroll_handle": "#D2D8E2",
        "scroll_handle_hover": "#B4BCC9",
        "menu_bg": "#FFFFFF",
        "tooltip_bg": "#2A3342",
        "tooltip_text": "#F5F7FB",
        "seg_bg": "#EEF2F8",
        "seg_active_bg": "#FFFFFF",
        "seg_text": "#5A6472",
        "seg_active_text": "#2C60D8",
        "ghost_hover": "#EEF3FA",
        "danger_border": "#F6D2CD",
        "danger_bg": "#FDF1EF",
        "notice_ok": "#2F8F63",
        "notice_warn": "#C07A2A",
        "status_on_bg": "#E4F5EC",
        "status_on_text": "#2F8F63",
        "status_paused_bg": "#FBF0DF",
        "status_paused_text": "#C07A2A",
        "status_off_bg": "#EEF2F8",
        "status_off_text": "#6B7686",
        "detail_border": "#E8ECF4",
        "shadow": "#E2E7F0",
    },
    "dark": {
        "bg": "#191C22",
        "card": "#22262E",
        "border": "#2D323B",
        "text": "#E4E7EC",
        "muted": "#9AA1AD",
        "subtle": "#6E7681",
        "primary": "#5B8DEF",
        "primary_hover": "#6C9AF2",
        "primary_pressed": "#4F7EDC",
        "primary_disabled": "#3A4A66",
        "primary_soft": "#2A3550",
        "green": "#5FBF95",
        "amber": "#E0A458",
        "red": "#E07A70",
        "mint": "#5FBF95",
        "peach": "#E0A458",
        "sky": "#6FB1E8",
        "active": "#5B8DEF",
        "idle": "#E0A458",
        "lock": "#7A828E",
        "sidebar_bg": "#1E222A",
        "sidebar_border": "#2D323B",
        "sidebar_text": "#AEB5C0",
        "sidebar_muted": "#6E7681",
        "sidebar_hover": "#262B34",
        "sidebar_active_bg": "#2A3550",
        "sidebar_active_text": "#8FB4F7",
        "sidebar_accent": "#5B8DEF",
        "sidebar_box_bg": "#262B34",
        "sidebar_box_border": "#2D323B",
        "input_bg": "#262B34",
        "input_border": "#353B45",
        "input_focus": "#5B8DEF",
        "table_grid": "#2A2F38",
        "table_alt": "#252A32",
        "table_select": "#2A3550",
        "header_bg": "#262B34",
        "mini_bg": "#262B34",
        "mini_border": "#2D323B",
        "scroll_handle": "#3A404B",
        "scroll_handle_hover": "#4A515D",
        "menu_bg": "#262B34",
        "tooltip_bg": "#0F1216",
        "tooltip_text": "#E4E7EC",
        "seg_bg": "#262B34",
        "seg_active_bg": "#333A45",
        "seg_text": "#AEB5C0",
        "seg_active_text": "#8FB4F7",
        "ghost_hover": "#2A2F38",
        "danger_border": "#5A3A36",
        "danger_bg": "#3A2A28",
        "notice_ok": "#5FBF95",
        "notice_warn": "#E0A458",
        "status_on_bg": "#233A2F",
        "status_on_text": "#5FBF95",
        "status_paused_bg": "#3A3226",
        "status_paused_text": "#E0A458",
        "status_off_bg": "#2A2F38",
        "status_off_text": "#9AA1AD",
        "detail_border": "#2D323B",
        "shadow": "#12151A",
    },
}

# 文件事件行底色（新建浅薄荷绿 / 修改浅蓝 / 删除浅桃橙 / 重命名浅灰）
EVENT_ROW_BG: dict[str, dict[str, str]] = {
    "light": {
        "created": "#EAF7F0",
        "modified": "#EAF1FE",
        "deleted": "#FDEFE7",
        "renamed": "#F1F3F7",
    },
    "dark": {
        "created": "#233A2F",
        "modified": "#26324E",
        "deleted": "#3A2C26",
        "renamed": "#2A2F38",
    },
}

EVENT_COLORS = {
    "created": "#3BA776",
    "modified": "#4080FF",
    "deleted": "#E0655A",
    "renamed": "#8A93A3",
}

# 兼容旧引用：默认浅色关键色
COLORS = {
    "bg": PALETTES["light"]["bg"],
    "card": PALETTES["light"]["card"],
    "border": PALETTES["light"]["border"],
    "sidebar": PALETTES["light"]["sidebar_bg"],
    "text": PALETTES["light"]["text"],
    "muted": PALETTES["light"]["muted"],
    "subtle": PALETTES["light"]["subtle"],
    "primary": PALETTES["light"]["primary"],
    "sky": PALETTES["light"]["sky"],
    "green": PALETTES["light"]["green"],
    "amber": PALETTES["light"]["amber"],
    "red": PALETTES["light"]["red"],
    "active": PALETTES["light"]["active"],
    "idle": PALETTES["light"]["idle"],
}

_current_theme = "light"


def current_theme() -> str:
    return _current_theme


def current_palette() -> dict[str, str]:
    return PALETTES[_current_theme]


def event_row_bg(kind: str) -> str:
    return EVENT_ROW_BG[_current_theme].get(kind, "transparent")


_QSS_TEMPLATE = """
* { font-family: "Microsoft YaHei UI"; }
QMainWindow, QWidget#Root, QWidget#ContentRoot { background: @bg@; }
QWidget { color: @text@; font-size: 13px; }
QToolTip { background: @tooltip_bg@; color: @tooltip_text@; border: none; padding: 5px 8px; font-size: 12px; }

QFrame#Sidebar { background: @sidebar_bg@; border-right: 1px solid @sidebar_border@; }
QLabel#BrandTitle { color: @text@; font-size: 15px; font-weight: 700; }
QLabel#BrandSub { color: @sidebar_muted@; font-size: 10px; letter-spacing: 1px; }
QPushButton#NavButton { color: @sidebar_text@; background: transparent; border: none; border-left: 3px solid transparent; border-radius: 9px; padding: 10px 14px; text-align: left; font-size: 13px; }
QPushButton#NavButton:hover { background: @sidebar_hover@; color: @text@; }
QPushButton#NavButton:checked { background: @sidebar_active_bg@; color: @sidebar_active_text@; border-left: 3px solid @sidebar_accent@; font-weight: 600; padding-left: 11px; }
QLabel#SidebarMuted { color: @sidebar_muted@; font-size: 11px; }
QLabel#SidebarValue { color: @sidebar_text@; font-size: 12px; font-weight: 600; }
QFrame#SidebarBox { background: @sidebar_box_bg@; border: 1px solid @sidebar_box_border@; border-radius: 10px; }

QFrame#TopBar { background: @card@; border-bottom: 1px solid @border@; }
QLabel#TopHint { color: @muted@; font-size: 12px; }
QLabel#StatusPill { border-radius: 10px; padding: 4px 12px; font-size: 11px; font-weight: 600; }
QLabel#StatusPill[state="on"] { background: @status_on_bg@; color: @status_on_text@; }
QLabel#StatusPill[state="paused"] { background: @status_paused_bg@; color: @status_paused_text@; }
QLabel#StatusPill[state="off"] { background: @status_off_bg@; color: @status_off_text@; }

QLabel#PageTitle { font-size: 22px; font-weight: 700; color: @text@; }
QLabel#PageSub { color: @muted@; font-size: 12px; }
QLabel#SectionTitle { font-size: 14px; font-weight: 700; color: @text@; }
QLabel#SectionSub { color: @subtle@; font-size: 11px; }
QLabel#Muted { color: @muted@; font-size: 12px; }
QLabel#EmptyHint { color: @subtle@; font-size: 12px; }
QLabel#FieldLabel { color: @muted@; font-size: 12px; font-weight: 600; }
QLabel#HelperText { color: @subtle@; font-size: 11px; }
QLabel#NoticeOk { color: @notice_ok@; font-size: 12px; font-weight: 600; }
QLabel#NoticeWarn { color: @notice_warn@; font-size: 12px; }

QFrame#Card { background: @card@; border: 1px solid @border@; border-radius: 14px; }
QLabel#CardTitle { color: @muted@; font-size: 12px; font-weight: 600; }
QLabel#CardValue { color: @text@; font-size: 22px; font-weight: 700; }
QLabel#CardSub { color: @subtle@; font-size: 11px; }
QFrame#MiniCard { background: @mini_bg@; border: 1px solid @mini_border@; border-radius: 10px; }
QLabel#MiniTitle { color: @subtle@; font-size: 11px; }
QLabel#MiniValue { color: @text@; font-size: 17px; font-weight: 700; }

QPushButton#Primary { background: @primary@; color: #FFFFFF; border: none; border-radius: 9px; padding: 8px 16px; font-weight: 600; }
QPushButton#Primary:hover { background: @primary_hover@; }
QPushButton#Primary:pressed { background: @primary_pressed@; }
QPushButton#Primary:disabled { background: @primary_disabled@; color: #F5F7FB; }
QPushButton#Secondary { background: @card@; color: @text@; border: 1px solid @input_border@; border-radius: 9px; padding: 7px 14px; font-weight: 600; }
QPushButton#Secondary:hover { background: @sidebar_hover@; border-color: @scroll_handle_hover@; }
QPushButton#Secondary:disabled { color: @subtle@; border-color: @border@; }
QPushButton#Ghost { background: transparent; color: @muted@; border: none; border-radius: 7px; padding: 6px 10px; }
QPushButton#Ghost:hover { background: @ghost_hover@; color: @text@; }
QPushButton#Danger { background: @card@; color: @red@; border: 1px solid @danger_border@; border-radius: 9px; padding: 7px 14px; font-weight: 600; }
QPushButton#Danger:hover { background: @danger_bg@; }
QPushButton#Segment { background: transparent; color: @seg_text@; border: none; border-radius: 7px; padding: 5px 14px; font-size: 12px; font-weight: 600; }
QPushButton#Segment:hover { color: @seg_active_text@; }
QPushButton#Segment:checked { background: @seg_active_bg@; color: @seg_active_text@; }
QFrame#SegmentBar { background: @seg_bg@; border: none; border-radius: 9px; }

QLineEdit, QComboBox, QSpinBox, QDateEdit, QPlainTextEdit, QTextEdit { background: @input_bg@; color: @text@; border: 1px solid @input_border@; border-radius: 8px; padding: 6px 10px; selection-background-color: @primary_soft@; selection-color: @text@; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus, QPlainTextEdit:focus, QTextEdit:focus { border: 1px solid @input_focus@; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { background: @mini_bg@; color: @subtle@; }
QComboBox QAbstractItemView { background: @menu_bg@; border: 1px solid @border@; padding: 4px; outline: 0; selection-background-color: @primary_soft@; selection-color: @seg_active_text@; }
QComboBox::drop-down { border: none; width: 18px; }
QSpinBox::up-button, QSpinBox::down-button { width: 16px; border: none; background: transparent; }
QCheckBox { spacing: 8px; color: @text@; font-size: 12px; }
QTabWidget::pane { border: 1px solid @border@; border-radius: 10px; background: @card@; top: -1px; }
QTabBar::tab { background: transparent; color: @muted@; padding: 8px 18px; border: none; font-weight: 600; }
QTabBar::tab:selected { color: @primary@; border-bottom: 2px solid @primary@; }
QTabBar::tab:hover { color: @text@; }

QTableWidget { background: @card@; border: none; gridline-color: @table_grid@; alternate-background-color: @table_alt@; selection-background-color: @table_select@; selection-color: @text@; outline: 0; }
QTableWidget::item { padding: 2px 8px; border-bottom: 1px solid @table_grid@; }
QTableWidget::item:selected { color: @text@; }
QHeaderView { background: transparent; }
QHeaderView::section { background: @header_bg@; color: @muted@; border: none; border-bottom: 1px solid @border@; padding: 7px 8px; font-size: 11px; font-weight: 600; }
QTableWidget QTableCornerButton::section { background: @header_bg@; border: none; }

QListWidget { background: @input_bg@; border: 1px solid @input_border@; border-radius: 9px; padding: 4px; outline: 0; }
QListWidget::item { padding: 6px 8px; border-radius: 7px; color: @text@; }
QListWidget::item:selected { background: @primary_soft@; color: @seg_active_text@; }

QFrame#DetailPane { background: @card@; border-left: 1px solid @detail_border@; }
QLabel#DetailHeading { font-size: 14px; font-weight: 700; color: @text@; }
QLabel#DetailLabel { color: @subtle@; font-size: 11px; }
QLabel#DetailValue { color: @text@; font-size: 12px; font-weight: 600; }
QLabel#DetailValueBig { color: @text@; font-size: 20px; font-weight: 700; }
QLabel#DetailBody { color: @muted@; font-size: 11px; }

QScrollArea { border: none; background: transparent; }
QWidget#ScrollBody { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: @scroll_handle@; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: @scroll_handle_hover@; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle:horizontal { background: @scroll_handle@; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QMenu { background: @menu_bg@; border: 1px solid @border@; border-radius: 9px; padding: 6px; }
QMenu::item { padding: 6px 22px; border-radius: 7px; color: @text@; }
QMenu::item:selected { background: @primary_soft@; color: @seg_active_text@; }
QMenu::separator { height: 1px; background: @table_grid@; margin: 4px 8px; }
QMessageBox { background: @card@; }
"""


def build_qss(palette: dict[str, str]) -> str:
    qss = _QSS_TEMPLATE
    for key, value in palette.items():
        qss = qss.replace(f"@{key}@", value)
    return qss


def apply_theme(app: QApplication, theme: str) -> None:
    global _current_theme
    _current_theme = theme if theme in PALETTES else "light"
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(build_qss(current_palette()))


def setup_app(app: QApplication) -> None:
    apply_theme(app, _current_theme)


def make_app_icon(size: int = 64) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor("#4080FF"))
    gradient.setColorAt(1.0, QColor("#57B894"))
    painter.setBrush(gradient)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRectF(2, 2, size - 4, size - 4), size * 0.24, size * 0.24)
    painter.setBrush(QColor("#FFFFFF"))
    bar_width = size * 0.12
    gap = size * 0.07
    base = size * 0.76
    heights = (0.22, 0.40, 0.30)
    x0 = size * 0.24
    for index, height in enumerate(heights):
        x = x0 + index * (bar_width + gap)
        painter.drawRoundedRect(
            QRectF(x, base - size * height, bar_width, size * height),
            bar_width / 2, bar_width / 2,
        )
    painter.setBrush(QColor("#DCEBFF"))
    radius = size * 0.055
    painter.drawEllipse(QPointF(size * 0.755, size * 0.255), radius, radius)
    painter.end()
    return QIcon(pix)


def make_nav_icon(key: str, size: int = 18, color: str = "#6B7686") -> QIcon:
    """为可折叠侧栏绘制简洁线性图标。"""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = p.pen()
    pen.setColor(QColor(color))
    pen.setWidthF(max(1.3, size * 0.085))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    s = size
    m = s * 0.18
    if key == "overview":
        g = s * 0.10
        cell = (s - 2 * m - g) / 2
        for r in range(2):
            for c in range(2):
                p.drawRoundedRect(QRectF(m + c * (cell + g), m + r * (cell + g), cell, cell), 2, 2)
    elif key == "duration":
        p.drawEllipse(QRectF(m, m, s - 2 * m, s - 2 * m))
        c = s / 2
        p.drawLine(QPointF(c, c), QPointF(c, m + s * 0.14))
        p.drawLine(QPointF(c, c), QPointF(c + s * 0.18, c + s * 0.06))
    elif key == "software":
        p.drawRoundedRect(QRectF(m, m + s * 0.04, s - 2 * m, s - 2 * m - s * 0.08), 3, 3)
        p.drawLine(QPointF(m, m + s * 0.22), QPointF(s - m, m + s * 0.22))
    elif key == "events":
        path = QPainterPath()
        x0, y0 = m + s * 0.04, m
        w, h = s - 2 * m - s * 0.08, s - 2 * m
        fold = s * 0.18
        path.moveTo(x0, y0)
        path.lineTo(x0 + w - fold, y0)
        path.lineTo(x0 + w, y0 + fold)
        path.lineTo(x0 + w, y0 + h)
        path.lineTo(x0, y0 + h)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(x0 + s * 0.12, y0 + h * 0.5), QPointF(x0 + w - s * 0.12, y0 + h * 0.5))
        p.drawLine(QPointF(x0 + s * 0.12, y0 + h * 0.72), QPointF(x0 + w - s * 0.12, y0 + h * 0.72))
    elif key == "settings":
        c = s / 2
        p.drawEllipse(QRectF(c - s * 0.13, c - s * 0.13, s * 0.26, s * 0.26))
        p.drawEllipse(QRectF(m, m, s - 2 * m, s - 2 * m))
    elif key == "export":
        c = s / 2
        p.drawLine(QPointF(c, m), QPointF(c, s - m - s * 0.1))
        p.drawLine(QPointF(c - s * 0.14, m + s * 0.14), QPointF(c, m))
        p.drawLine(QPointF(c + s * 0.14, m + s * 0.14), QPointF(c, m))
        p.drawLine(QPointF(m, s - m), QPointF(s - m, s - m))
    else:
        p.drawEllipse(QRectF(m, m, s - 2 * m, s - 2 * m))
    p.end()
    return QIcon(pix)


class ToggleSwitch(QCheckBox):
    """美化开关滑块，替代普通复选框用于设置项。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(24)

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setWidth(hint.width() + 46)
        hint.setHeight(max(hint.height(), 24))
        return hint

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = current_palette()
        track_w, track_h = 38, 20
        x = self.width() - track_w - 2
        y = (self.height() - track_h) / 2
        on = self.isChecked()
        track_color = QColor(pal["primary"] if on else pal["scroll_handle"])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track_color)
        p.drawRoundedRect(QRectF(x, y, track_w, track_h), track_h / 2, track_h / 2)
        knob_d = track_h - 4
        knob_x = x + track_w - knob_d - 2 if on else x + 2
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(knob_x, y + 2, knob_d, knob_d))
        p.setPen(QColor(pal["text"]))
        font = p.font()
        font.setPointSize(9)
        p.setFont(font)
        p.drawText(QRectF(0, 0, x - 8, self.height()), Qt.AlignmentFlag.AlignVCenter, self.text())
        p.end()