from __future__ import annotations

from datetime import date, timedelta

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.database import Database
from app.export import export_excel, export_html
from app.ui.widgets import Card, MiniStat, PageHeader
from app.utils import human_duration, human_size, month_bounds


class ExportPage(QWidget):
    def __init__(self, db: Database, config_provider, parent=None):
        super().__init__(parent)
        self.db = db
        self.get_config = config_provider
        self._build()
        self.refresh_preview()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 18)
        outer.setSpacing(14)
        self.header = PageHeader("导出报告", "导出 Excel 明细或自包含 HTML 可视化报告（含文档类型饼图）")
        outer.addWidget(self.header)

        range_card = Card("导出范围", "选择需要导出的时间段")
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.range_combo = QComboBox()
        self.range_combo.addItem("今日", "today")
        self.range_combo.addItem("近 7 天", "7d")
        self.range_combo.addItem("本月", "month")
        self.range_combo.addItem("自定义", "custom")
        self.range_combo.setCurrentIndex(1)
        self.range_combo.setFixedWidth(120)
        self.range_combo.currentIndexChanged.connect(self._on_range_changed)
        self.start_edit = QDateEdit(QDate.currentDate().addDays(-6))
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_edit.setFixedWidth(118)
        self.end_edit = QDateEdit(QDate.currentDate())
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("yyyy-MM-dd")
        self.end_edit.setFixedWidth(118)
        self.range_dash = QLabel("至")
        self.range_dash.setObjectName("FieldLabel")
        for w in (self.start_edit, self.range_dash, self.end_edit):
            w.hide()
        self.start_edit.dateChanged.connect(lambda: self.refresh_preview())
        self.end_edit.dateChanged.connect(lambda: self.refresh_preview())
        label = QLabel("时间范围")
        label.setObjectName("FieldLabel")
        bar.addWidget(label)
        bar.addWidget(self.range_combo)
        bar.addWidget(self.start_edit)
        bar.addWidget(self.range_dash)
        bar.addWidget(self.end_edit)
        bar.addStretch(1)
        range_card.body.addLayout(bar)
        outer.addWidget(range_card)

        preview = QGridLayout()
        preview.setHorizontalSpacing(12)
        preview.setVerticalSpacing(12)
        self.stat_total = MiniStat("总使用时长")
        self.stat_files = MiniStat("文件变动")
        self.stat_office = MiniStat("办公文档变动")
        self.stat_traffic = MiniStat("整机流量")
        for index, tile in enumerate(
            (self.stat_total, self.stat_files, self.stat_office, self.stat_traffic)
        ):
            preview.addWidget(tile, 0, index)
            preview.setColumnStretch(index, 1)
        outer.addLayout(preview)

        action_card = Card("导出", "HTML 报告内嵌图表脚本，可离线双击打开，无需联网")
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        excel_button = QPushButton("导出 Excel 明细")
        excel_button.setObjectName("Primary")
        excel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        excel_button.clicked.connect(self._export_excel)
        html_button = QPushButton("导出 HTML 报告")
        html_button.setObjectName("Secondary")
        html_button.setCursor(Qt.CursorShape.PointingHandCursor)
        html_button.clicked.connect(self._export_html)
        buttons.addWidget(excel_button)
        buttons.addWidget(html_button)
        buttons.addStretch(1)
        action_card.body.addLayout(buttons)
        outer.addWidget(action_card)
        outer.addStretch(1)

    def _on_range_changed(self) -> None:
        custom = self.range_combo.currentData() == "custom"
        self.start_edit.setVisible(custom)
        self.range_dash.setVisible(custom)
        self.end_edit.setVisible(custom)
        self.refresh_preview()

    def _range(self) -> tuple[date, date]:
        key = self.range_combo.currentData()
        today = date.today()
        if key == "today":
            return today, today
        if key == "7d":
            return today - timedelta(days=6), today
        if key == "month":
            return month_bounds(today)
        start = self.start_edit.date().toPyDate()
        end = self.end_edit.date().toPyDate()
        if start > end:
            start, end = end, start
        return start, end

    def refresh_preview(self) -> None:
        start, end = self._range()
        a, i, l = self.db.usage_totals(start.isoformat(), end.isoformat())
        start_iso = f"{start.isoformat()} 00:00:00"
        end_iso = f"{(end + timedelta(days=1)).isoformat()} 00:00:00"
        groups = self.db.group_counts_between(start_iso, end_iso, self.get_config().office_extensions)
        bin_, bout_ = self.db.network_host_totals(start.isoformat(), end.isoformat())
        self.stat_total.set_value(human_duration(a + i + l))
        self.stat_files.set_value(str(groups.get("all", 0)))
        self.stat_office.set_value(str(groups.get("office", 0)), "#F0A868")
        self.stat_traffic.set_value(human_size(bin_ + bout_), "#5AA9E6")

    def _export_excel(self) -> None:
        start, end = self._range()
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 Excel", f"使用行为报告_{start.isoformat()}_{end.isoformat()}.xlsx",
            "Excel 文件 (*.xlsx)",
        )
        if not path:
            return
        try:
            count = export_excel(self.db, self.get_config(), path, start, end)
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"无法生成 Excel：\n{exc}")
            return
        QMessageBox.information(self, "导出完成", f"已导出 {count} 条文件事件及统计到：\n{path}")

    def _export_html(self) -> None:
        start, end = self._range()
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 HTML 报告", f"使用行为报告_{start.isoformat()}_{end.isoformat()}.html",
            "HTML 文件 (*.html)",
        )
        if not path:
            return
        try:
            count = export_html(self.db, self.get_config(), path, start, end)
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"无法生成 HTML 报告：\n{exc}")
            return
        QMessageBox.information(
            self, "导出完成",
            f"已生成含 {count} 条文件事件的可视化报告：\n{path}\n\n可直接双击用浏览器离线打开。",
        )

    def on_shown(self) -> None:
        self.refresh_preview()