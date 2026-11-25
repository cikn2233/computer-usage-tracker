from __future__ import annotations

from datetime import date, datetime, timedelta

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.config import DATA_DIR
from app.ui.theme import EVENT_COLORS
from app.ui.widgets import MiniBars, MiniPie
from app.utils import (
    event_type_label,
    human_duration,
    human_size,
    open_terminal_folder,
    parse_iso,
    reveal_in_explorer,
)

_PIE_COLORS = ["#4080FF", "#57B894", "#F0A868", "#5AA9E6", "#A0A8B8"]


def _breakable(text: str | None) -> str:
    if not text:
        return ""
    return text.replace("\\", "\\\u200b").replace("/", "/\u200b")


class DetailPanel(QFrame):
    def __init__(self, db=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.setObjectName("DetailPane")
        self.setFixedWidth(306)
        self._current_event: dict | None = None
        self._current_app: dict | None = None
        self._build()
        self.clear_event()
        self.clear_app()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 16, 14)
        root.setSpacing(10)
        heading = QLabel("实时详情")
        heading.setObjectName("DetailHeading")
        root.addWidget(heading)
        hint = QLabel("本地运行 · 无云端同步")
        hint.setObjectName("DetailLabel")
        root.addWidget(hint)
        root.addSpacing(4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("ScrollBody")
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 2, 0)
        content.setSpacing(10)
        content.addWidget(self._build_live_card())
        content.addWidget(self._build_app_card())
        content.addWidget(self._build_event_card())
        content.addWidget(self._build_stats_card())
        content.addWidget(self._build_scope_card())
        content.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        footer = QLabel(f"数据目录\n{_breakable(str(DATA_DIR))}")
        footer.setObjectName("DetailLabel")
        footer.setWordWrap(True)
        footer.setToolTip(str(DATA_DIR))
        footer.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(footer)
        open_data = QPushButton("打开数据目录")
        open_data.setObjectName("Ghost")
        open_data.setCursor(Qt.CursorShape.PointingHandCursor)
        open_data.clicked.connect(lambda: open_terminal_folder(DATA_DIR))
        root.addWidget(open_data, 0, Qt.AlignmentFlag.AlignLeft)

    def _section(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("MiniCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("FieldLabel")
        layout.addWidget(label)
        return frame, layout

    def _build_live_card(self) -> QFrame:
        frame, layout = self._section("运行状态")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        status_caption = QLabel("文件监测")
        status_caption.setObjectName("DetailLabel")
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(8, 8)
        self.status_value = QLabel("—")
        self.status_value.setObjectName("DetailValue")
        self.status_value.setWordWrap(True)
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_value, 1)
        grid.addWidget(status_caption, 0, 0, Qt.AlignmentFlag.AlignTop)
        grid.addLayout(status_row, 0, 1)
        session_caption = QLabel("本次会话")
        session_caption.setObjectName("DetailLabel")
        self.session_value = QLabel("—")
        self.session_value.setObjectName("DetailBody")
        self.session_value.setWordWrap(True)
        grid.addWidget(session_caption, 1, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self.session_value, 1, 1)
        boot_caption = QLabel("系统开机")
        boot_caption.setObjectName("DetailLabel")
        self.boot_value = QLabel("—")
        self.boot_value.setObjectName("DetailBody")
        self.boot_value.setWordWrap(True)
        grid.addWidget(boot_caption, 2, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self.boot_value, 2, 1)
        layout.addLayout(grid)
        layout.addWidget(self._separator())
        today_caption = QLabel("今日使用")
        today_caption.setObjectName("DetailLabel")
        layout.addWidget(today_caption)
        self.today_value = QLabel("—")
        self.today_value.setObjectName("DetailValueBig")
        layout.addWidget(self.today_value)
        self.today_split = QLabel("")
        self.today_split.setObjectName("DetailBody")
        self.today_split.setWordWrap(True)
        layout.addWidget(self.today_split)
        layout.addWidget(self._separator())
        file_caption = QLabel("今日文件动态")
        file_caption.setObjectName("DetailLabel")
        layout.addWidget(file_caption)
        self.file_counts = QLabel("—")
        self.file_counts.setObjectName("DetailBody")
        self.file_counts.setWordWrap(True)
        layout.addWidget(self.file_counts)
        return frame

    def _build_app_card(self) -> QFrame:
        self.app_frame, layout = self._section("选中软件")
        self.app_name = QLabel("")
        self.app_name.setObjectName("DetailValue")
        self.app_name.setWordWrap(True)
        layout.addWidget(self.app_name)
        self.app_exe = QLabel("")
        self.app_exe.setObjectName("DetailBody")
        self.app_exe.setWordWrap(True)
        self.app_exe.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.app_exe)
        self.app_today = QLabel("")
        self.app_today.setObjectName("DetailBody")
        self.app_today.setWordWrap(True)
        layout.addWidget(self.app_today)
        caption = QLabel("近 7 天前台时长")
        caption.setObjectName("DetailLabel")
        layout.addWidget(caption)
        self.app_bars = MiniBars(height=64)
        layout.addWidget(self.app_bars)
        return self.app_frame

    def _build_event_card(self) -> QFrame:
        self.event_frame, layout = self._section("选中记录")
        self.event_empty = QLabel("在「文件日志」中选中一条记录，可在此查看完整信息。")
        self.event_empty.setObjectName("EmptyHint")
        self.event_empty.setWordWrap(True)
        layout.addWidget(self.event_empty)
        self.event_box = QWidget()
        box_layout = QVBoxLayout(self.event_box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(6)
        self.event_type = QLabel("")
        self.event_type.setStyleSheet("font-size: 11px; font-weight: 700;")
        box_layout.addWidget(self.event_type, 0, Qt.AlignmentFlag.AlignLeft)
        self.event_name = QLabel("")
        self.event_name.setObjectName("DetailValue")
        self.event_name.setWordWrap(True)
        self.event_name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box_layout.addWidget(self.event_name)
        self.event_path = QLabel("")
        self.event_path.setObjectName("DetailBody")
        self.event_path.setWordWrap(True)
        self.event_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box_layout.addWidget(self.event_path)
        self.event_meta = QLabel("")
        self.event_meta.setObjectName("DetailLabel")
        self.event_meta.setWordWrap(True)
        box_layout.addWidget(self.event_meta)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.open_button = QPushButton("打开位置")
        self.open_button.setObjectName("Secondary")
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.clicked.connect(self._open_current)
        self.copy_button = QPushButton("复制路径")
        self.copy_button.setObjectName("Ghost")
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.clicked.connect(self._copy_current)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.copy_button)
        buttons.addStretch(1)
        box_layout.addLayout(buttons)
        layout.addWidget(self.event_box)
        self.event_frame.hide()
        return self.event_frame

    def _build_stats_card(self) -> QFrame:
        self.stats_frame, layout = self._section("时段文档统计")
        row = QHBoxLayout()
        row.setSpacing(10)
        self.stats_pie = MiniPie(size=96)
        row.addWidget(self.stats_pie)
        self.stats_text = QLabel("")
        self.stats_text.setObjectName("DetailBody")
        self.stats_text.setWordWrap(True)
        row.addWidget(self.stats_text, 1)
        layout.addLayout(row)
        self.stats_frame.hide()
        return self.stats_frame

    def _build_scope_card(self) -> QFrame:
        frame, layout = self._section("监测范围")
        self.scope_value = QLabel("尚未选择监测目录")
        self.scope_value.setObjectName("DetailBody")
        self.scope_value.setWordWrap(True)
        self.scope_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.scope_value)
        return frame

    @staticmethod
    def _separator() -> QFrame:
        from app.ui.theme import current_palette
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {current_palette()['border']}; border: none;")
        return line

    # -------- updates --------

    def update_live(
        self, *, running: bool, status_text: str, session_start: str | None,
        boot_time: datetime | None, today_active: int, today_idle: int,
        today_lock: int, counts: dict[str, int],
    ) -> None:
        color = "#57B894" if running else "#E0913A"
        self.status_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        self.status_value.setText(status_text)
        self.status_value.setStyleSheet(f"color: {color};")
        start = parse_iso(session_start or "")
        if start is not None:
            elapsed = max(0, int((datetime.now() - start).total_seconds()))
            self.session_value.setText(
                f"{start.strftime('%m-%d %H:%M')} 开始 · 已运行 {human_duration(elapsed)}"
            )
        else:
            self.session_value.setText("—")
        if boot_time is not None:
            elapsed = max(0, int((datetime.now() - boot_time).total_seconds()))
            self.boot_value.setText(
                f"{boot_time.strftime('%m-%d %H:%M')} · 已开机 {human_duration(elapsed)}"
            )
        else:
            self.boot_value.setText("—")
        total = today_active + today_idle + today_lock
        self.today_value.setText(human_duration(total))
        self.today_split.setText(
            f"活跃 {human_duration(today_active)} · 闲置 {human_duration(today_idle)} · "
            f"锁屏 {human_duration(today_lock)}"
        )
        self.file_counts.setText(
            f'<span style="color:#3BA776;font-weight:600">新建 {counts.get("created", 0)}</span>'
            f' &nbsp;·&nbsp; <span style="color:#4080FF;font-weight:600">修改 {counts.get("modified", 0)}</span>'
            f' &nbsp;·&nbsp; <span style="color:#8A93A3;font-weight:600">重命名 {counts.get("renamed", 0)}</span>'
            f' &nbsp;·&nbsp; <span style="color:#E0655A;font-weight:600">删除 {counts.get("deleted", 0)}</span>'
        )

    def set_scope(self, roots: list[str]) -> None:
        if not roots:
            self.scope_value.setText("尚未选择监测目录")
            self.scope_value.setToolTip("")
            return
        shown = roots[:6]
        text = "\n".join(_breakable(path) for path in shown)
        if len(roots) > 6:
            text += f"\n… 另有 {len(roots) - 6} 个目录"
        self.scope_value.setText(text)
        self.scope_value.setToolTip("\n".join(roots))

    def show_app(self, row: dict) -> None:
        self._current_app = row
        self.app_name.setText(row.get("name", ""))
        self.app_exe.setText(_breakable(row.get("exe", "")))
        self.app_exe.setToolTip(row.get("exe", ""))
        self.app_today.setText(
            f"今日前台 {human_duration(row.get('fg', 0))} · 后台 {human_duration(row.get('bg', 0))}\n"
            f"下载 {human_size(row.get('bin', 0))} · 上传 {human_size(row.get('bout', 0))}"
        )
        if self.db is not None and row.get("app_key"):
            today = date.today()
            days = [today - timedelta(days=o) for o in range(6, -1, -1)]
            series = self.db.app_daily_series(row["app_key"], days[0].isoformat(), days[-1].isoformat())
            labels = [f"{d.month}/{d.day}" for d in days]
            values = [series.get(d.isoformat(), (0, 0))[0] / 60 for d in days]
            self.app_bars.set_data(labels, values)
        self.app_frame.show()

    def clear_app(self) -> None:
        self._current_app = None
        self.app_frame.hide()

    def set_event_stats(self, stats: dict) -> None:
        types = stats.get("types", {})
        groups = stats.get("groups", {})
        items = [(k, v, _PIE_COLORS[i % len(_PIE_COLORS)]) for i, (k, v) in enumerate(types.items()) if v > 0]
        self.stats_pie.set_data(items)
        self.stats_text.setText(
            f"办公文档 {groups.get('office', 0)} 次\n其他文件 {groups.get('other', 0)} 次\n"
            f"合计 {groups.get('all', 0)} 次"
        )
        self.stats_frame.show()

    def show_event(self, row: dict) -> None:
        self._current_event = row
        color = EVENT_COLORS.get(row["event_type"], "#6B7686")
        self.event_type.setText(event_type_label(row["event_type"]))
        self.event_type.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {color};")
        self.event_name.setText(_breakable(row["name"]))
        self.event_name.setToolTip(row["name"])
        self.event_path.setText(_breakable(row["path"]))
        self.event_path.setToolTip(row["path"])
        ext_text = f".{row['ext']}" if row.get("ext") else "无后缀"
        size_text = human_size(row.get("size"))
        meta = f"{row['event_time']} · {ext_text} · {size_text}"
        if row.get("process_name"):
            meta += f"\n操作软件（推测）：{row['process_name']}"
        if row.get("old_path"):
            meta += f"\n原路径：{_breakable(row['old_path'])}"
        if row.get("root"):
            meta += f"\n监测目录：{_breakable(row['root'])}"
        self.event_meta.setText(meta)
        self.event_empty.hide()
        self.event_box.show()
        self.open_button.setEnabled(True)
        self.copy_button.setEnabled(True)

    def clear_event(self) -> None:
        self._current_event = None
        self.event_box.hide()
        self.event_empty.show()
        self.open_button.setEnabled(False)
        self.copy_button.setEnabled(False)

    def _open_current(self) -> None:
        if self._current_event:
            reveal_in_explorer(self._current_event["path"])

    def _copy_current(self) -> None:
        if self._current_event:
            QApplication.clipboard().setText(self._current_event["path"])