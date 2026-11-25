from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.database import Database
from app.monitors.power_events import compute_powered_seconds
from app.ui.plotly_charts import PlotView, donut_figure, pie_figure, usage_figure
from app.ui.theme import EVENT_COLORS, current_palette
from app.ui.widgets import Card, PageHeader, StatCard, exe_icon, make_item, make_table
from app.utils import (
    event_type_label,
    greeting,
    human_duration,
    human_size,
    reveal_in_explorer,
    weekday_cn,
)

_PIE_COLORS = ["#4080FF", "#57B894", "#F0A868", "#5AA9E6", "#A0A8B8", "#E0655A"]


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
        elif item.layout() is not None:
            _clear_layout(item.layout())


def _app_label(row: dict) -> str:
    return row.get("name") or row.get("app_key") or "未知软件"


class OverviewPage(QWidget):
    nav_requested = pyqtSignal(str)

    def __init__(self, db: Database, config_provider, parent=None):
        super().__init__(parent)
        self.db = db
        self.get_config = config_provider
        self._recent_rows: list[dict] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 18)
        outer.setSpacing(14)
        self.header = PageHeader("首页概览", "")
        outer.addWidget(self.header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("ScrollBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 2, 8, 8)
        layout.setSpacing(14)

        cards = QGridLayout()
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(12)
        self.card_total = StatCard("今日使用时长", "#4080FF")
        self.card_active = StatCard("活跃使用时长", "#57B894")
        self.card_office = StatCard("今日办公文档变动", "#F0A868")
        self.card_traffic = StatCard("流量 TOP 软件", "#5AA9E6")
        for index, card in enumerate(
            (self.card_total, self.card_active, self.card_office, self.card_traffic)
        ):
            cards.addWidget(card, 0, index)
            cards.setColumnStretch(index, 1)
        layout.addLayout(cards)

        middle = QHBoxLayout()
        middle.setSpacing(12)
        trend_card = Card("近 7 天整机使用时长", "活跃 / 闲置 / 锁屏堆叠对比 · 单位：小时")
        self.trend_chart = PlotView(min_height=280)
        self.trend_chart.setFixedHeight(368)
        trend_card.body.addWidget(self.trend_chart)
        middle.addWidget(trend_card, 3)

        right = QVBoxLayout()
        right.setSpacing(12)
        donut_card = Card("今日软件使用时长", "仅统计前台有效使用")
        donut_row = QHBoxLayout()
        donut_row.setSpacing(10)
        self.software_donut = PlotView(min_height=150)
        self.software_donut.setFixedHeight(150)
        donut_row.addWidget(self.software_donut, 1)
        self.software_legend = QWidget()
        self.software_legend.setFixedWidth(186)
        self.software_legend_layout = QVBoxLayout(self.software_legend)
        self.software_legend_layout.setContentsMargins(0, 0, 0, 0)
        self.software_legend_layout.setSpacing(3)
        donut_row.addWidget(self.software_legend)
        donut_card.body.addLayout(donut_row)
        right.addWidget(donut_card, 1)
        pie_card = Card("办公文档类型分布", "Word / Excel / PDF / PPT")
        self.office_pie = PlotView(min_height=150)
        self.office_pie.setFixedHeight(150)
        pie_card.body.addWidget(self.office_pie)
        right.addWidget(pie_card, 1)
        middle.addLayout(right, 2)
        layout.addLayout(middle)

        recent_card = Card("最近办公文档变动", "双击记录可打开文件所在位置")
        self.recent_card = recent_card
        view_all = QPushButton("查看全部")
        view_all.setObjectName("Ghost")
        view_all.setCursor(Qt.CursorShape.PointingHandCursor)
        view_all.clicked.connect(lambda: self.nav_requested.emit("events"))
        recent_card.add_action(view_all)
        self.recent_table = make_table(
            ["时间", "类型", "文件名", "操作软件（推测）", "完整路径"],
            [120, 64, 200, 130, -1],
        )
        self.recent_table.setMinimumHeight(8 * 33 + 34)
        self.recent_table.cellDoubleClicked.connect(self._open_recent)
        self.recent_empty = QLabel("暂无办公文档变动 · 请在设置中选择监测目录")
        self.recent_empty.setObjectName("EmptyHint")
        self.recent_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recent_empty.setMinimumHeight(90)
        self.recent_empty.hide()
        recent_card.body.addWidget(self.recent_table)
        recent_card.body.addWidget(self.recent_empty)
        layout.addWidget(recent_card)
        layout.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

    def refresh(self) -> None:
        today = date.today()
        active, idle, lock = self.db.usage_totals(today.isoformat(), today.isoformat())
        total = active + idle + lock
        ratio = int(active * 100 / total) if total else 0
        config = self.get_config()
        self.card_total.set_value(human_duration(total), "活跃 + 闲置 + 锁屏")
        self.card_active.set_value(human_duration(active), f"占比 {ratio}% · 鼠标键盘活跃")

        start_iso = f"{today.isoformat()} 00:00:00"
        end_iso = f"{(today + timedelta(days=1)).isoformat()} 00:00:00"
        groups = self.db.group_counts_between(start_iso, end_iso, config.office_extensions)
        self.card_office.set_value(str(groups.get("office", 0)), "Word / Excel / PDF / PPT 等")

        ranking = self.db.network_ranking(today.isoformat(), today.isoformat(), limit=1)
        if ranking:
            top = ranking[0]
            self.card_traffic.set_value(
                top["name"], human_size(int(top["bin"]) + int(top["bout"])) + " · 今日累计"
            )
        else:
            bin_, bout_ = self.db.network_host_totals(today.isoformat(), today.isoformat())
            self.card_traffic.set_value(
                human_size(bin_ + bout_), "整机流量（按软件需管理员）"
            )

        self.header.set_subtitle(
            f"{greeting()}，今天是 {today.year} 年 {today.month} 月 {today.day} 日 · "
            f"{weekday_cn(today)} · 数据完全保存在本机"
        )

        days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
        usage = self.db.usage_daily_map(days[0].isoformat(), days[-1].isoformat())
        labels = [f"{d.month:02d}-{d.day:02d}" for d in days]
        a = [usage.get(d.isoformat(), (0, 0, 0))[0] / 3600 for d in days]
        i = [usage.get(d.isoformat(), (0, 0, 0))[1] / 3600 for d in days]
        l = [usage.get(d.isoformat(), (0, 0, 0))[2] / 3600 for d in days]
        self.trend_chart.render(usage_figure(labels, a, i, l))

        apps = self.db.app_ranking(today.isoformat(), today.isoformat(), limit=6)
        apps = [x for x in apps if int(x["fg"]) > 0]
        self.software_donut.render(donut_figure(
            [_app_label(x) for x in apps],
            [round(int(x["fg"]) / 60, 1) for x in apps],
            _PIE_COLORS, "分钟", show_legend=False,
        ))
        _clear_layout(self.software_legend_layout)
        total_fg = sum(int(x["fg"]) for x in apps)
        if not apps:
            empty = QLabel("今日暂无前台使用记录")
            empty.setObjectName("EmptyHint")
            self.software_legend_layout.addWidget(empty)
        for index, row in enumerate(apps):
            line = QHBoxLayout()
            line.setSpacing(6)
            dot = QLabel()
            dot.setFixedSize(6, 6)
            dot.setStyleSheet(
                f"background: {_PIE_COLORS[index % len(_PIE_COLORS)]}; border-radius: 3px;"
            )
            icon = QLabel()
            icon.setFixedSize(16, 16)
            icon.setPixmap(exe_icon(row.get("exe", ""), 16))
            label = _app_label(row)
            name = QLabel()
            name.setObjectName("DetailBody")
            name.setText(name.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, 88))
            name.setToolTip(f"{label}\n{row.get('exe', '')}")
            fg = int(row["fg"])
            pct = int(fg * 100 / total_fg) if total_fg else 0
            duration = QLabel(human_duration(fg))
            duration.setObjectName("DetailLabel")
            duration.setToolTip(f"占比 {pct}%")
            line.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
            line.addWidget(icon)
            line.addWidget(name, 1)
            line.addWidget(duration)
            self.software_legend_layout.addLayout(line)
        self.software_legend_layout.addStretch(1)

        types = self.db.office_type_counts(start_iso, end_iso, config.office_extensions)
        labels_t = [k for k, v in types.items() if v > 0]
        values_t = [types[k] for k in labels_t]
        self.office_pie.render(pie_figure(labels_t, values_t, _PIE_COLORS))

        rows = self.db.recent_file_events(8, config.office_extensions)
        self._recent_rows = rows
        self.recent_table.setUpdatesEnabled(False)
        self.recent_table.setRowCount(0)
        self.recent_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            self.recent_table.setItem(index, 0, make_item(row["event_time"][5:16], "#6B7686"))
            self.recent_table.setItem(
                index, 1,
                make_item(event_type_label(row["event_type"]),
                          EVENT_COLORS.get(row["event_type"]), bold=True),
            )
            self.recent_table.setItem(index, 2, make_item(row["name"], tooltip=row["name"]))
            self.recent_table.setItem(
                index, 3, make_item(row.get("process_name") or "—", "#9AA4B2")
            )
            self.recent_table.setItem(index, 4, make_item(row["path"], "#6B7686", tooltip=row["path"]))
        self.recent_table.setUpdatesEnabled(True)
        if rows:
            self.recent_table.show()
            self.recent_empty.hide()
        else:
            self.recent_table.hide()
            self.recent_empty.show()
        self.recent_card.set_subtitle(f"共 {len(rows)} 条最近记录 · 双击打开所在位置")

    def _open_recent(self, row: int, _column: int) -> None:
        if 0 <= row < len(self._recent_rows):
            reveal_in_explorer(self._recent_rows[row]["path"])