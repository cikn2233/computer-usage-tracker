from __future__ import annotations

from datetime import date, timedelta

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.database import Database
from app.monitors.power_events import kind_label
from app.ui.plotly_charts import PlotView, hbar_figure, usage_figure
from app.ui.widgets import Card, MiniStat, PageHeader, SegmentedControl, make_item, make_table
from app.utils import human_duration, month_bounds, weekday_cn

POWER_NOTES = {
    "boot": "系统启动完成",
    "shutdown": "系统正常关机",
    "sleep": "系统进入睡眠",
    "resume": "从睡眠状态唤醒",
    "unexpected": "非正常断电或重启",
}


class DurationPage(QWidget):
    power_refresh_requested = pyqtSignal()

    def __init__(self, db: Database, config_provider, parent=None):
        super().__init__(parent)
        self.db = db
        self.get_config = config_provider
        self.mode = "bar"
        self._build()
        self.refresh()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 18)
        outer.setSpacing(14)
        self.header = PageHeader("时长统计", "按今日 / 近 7 天 / 本月 / 自定义统计整机与软件使用时长")
        refresh_button = QPushButton("刷新")
        refresh_button.setObjectName("Secondary")
        refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_button.clicked.connect(self.refresh)
        self.header.add_action(refresh_button)
        outer.addWidget(self.header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("ScrollBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 2, 8, 8)
        layout.setSpacing(14)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        range_label = QLabel("时间范围")
        range_label.setObjectName("FieldLabel")
        self.range_combo = QComboBox()
        self.range_combo.addItem("今日", "today")
        self.range_combo.addItem("近 7 天", "7d")
        self.range_combo.addItem("本月", "month")
        self.range_combo.addItem("自定义", "custom")
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
        self.start_edit.dateChanged.connect(lambda: self.refresh())
        self.end_edit.dateChanged.connect(lambda: self.refresh())
        self.period_label = QLabel("")
        self.period_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        bar.addWidget(range_label)
        bar.addWidget(self.range_combo)
        bar.addWidget(self.start_edit)
        bar.addWidget(self.range_dash)
        bar.addWidget(self.end_edit)
        bar.addSpacing(8)
        bar.addWidget(self.period_label)
        bar.addStretch(1)
        layout.addLayout(bar)

        summary = QGridLayout()
        summary.setHorizontalSpacing(12)
        summary.setVerticalSpacing(12)
        self.stat_total = MiniStat("统计总时长")
        self.stat_active = MiniStat("活跃时长")
        self.stat_idle = MiniStat("闲置时长")
        self.stat_lock = MiniStat("锁屏时长")
        for index, tile in enumerate(
            (self.stat_total, self.stat_active, self.stat_idle, self.stat_lock)
        ):
            summary.addWidget(tile, 0, index)
            summary.setColumnStretch(index, 1)
        layout.addLayout(summary)

        chart_card = Card("整机使用时长分布", "按小时统计 · 柱状图")
        self.chart_card = chart_card
        self.mode_control = SegmentedControl([("bar", "柱状图"), ("line", "折线图")], "bar")
        self.mode_control.changed.connect(self._on_mode_changed)
        chart_card.add_action(self.mode_control)
        self.chart = PlotView(min_height=280)
        chart_card.body.addWidget(self.chart)
        layout.addWidget(chart_card)

        rank_card = Card("软件有效使用排行", "仅统计前台窗口时长 · 单位：分钟")
        self.rank_chart = PlotView(min_height=260)
        rank_card.body.addWidget(self.rank_chart)
        layout.addWidget(rank_card)

        power_card = Card("系统开机 / 关机 / 休眠记录", "读取自 Windows 系统事件日志")
        self.power_card = power_card
        power_refresh = QPushButton("刷新系统日志")
        power_refresh.setObjectName("Ghost")
        power_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        power_refresh.clicked.connect(self.power_refresh_requested.emit)
        power_card.add_action(power_refresh)
        self.power_table = make_table(["发生时间", "事件", "代码", "备注"], [168, 150, 76, -1])
        self.power_table.setMinimumHeight(6 * 33 + 34)
        self.power_empty = QLabel("该时间段内没有系统电源事件记录")
        self.power_empty.setObjectName("EmptyHint")
        self.power_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.power_empty.setMinimumHeight(60)
        self.power_empty.hide()
        power_card.body.addWidget(self.power_table)
        power_card.body.addWidget(self.power_empty)
        layout.addWidget(power_card)
        layout.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

    # -------- range --------

    def _on_range_changed(self) -> None:
        custom = self.range_combo.currentData() == "custom"
        self.start_edit.setVisible(custom)
        self.range_dash.setVisible(custom)
        self.end_edit.setVisible(custom)
        self.refresh()

    def _on_mode_changed(self, value: str) -> None:
        self.mode = value
        self.refresh()

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

    def _period_text(self, start: date, end: date) -> str:
        if start == end:
            return f"{start.year} 年 {start.month} 月 {start.day} 日 · {weekday_cn(start)}"
        return f"{start.month} 月 {start.day} 日 — {end.month} 月 {end.day} 日"

    # -------- data --------

    def refresh(self) -> None:
        start, end = self._range()
        if start == end:
            active, idle, lock = self.db.usage_hour_map(start.isoformat())
            labels = [f"{h}时" for h in range(24)]
            a = [v / 3600 for v in active]
            i = [v / 3600 for v in idle]
            l = [v / 3600 for v in lock]
            self.chart_card.set_subtitle("按小时统计 · " + ("柱状图" if self.mode == "bar" else "折线图"))
            total_active, total_idle, total_lock = sum(active), sum(idle), sum(lock)
        else:
            days = [start + timedelta(days=o) for o in range((end - start).days + 1)]
            usage = self.db.usage_daily_map(start.isoformat(), end.isoformat())
            labels = [f"{d.month}/{d.day}" for d in days]
            a = [usage.get(d.isoformat(), (0, 0, 0))[0] / 3600 for d in days]
            i = [usage.get(d.isoformat(), (0, 0, 0))[1] / 3600 for d in days]
            l = [usage.get(d.isoformat(), (0, 0, 0))[2] / 3600 for d in days]
            self.chart_card.set_subtitle("按天统计 · " + ("柱状图" if self.mode == "bar" else "折线图"))
            total_active = sum(usage.get(d.isoformat(), (0, 0, 0))[0] for d in days)
            total_idle = sum(usage.get(d.isoformat(), (0, 0, 0))[1] for d in days)
            total_lock = sum(usage.get(d.isoformat(), (0, 0, 0))[2] for d in days)

        total = total_active + total_idle + total_lock
        self.stat_total.set_value(human_duration(total))
        self.stat_active.set_value(human_duration(total_active), "#57B894")
        self.stat_idle.set_value(human_duration(total_idle), "#F0A868")
        self.stat_lock.set_value(human_duration(total_lock), "#A0A8B8")
        self.period_label.setText(self._period_text(start, end))
        self.chart.render(usage_figure(labels, a, i, l, mode=self.mode))

        apps = self.db.app_ranking(start.isoformat(), end.isoformat(), limit=10)
        apps = [x for x in apps if int(x["fg"]) > 0]
        self.rank_chart.render(hbar_figure(
            [x["name"] for x in apps],
            [round(int(x["fg"]) / 60) for x in apps],
            "#4080FF", " 分钟",
        ))
        self._refresh_power_table(start, end)

    def _refresh_power_table(self, start: date, end: date) -> None:
        start_iso = f"{start.isoformat()} 00:00:00"
        end_iso = f"{(end + timedelta(days=1)).isoformat()} 00:00:00"
        events = self.db.power_events_between(start_iso, end_iso, limit=200)
        events = list(reversed(events))[:40]
        self.power_table.setUpdatesEnabled(False)
        self.power_table.setRowCount(0)
        self.power_table.setRowCount(len(events))
        for index, event in enumerate(events):
            self.power_table.setItem(index, 0, make_item(event["event_time"], "#6B7686"))
            self.power_table.setItem(index, 1, make_item(kind_label(event["kind"])))
            self.power_table.setItem(index, 2, make_item(str(event["event_code"]), "#9AA4B2"))
            self.power_table.setItem(index, 3, make_item(POWER_NOTES.get(event["kind"], ""), "#9AA4B2"))
        self.power_table.setUpdatesEnabled(True)
        if events:
            self.power_table.setMinimumHeight(min(len(events), 10) * 33 + 34)
            self.power_table.show()
            self.power_empty.hide()
        else:
            self.power_table.hide()
            self.power_empty.show()

    def set_power_note(self, text: str) -> None:
        self.power_card.set_subtitle(text)

    def on_power_updated(self, note: str) -> None:
        self.set_power_note(note)
        self._refresh_power_table(*self._range())