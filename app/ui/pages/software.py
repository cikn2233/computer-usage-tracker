from __future__ import annotations

from datetime import date

from PyQt6.QtCore import QEvent, QFileInfo, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFileIconProvider,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.database import Database
from app.ui.plotly_charts import PlotView, traffic_figure
from app.ui.widgets import Card, PageHeader, make_item, make_table
from app.utils import human_duration, human_size


def _rate_text(bytes_per_sec: float) -> str:
    return f"{human_size(bytes_per_sec)}/s" if bytes_per_sec >= 1 else "—"


class SoftwarePage(QWidget):
    app_selected = pyqtSignal(dict)
    app_cleared = pyqtSignal()

    def __init__(self, db: Database, config_provider, process_monitor=None,
                 network_monitor=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.get_config = config_provider
        self.pm = process_monitor
        self.nm = network_monitor
        self._rows: list[dict] = []
        self._icon_provider = QFileIconProvider()
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(3000)
        self._auto_timer.timeout.connect(self._auto_refresh)
        self._build()
        self.refresh()
        self._auto_timer.start()
        self.traffic_chart.installEventFilter(self)
        proxy = self.traffic_chart.focusProxy()
        if proxy is not None:
            proxy.installEventFilter(self)
        self.table.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        # WebEngine 与无滚动条的表格会吞掉滚轮，统一转交给整页滚动区
        if event.type() == QEvent.Type.Wheel:
            if abs(event.angleDelta().x()) > abs(event.angleDelta().y()):
                return super().eventFilter(obj, event)
            if obj in (self.traffic_chart, self.traffic_chart.focusProxy(), self.table.viewport()):
                QApplication.sendEvent(self._scroll.viewport(), event)
                return True
        return super().eventFilter(obj, event)

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 18)
        outer.setSpacing(14)
        self.header = PageHeader("软件监测", "前台有效使用时长与网络流量 · 选中软件可在右侧查看历史")
        refresh_button = QPushButton("刷新")
        refresh_button.setObjectName("Primary")
        refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_button.clicked.connect(self.refresh)
        self.header.add_action(refresh_button)
        outer.addWidget(self.header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("ScrollBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 2, 8, 8)
        layout.setSpacing(14)

        traffic_card = Card("实时网络流量", "整机网卡速率")
        self.traffic_card = traffic_card
        self.rate_label = QLabel("—")
        self.rate_label.setObjectName("DetailValue")
        traffic_card.add_action(self.rate_label)
        self.traffic_chart = PlotView(min_height=200)
        self.traffic_chart.setFixedHeight(230)
        traffic_card.body.addWidget(self.traffic_chart)
        self.traffic_note = QLabel("")
        self.traffic_note.setObjectName("HelperText")
        self.traffic_note.setWordWrap(True)
        traffic_card.body.addWidget(self.traffic_note)
        layout.addWidget(traffic_card)

        table_card = Card("软件使用与流量明细", "今日累计 + 实时速率 · 按前台时长排序")
        self.table = make_table(
            ["软件", "前台时长", "后台时长", "下载", "上传", "总流量", "实时下载", "实时上传"],
            [-1, 100, 100, 90, 90, 90, 90, 90],
        )
        self.table.setIconSize(QSize(18, 18))
        # 表格不再内部滚动：高度随行数展开，整页统一一条滚动条
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.empty_label = QLabel("暂无软件使用记录 · 保持程序运行即可自动采集")
        self.empty_label.setObjectName("EmptyHint")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setMinimumHeight(120)
        self.empty_label.hide()
        table_card.body.addWidget(self.table)
        table_card.body.addWidget(self.empty_label)
        layout.addWidget(table_card)
        layout.addStretch(1)
        self._scroll.setWidget(body)
        outer.addWidget(self._scroll, 1)

    # -------- refresh --------

    def _auto_refresh(self) -> None:
        if not self.isVisible():
            return
        self._refresh_traffic()
        if not self.table.hasFocus():
            self._refresh_table()

    def refresh(self) -> None:
        self._refresh_traffic()
        self._refresh_table()

    def _refresh_traffic(self) -> None:
        samples = self.db.network_samples(limit=120)
        times = [s["sample_time"][11:19] for s in samples]
        down = [s["bytes_in"] / 2.0 / 1024 for s in samples]
        up = [s["bytes_out"] / 2.0 / 1024 for s in samples]
        self.traffic_chart.render(traffic_figure(times, down, up))
        if down and up:
            self.rate_label.setText(f"↓ {human_size(down[-1] * 1024)}/s   ↑ {human_size(up[-1] * 1024)}/s")
        per_app = bool(self.nm and self.nm.per_app_available)
        if per_app:
            self.traffic_note.setText("已启用管理员模式：下方流量按软件归属统计（仅 TCP 连接）。")
        else:
            self.traffic_note.setText(
                "当前为整机流量统计。按软件统计流量需要以管理员身份运行（可在设置中一键提权重启），"
                "且仅覆盖 TCP 连接。"
            )

    def _refresh_table(self) -> None:
        today = date.today().isoformat()
        apps = {x["app_key"]: x for x in self.db.app_ranking(today, today, limit=200)}
        nets = {x["app_key"]: x for x in self.db.network_ranking(today, today, limit=200)}
        keys = list(apps.keys())
        for k in nets:
            if k not in apps:
                keys.append(k)
        fg_keys = {a["app_key"] for a in (self.pm.running_apps() if self.pm else []) if a["foreground"]}
        rates = self.nm.live_rates() if self.nm else {}

        def sort_key(k):
            fg = int(apps.get(k, {}).get("fg", 0))
            traffic = int(nets.get(k, {}).get("bin", 0)) + int(nets.get(k, {}).get("bout", 0))
            return (-fg, -traffic)

        keys.sort(key=sort_key)
        keys = keys[:80]
        rows = []
        for k in keys:
            a = apps.get(k, {})
            n = nets.get(k, {})
            rows.append({
                "app_key": k,
                "name": a.get("name") or n.get("name") or k,
                "exe": a.get("exe", ""),
                "fg": int(a.get("fg", 0)),
                "bg": int(a.get("bg", 0)),
                "bin": int(n.get("bin", 0)),
                "bout": int(n.get("bout", 0)),
                "rin": rates.get(k, (0.0, 0.0))[0],
                "rout": rates.get(k, (0.0, 0.0))[1],
                "foreground_now": k in fg_keys,
            })
        self._rows = rows
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            name_item = make_item(row["name"], bold=row["foreground_now"])
            if row["exe"]:
                icon = self._icon_provider.icon(QFileInfo(row["exe"]))
                if not icon.isNull():
                    name_item.setIcon(icon)
            name_item.setToolTip(row["exe"] or row["app_key"])
            self.table.setItem(index, 0, name_item)
            self.table.setItem(index, 1, make_item(human_duration(row["fg"]), "#4080FF"))
            self.table.setItem(index, 2, make_item(human_duration(row["bg"]), "#9AA4B2"))
            self.table.setItem(index, 3, make_item(human_size(row["bin"]), "#6B7686", align_right=True))
            self.table.setItem(index, 4, make_item(human_size(row["bout"]), "#6B7686", align_right=True))
            self.table.setItem(
                index, 5, make_item(human_size(row["bin"] + row["bout"]), "#5AA9E6", align_right=True)
            )
            self.table.setItem(index, 6, make_item(_rate_text(row["rin"]), "#4080FF", align_right=True))
            self.table.setItem(index, 7, make_item(_rate_text(row["rout"]), "#E6A23C", align_right=True))
        self.table.setUpdatesEnabled(True)
        if rows:
            header_h = self.table.horizontalHeader().height()
            row_h = self.table.verticalHeader().defaultSectionSize()
            self.table.setFixedHeight(
                header_h + row_h * len(rows) + 2 * self.table.frameWidth()
            )
            self.table.show()
            self.empty_label.hide()
        else:
            self.table.hide()
            self.empty_label.show()

    def _on_selection(self) -> None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            self.app_cleared.emit()
            return
        index = rows[0].row()
        if 0 <= index < len(self._rows):
            self.app_selected.emit(self._rows[index])

    def on_shown(self) -> None:
        self.refresh()