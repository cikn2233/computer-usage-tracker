from __future__ import annotations

import csv
import math
import os
from datetime import date, datetime, timedelta

from PyQt6.QtCore import QDate, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.database import Database
from app.ui.theme import EVENT_COLORS, event_row_bg
from app.ui.widgets import (
    Card,
    PageHeader,
    RowBackgroundDelegate,
    SegmentedControl,
    make_item,
    make_table,
)
from app.utils import event_type_label, human_size, reveal_in_explorer

PAGE_SIZE = 200


class EventsPage(QWidget):
    event_selected = pyqtSignal(dict)
    event_cleared = pyqtSignal()
    stats_updated = pyqtSignal(dict)

    def __init__(self, db: Database, config_provider, parent=None):
        super().__init__(parent)
        self.db = db
        self.get_config = config_provider
        self.page = 1
        self.total = 0
        self._page_rows: list[dict] = []
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(lambda: self.refresh(reset_page=True))
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(4000)
        self._auto_timer.timeout.connect(self._auto_refresh)
        self._build()
        self.refresh()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 18)
        outer.setSpacing(14)
        self.header = PageHeader("文件日志溯源", "记录文件新建 / 修改 / 重命名 / 删除，并推测操作软件")
        export_button = QPushButton("导出 CSV")
        export_button.setObjectName("Secondary")
        export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        export_button.clicked.connect(self.export_csv)
        refresh_button = QPushButton("刷新")
        refresh_button.setObjectName("Primary")
        refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_button.clicked.connect(lambda: self.refresh(reset_page=True))
        self.header.add_action(export_button)
        self.header.add_action(refresh_button)
        outer.addWidget(self.header)

        self.group_control = SegmentedControl(
            [("all", "全部文件"), ("office", "办公文档"), ("other", "其他文件")], "all"
        )
        self.group_control.changed.connect(lambda _v: self.refresh(reset_page=True))
        outer.addWidget(self.group_control, 0, Qt.AlignmentFlag.AlignLeft)

        filter_card = Card()
        row_one = QHBoxLayout()
        row_one.setSpacing(8)
        self.type_combo = QComboBox()
        for label, value in (
            ("全部类型", "all"), ("新建", "created"), ("修改", "modified"),
            ("重命名", "renamed"), ("删除", "deleted"),
        ):
            self.type_combo.addItem(label, value)
        self.type_combo.setFixedWidth(108)
        self.type_combo.currentIndexChanged.connect(lambda: self.refresh(reset_page=True))
        self.ext_combo = QComboBox()
        self.ext_combo.setFixedWidth(128)
        self.ext_combo.currentIndexChanged.connect(lambda: self.refresh(reset_page=True))
        self.process_combo = QComboBox()
        self.process_combo.setFixedWidth(150)
        self.process_combo.currentIndexChanged.connect(lambda: self.refresh(reset_page=True))
        self.range_combo = QComboBox()
        self.range_combo.addItem("今日", "today")
        self.range_combo.addItem("近 7 天", "7d")
        self.range_combo.addItem("近 30 天", "30d")
        self.range_combo.addItem("全部时间", "all")
        self.range_combo.addItem("自定义", "custom")
        self.range_combo.setCurrentIndex(1)
        self.range_combo.setFixedWidth(104)
        self.range_combo.currentIndexChanged.connect(self._on_range_changed)
        self.start_edit = QDateEdit(QDate.currentDate().addDays(-6))
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_edit.setFixedWidth(112)
        self.end_edit = QDateEdit(QDate.currentDate())
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("yyyy-MM-dd")
        self.end_edit.setFixedWidth(112)
        self.range_dash = QLabel("至")
        self.range_dash.setObjectName("FieldLabel")
        for w in (self.start_edit, self.range_dash, self.end_edit):
            w.hide()
        self.start_edit.dateChanged.connect(self._on_custom_date_changed)
        self.end_edit.dateChanged.connect(self._on_custom_date_changed)
        for label_text, widget in (
            ("类型", self.type_combo), ("后缀", self.ext_combo),
            ("软件", self.process_combo), ("时间", self.range_combo),
        ):
            label = QLabel(label_text)
            label.setObjectName("FieldLabel")
            row_one.addWidget(label)
            row_one.addWidget(widget)
            row_one.addSpacing(2)
        row_one.addWidget(self.start_edit)
        row_one.addWidget(self.range_dash)
        row_one.addWidget(self.end_edit)
        row_one.addStretch(1)
        filter_card.body.addLayout(row_one)

        row_two = QHBoxLayout()
        row_two.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索文件名或完整路径关键词…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda: self._search_timer.start())
        hint = QLabel("匹配文件名 / 路径，输入后自动检索")
        hint.setObjectName("HelperText")
        row_two.addWidget(self.search_edit, 1)
        row_two.addWidget(hint)
        filter_card.body.addLayout(row_two)
        outer.addWidget(filter_card)

        self.table_card = Card("文件事件记录", "按发生时间倒序 · 双击查看详情 · 行底色区分事件类型")
        self.table = make_table(
            ["发生时间", "类型", "文件名", "后缀", "大小", "操作软件（推测）", "完整路径", "操作"],
            [150, 62, 180, 56, 80, 120, -1, 70],
        )
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.cellDoubleClicked.connect(self._open_row)
        self.table.setItemDelegate(RowBackgroundDelegate(self.table))
        self.empty_label = QLabel("没有符合条件的文件事件")
        self.empty_label.setObjectName("EmptyHint")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setMinimumHeight(160)
        self.empty_label.hide()
        self.table_card.body.addWidget(self.table, 1)
        self.table_card.body.addWidget(self.empty_label)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.count_label = QLabel("共 0 条记录")
        self.count_label.setObjectName("Muted")
        self.prev_button = QPushButton("上一页")
        self.prev_button.setObjectName("Secondary")
        self.prev_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_button.clicked.connect(lambda: self._change_page(-1))
        self.next_button = QPushButton("下一页")
        self.next_button.setObjectName("Secondary")
        self.next_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_button.clicked.connect(lambda: self._change_page(1))
        self.page_label = QLabel("1 / 1")
        self.page_label.setObjectName("Muted")
        footer.addWidget(self.count_label)
        footer.addStretch(1)
        footer.addWidget(self.prev_button)
        footer.addWidget(self.page_label)
        footer.addWidget(self.next_button)
        self.table_card.body.addLayout(footer)
        outer.addWidget(self.table_card, 1)
        self._auto_timer.start()

    # -------- filters --------

    def _on_range_changed(self) -> None:
        custom = self.range_combo.currentData() == "custom"
        self.start_edit.setVisible(custom)
        self.range_dash.setVisible(custom)
        self.end_edit.setVisible(custom)
        self.refresh(reset_page=True)

    def _on_custom_date_changed(self) -> None:
        if self.range_combo.currentData() == "custom":
            self.refresh(reset_page=True)

    def _time_bounds(self) -> tuple[str | None, str | None]:
        key = self.range_combo.currentData()
        today = date.today()
        if key == "today":
            start, end = today, today
        elif key == "7d":
            start, end = today - timedelta(days=6), today
        elif key == "30d":
            start, end = today - timedelta(days=29), today
        elif key == "custom":
            start = self.start_edit.date().toPyDate()
            end = self.end_edit.date().toPyDate()
            if start > end:
                start, end = end, start
        else:
            return None, None
        return f"{start.isoformat()} 00:00:00", f"{(end + timedelta(days=1)).isoformat()} 00:00:00"

    def _query_params(self) -> dict:
        start_iso, end_iso = self._time_bounds()
        group = self.group_control.current_value()
        return {
            "event_type": self.type_combo.currentData() or "all",
            "ext": self.ext_combo.currentData(),
            "start_iso": start_iso,
            "end_iso": end_iso,
            "keyword": self.search_edit.text().strip() or None,
            "process_key": self.process_combo.currentData(),
            "group": None if group == "all" else group,
            "office_exts": self.get_config().office_extensions,
        }

    def _load_filters(self) -> None:
        current_ext = self.ext_combo.currentData()
        self.ext_combo.blockSignals(True)
        self.ext_combo.clear()
        self.ext_combo.addItem("全部后缀", None)
        for ext, count in self.db.distinct_extensions():
            self.ext_combo.addItem(f".{ext}（{count}）", ext)
        index = self.ext_combo.findData(current_ext) if current_ext else 0
        self.ext_combo.setCurrentIndex(index if index >= 0 else 0)
        self.ext_combo.blockSignals(False)

        current_proc = self.process_combo.currentData()
        self.process_combo.blockSignals(True)
        self.process_combo.clear()
        self.process_combo.addItem("全部软件", None)
        for key, name, count in self.db.distinct_processes():
            if key:
                self.process_combo.addItem(f"{name or key}（{count}）", key)
        index = self.process_combo.findData(current_proc) if current_proc else 0
        self.process_combo.setCurrentIndex(index if index >= 0 else 0)
        self.process_combo.blockSignals(False)

    # -------- refresh --------

    def refresh(self, reset_page: bool = False) -> None:
        if reset_page:
            self.page = 1
        params = self._query_params()
        offset = (self.page - 1) * PAGE_SIZE
        rows, total = self.db.query_file_events(**params, limit=PAGE_SIZE, offset=offset)
        pages = max(1, math.ceil(total / PAGE_SIZE))
        if self.page > pages:
            self.page = pages
            offset = (self.page - 1) * PAGE_SIZE
            rows, total = self.db.query_file_events(**params, limit=PAGE_SIZE, offset=offset)
        self.total = total
        self._page_rows = rows
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            bg = event_row_bg(row["event_type"])
            self.table.setItem(index, 0, make_item(row["event_time"], "#6B7686", background=bg))
            self.table.setItem(
                index, 1,
                make_item(event_type_label(row["event_type"]),
                          EVENT_COLORS.get(row["event_type"]), bold=True, background=bg),
            )
            self.table.setItem(index, 2, make_item(row["name"], tooltip=row["path"], background=bg))
            ext_text = f".{row['ext']}" if row["ext"] else "—"
            self.table.setItem(index, 3, make_item(ext_text, "#6B7686", background=bg))
            self.table.setItem(
                index, 4, make_item(human_size(row["size"]), "#6B7686", align_right=True, background=bg)
            )
            self.table.setItem(
                index, 5, make_item(row.get("process_name") or "—", "#9AA4B2", background=bg)
            )
            self.table.setItem(index, 6, make_item(row["path"], "#6B7686", tooltip=row["path"], background=bg))
            open_button = QPushButton("打开")
            open_button.setObjectName("Ghost")
            open_button.setCursor(Qt.CursorShape.PointingHandCursor)
            open_button.clicked.connect(lambda _c=False, p=row["path"]: self._open_path(p))
            self.table.setCellWidget(index, 7, open_button)
        self.table.setUpdatesEnabled(True)
        self.table.clearSelection()
        if rows:
            self.table.show()
            self.empty_label.hide()
        else:
            self.table.hide()
            self.empty_label.show()
        self.count_label.setText(f"共 {total} 条记录 · 每页 {PAGE_SIZE} 条")
        self.page_label.setText(f"{self.page} / {pages}")
        self.prev_button.setEnabled(self.page > 1)
        self.next_button.setEnabled(self.page < pages)
        self._emit_stats()

    def _emit_stats(self) -> None:
        start_iso, end_iso = self._time_bounds()
        config = self.get_config()
        if start_iso is None:
            start_iso = "0000-00-00 00:00:00"
            end_iso = "9999-00-00 00:00:00"
        types = self.db.office_type_counts(start_iso, end_iso, config.office_extensions)
        groups = self.db.group_counts_between(start_iso, end_iso, config.office_extensions)
        self.stats_updated.emit({"types": types, "groups": groups})

    def on_events_added(self) -> None:
        if not self.isVisible():
            return
        if self.page != 1 or self.table.hasFocus():
            return
        self.refresh()

    def _auto_refresh(self) -> None:
        if not self.isVisible():
            return
        if self.page != 1 or self.table.hasFocus():
            return
        self.refresh()

    def on_shown(self) -> None:
        self._load_filters()
        self.refresh()

    def _change_page(self, direction: int) -> None:
        pages = max(1, math.ceil(self.total / PAGE_SIZE))
        new_page = min(pages, max(1, self.page + direction))
        if new_page != self.page:
            self.page = new_page
            self.refresh()

    # -------- actions --------

    def _on_selection_changed(self) -> None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            self.event_cleared.emit()
            return
        index = rows[0].row()
        if 0 <= index < len(self._page_rows):
            self.event_selected.emit(self._page_rows[index])

    def _open_row(self, row: int, column: int) -> None:
        if column == 7:
            return
        if 0 <= row < len(self._page_rows):
            self._open_path(self._page_rows[row]["path"])

    def _open_path(self, path: str) -> None:
        if os.path.exists(path):
            reveal_in_explorer(path)
        else:
            parent = os.path.dirname(path)
            if os.path.isdir(parent):
                QMessageBox.information(
                    self, "文件已不存在",
                    f"该文件已被删除或移动：\n{path}\n\n将为你打开它原来所在的文件夹。",
                )
                reveal_in_explorer(parent)
            else:
                QMessageBox.information(self, "文件已不存在", f"该文件及其所在目录均已不存在：\n{path}")

    def export_csv(self) -> None:
        params = self._query_params()
        rows, _total = self.db.query_file_events(**params, limit=200000, offset=0)
        if not rows:
            QMessageBox.information(self, "导出文件事件", "当前筛选条件下没有可导出的记录。")
            return
        default_name = f"文件事件_{datetime.now():%Y%m%d_%H%M}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "导出为 CSV", default_name, "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    ["发生时间", "事件类型", "文件名", "后缀", "文件大小(字节)",
                     "操作软件(推测)", "完整路径", "原路径(重命名)", "监测目录"]
                )
                for row in rows:
                    writer.writerow([
                        row["event_time"], event_type_label(row["event_type"]),
                        row["name"], row["ext"],
                        "" if row["size"] is None else row["size"],
                        row.get("process_name", ""), row["path"],
                        row.get("old_path", ""), row["root"],
                    ])
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", f"无法写入文件：\n{exc}")
            return
        QMessageBox.information(self, "导出完成", f"已导出 {len(rows)} 条记录到：\n{path}")