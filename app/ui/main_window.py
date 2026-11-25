from __future__ import annotations

import logging
import sqlite3
import time
from datetime import date, datetime

import psutil
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QCloseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from app.config import APP_NAME, DATA_DIR, VERSION, AppConfig
from app.database import Database
from app.monitors.activity import SessionTracker
from app.monitors.file_monitor import FileMonitor
from app.monitors.network_monitor import NetworkMonitor
from app.monitors.power_events import PowerEventsWorker
from app.monitors.process_monitor import ProcessMonitor
from app.monitors.reminders import AppLimitReminder, DocBurstReminder
from app.ui.detail_panel import DetailPanel
from app.ui.pages.duration import DurationPage
from app.ui.pages.events import EventsPage
from app.ui.pages.export import ExportPage
from app.ui.pages.overview import OverviewPage
from app.ui.pages.settings import SettingsPage
from app.ui.pages.software import SoftwarePage
from app.ui.theme import apply_theme, make_app_icon, make_nav_icon
from app.utils import open_terminal_folder, relaunch_elevated

log = logging.getLogger(__name__)

NAV_ITEMS = [
    ("overview", "首页概览"),
    ("duration", "时长统计"),
    ("software", "软件监测"),
    ("events", "文件日志"),
    ("settings", "设置"),
    ("export", "导出"),
]


class MainWindow(QMainWindow):
    def __init__(self, db: Database, config: AppConfig):
        super().__init__()
        self.db = db
        self.config = config
        self._quitting = False
        self._paused_by_user = False
        self._power_worker: PowerEventsWorker | None = None
        self._tray_notice_shown = False
        self._last_overview_refresh = 0.0
        self.nav_buttons: list[QPushButton] = []
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(make_app_icon())
        self.resize(1480, 920)
        self.setMinimumSize(1280, 780)
        self._build_ui()
        self._build_tray()
        self._start_services()
        self._apply_sidebar_collapsed(config.sidebar_collapsed)

    # -------- UI --------

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_sidebar())

        content = QWidget()
        content.setObjectName("ContentRoot")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._build_topbar())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        self.stack = QStackedWidget()
        self.overview = OverviewPage(self.db, lambda: self.config)
        self.duration = DurationPage(self.db, lambda: self.config)
        self.pm = ProcessMonitor(self.db, self.config, self)
        self.nm = NetworkMonitor(self.db, self.config, self)
        self.software = SoftwarePage(self.db, lambda: self.config, self.pm, self.nm)
        self.events = EventsPage(self.db, lambda: self.config)
        self.settings_page = SettingsPage(self.db, self.config)
        self.export_page = ExportPage(self.db, lambda: self.config)
        for page in (
            self.overview, self.duration, self.software,
            self.events, self.settings_page, self.export_page,
        ):
            self.stack.addWidget(page)
        body_layout.addWidget(self.stack, 1)
        self.detail = DetailPanel(self.db)
        body_layout.addWidget(self.detail)
        content_layout.addWidget(body, 1)
        outer.addWidget(content, 1)

        self.overview.nav_requested.connect(self._on_nav_requested)
        self.duration.power_refresh_requested.connect(self.refresh_power_events)
        self.software.app_selected.connect(self.detail.show_app)
        self.software.app_cleared.connect(self.detail.clear_app)
        self.events.event_selected.connect(self.detail.show_event)
        self.events.event_cleared.connect(self.detail.clear_event)
        self.events.stats_updated.connect(self.detail.set_event_stats)
        self.settings_page.config_saved.connect(self._on_config_saved)
        self.settings_page.events_cleared.connect(self._on_events_cleared)
        self.settings_page.theme_changed.connect(self._apply_theme)
        self.settings_page.elevate_requested.connect(self._elevate)
        self.pm.reminder.connect(self._show_reminder)
        self.nm.reminder.connect(self._show_reminder)
        if self.nav_buttons:
            self.nav_buttons[0].setChecked(True)

    def _build_sidebar(self) -> QFrame:
        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(218)
        layout = QVBoxLayout(self.sidebar)
        layout.setContentsMargins(16, 20, 14, 16)
        layout.setSpacing(4)

        logo_row = QHBoxLayout()
        logo_row.setSpacing(10)
        self.logo = QLabel()
        self.logo.setPixmap(make_app_icon(36).pixmap(36, 36))
        self.logo.setFixedSize(36, 36)
        logo_row.addWidget(self.logo)
        self.brand_box = QWidget()
        brand_layout = QVBoxLayout(self.brand_box)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(0)
        brand_one = QLabel("电脑使用行为")
        brand_one.setObjectName("BrandTitle")
        brand_two = QLabel("溯源监测系统")
        brand_two.setObjectName("BrandTitle")
        brand_layout.addWidget(brand_one)
        brand_layout.addWidget(brand_two)
        logo_row.addWidget(self.brand_box)
        logo_row.addStretch(1)
        layout.addLayout(logo_row)
        layout.addSpacing(6)
        self.tag = QLabel("LOCAL-FIRST · 隐私优先")
        self.tag.setObjectName("BrandSub")
        layout.addWidget(self.tag)
        layout.addSpacing(16)

        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, (key, label) in enumerate(NAV_ITEMS):
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setMinimumHeight(40)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(make_nav_icon(key, 18, "#6B7686"))
            button.clicked.connect(lambda _checked=False, i=index: self._goto(i))
            group.addButton(button)
            layout.addWidget(button)
            self.nav_buttons.append(button)

        layout.addStretch(1)
        self.sidebar_box = QFrame()
        self.sidebar_box.setObjectName("SidebarBox")
        box_layout = QVBoxLayout(self.sidebar_box)
        box_layout.setContentsMargins(12, 10, 12, 12)
        box_layout.setSpacing(8)
        caption = QLabel("运行概况")
        caption.setObjectName("SidebarMuted")
        box_layout.addWidget(caption)
        self.sidebar_dirs = QLabel("0 个监测目录")
        self.sidebar_dirs.setObjectName("SidebarValue")
        box_layout.addWidget(self.sidebar_dirs)
        self.sidebar_events = QLabel("0 条今日事件")
        self.sidebar_events.setObjectName("SidebarValue")
        box_layout.addWidget(self.sidebar_events)
        layout.addWidget(self.sidebar_box)
        layout.addSpacing(8)
        collapse_row = QHBoxLayout()
        self.collapse_button = QPushButton("折叠导航")
        self.collapse_button.setObjectName("Ghost")
        self.collapse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_button.clicked.connect(self._toggle_sidebar)
        collapse_row.addWidget(self.collapse_button)
        collapse_row.addStretch(1)
        layout.addLayout(collapse_row)
        self.version_label = QLabel(f"v{VERSION} · 数据仅存本机")
        self.version_label.setObjectName("SidebarMuted")
        layout.addWidget(self.version_label)
        return self.sidebar

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(62)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 0, 20, 0)
        layout.setSpacing(10)
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet("background: #57B894; border-radius: 4px;")
        self.top_hint = QLabel("完全离线 · 文件与使用数据仅保存在本机")
        self.top_hint.setObjectName("TopHint")
        self.status_pill = QLabel("初始化中")
        self.status_pill.setObjectName("StatusPill")
        self.status_pill.setProperty("state", "off")
        self.status_pill.setFixedHeight(24)
        self.status_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pause_button = QPushButton("暂停监测")
        self.pause_button.setObjectName("Secondary")
        self.pause_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_button.clicked.connect(self._on_pause_clicked)
        layout.addWidget(dot)
        layout.addWidget(self.top_hint)
        layout.addStretch(1)
        layout.addWidget(self.status_pill)
        layout.addWidget(self.pause_button)
        return bar

    # -------- sidebar / theme --------

    def _toggle_sidebar(self) -> None:
        self._apply_sidebar_collapsed(not self.config.sidebar_collapsed)

    def _apply_sidebar_collapsed(self, collapsed: bool) -> None:
        self.config.sidebar_collapsed = collapsed
        self.sidebar.setFixedWidth(64 if collapsed else 218)
        self.brand_box.setVisible(not collapsed)
        self.tag.setVisible(not collapsed)
        self.sidebar_box.setVisible(not collapsed)
        self.version_label.setVisible(not collapsed)
        self.collapse_button.setText("»" if collapsed else "折叠导航")
        for (key, label), button in zip(NAV_ITEMS, self.nav_buttons):
            button.setText("" if collapsed else label)
            button.setToolTip(label)
            color = "#8FB4F7" if button.isChecked() else "#6B7686"
            button.setIcon(make_nav_icon(key, 18, color))

    def _apply_theme(self, theme: str) -> None:
        self.config.theme = theme
        apply_theme(QApplication.instance(), theme)
        self._apply_sidebar_collapsed(self.config.sidebar_collapsed)
        self._refresh_current_page()
        self.detail.update()

    def _refresh_current_page(self) -> None:
        index = self.stack.currentIndex()
        if index == 0:
            self.overview.refresh()
        elif index == 1:
            self.duration.refresh()
        elif index == 2:
            self.software.refresh()
        elif index == 3:
            self.events.refresh()
        elif index == 5:
            self.export_page.refresh_preview()

    # -------- services --------

    def _start_services(self) -> None:
        self.monitor = FileMonitor(self.config)
        self.monitor.set_app_provider(lambda: self.pm.current_foreground())
        self.tracker = SessionTracker(self.db, self.config.idle_threshold_sec, self)
        self.burst = DocBurstReminder(self.db, self.config, self)
        self.burst.reminder.connect(self._show_reminder)
        self.app_limit = AppLimitReminder(self.db, self.config, self)
        self.app_limit.reminder.connect(self._show_reminder)
        self.tracker.start()
        self._paused_by_user = not self.config.start_monitoring
        if self.config.start_monitoring:
            if self.config.monitor_roots:
                self.monitor.start(self.config)
            if self.config.process_tracking:
                self.pm.start()
            if self.config.traffic_tracking:
                self.nm.start()
            self.burst.start()
            self.app_limit.start()
        self.detail.set_scope(self.config.monitor_roots)

        self.drain_timer = QTimer(self)
        self.drain_timer.setInterval(800)
        self.drain_timer.timeout.connect(self._drain_events)
        self.drain_timer.start()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(10000)
        self.refresh_timer.timeout.connect(self._periodic_refresh)
        self.refresh_timer.start()
        self._update_status()
        self._refresh_detail_live()
        QTimer.singleShot(600, self.refresh_power_events)

    def _build_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        self.act_toggle: QAction | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(make_app_icon(), self)
        tray.setToolTip(APP_NAME)
        menu = QMenu(self)
        act_show = QAction("打开主界面", self)
        act_show.triggered.connect(self._show_window)
        self.act_toggle = QAction("暂停监测", self)
        self.act_toggle.triggered.connect(self._on_pause_clicked)
        act_data = QAction("打开数据目录", self)
        act_data.triggered.connect(lambda: open_terminal_folder(DATA_DIR))
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_show)
        menu.addAction(self.act_toggle)
        menu.addSeparator()
        menu.addAction(act_data)
        menu.addSeparator()
        menu.addAction(act_quit)
        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_activated)
        tray.show()
        self.tray = tray

    # -------- navigation / status --------

    def _goto(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for position, button in enumerate(self.nav_buttons):
            button.setChecked(position == index)
        if index == 0:
            self.overview.refresh()
            self._last_overview_refresh = time.monotonic()
        elif index == 1:
            self.duration.refresh()
        elif index == 2:
            self.software.on_shown()
        elif index == 3:
            self.events.on_shown()
        elif index == 4:
            self.settings_page.refresh_data_info()
        elif index == 5:
            self.export_page.on_shown()
        if index != 2:
            self.detail.clear_app()
        if index != 3:
            self.detail.stats_frame.hide()
            self.detail.event_frame.hide()
        else:
            self.detail.event_frame.show()
        self._apply_sidebar_collapsed(self.config.sidebar_collapsed)
        self._refresh_detail_live()

    def _on_nav_requested(self, page: str) -> None:
        if page == "events":
            self._goto(3)

    def _status_text(self) -> str:
        if self.monitor.running:
            return "运行中"
        if not self.config.monitor_roots:
            return "未配置目录"
        if self._paused_by_user:
            return "已暂停"
        return "未启动"

    def _update_status(self) -> None:
        running = self.monitor.running
        has_roots = bool(self.config.monitor_roots)
        if running:
            state, text = "on", "监测运行中"
        elif not has_roots:
            state, text = "off", "未配置监测目录"
        elif self._paused_by_user:
            state, text = "paused", "监测已暂停"
        else:
            state, text = "off", "监测未启动"
        self.status_pill.setText(text)
        self.status_pill.setProperty("state", state)
        self.status_pill.style().unpolish(self.status_pill)
        self.status_pill.style().polish(self.status_pill)
        if self.monitor.errors:
            self.status_pill.setToolTip("\n".join(self.monitor.errors))
        else:
            self.status_pill.setToolTip("目录：" + ("、".join(self.monitor.watched_roots) or "无"))
        self.pause_button.setText("暂停监测" if not self._paused_by_user else "继续监测")
        if self.act_toggle is not None:
            self.act_toggle.setText("继续监测" if self._paused_by_user else "暂停监测")

    def _on_pause_clicked(self) -> None:
        if not self._paused_by_user:
            self.monitor.stop()
            self.tracker.stop()
            self.pm.stop()
            self.nm.stop()
            self.burst.stop()
            self.app_limit.stop()
            self._paused_by_user = True
        else:
            if not self.config.monitor_roots:
                self._goto(4)
                return
            self.tracker.start()
            self.monitor.start(self.config)
            if self.config.process_tracking:
                self.pm.start()
            if self.config.traffic_tracking:
                self.nm.start()
            self.burst.start()
            self.app_limit.start()
            self._paused_by_user = False
            if self.monitor.errors:
                QMessageBox.warning(self, "启动文件监测失败", "\n".join(self.monitor.errors))
        self._update_status()
        self._refresh_detail_live()
        self.overview.refresh()
        self._last_overview_refresh = time.monotonic()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_window()

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _show_reminder(self, title: str, body: str) -> None:
        if self.tray is not None:
            self.tray.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 5000)
        self.top_hint.setText(f"{title}：{body}")
        QTimer.singleShot(8000, self._restore_hint)

    def _restore_hint(self) -> None:
        self.top_hint.setText("完全离线 · 文件与使用数据仅保存在本机")

    def _elevate(self) -> None:
        answer = QMessageBox.question(
            self, "以管理员身份重启",
            "按软件统计网络流量需要管理员权限。\n程序将以管理员身份重新启动，是否继续？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if relaunch_elevated():
            self._quit()
        else:
            QMessageBox.warning(self, "提权失败", "无法以管理员身份重启，请手动右键以管理员身份运行。")

    # -------- refresh loops --------

    def _drain_events(self) -> None:
        items = self.monitor.drain()
        if not items:
            return
        try:
            self.db.insert_file_events(items)
        except sqlite3.Error:
            log.exception("cannot insert file events")
            return
        current = self.stack.currentIndex()
        if current == 0:
            now = time.monotonic()
            if now - self._last_overview_refresh >= 2.5:
                self.overview.refresh()
                self._last_overview_refresh = now
        elif current == 3:
            self.events.on_events_added()
        if self.settings_page.isVisible():
            self.settings_page.refresh_data_info()
        self._refresh_detail_live()
        self._update_status()

    def _periodic_refresh(self) -> None:
        current = self.stack.currentIndex()
        if current == 0:
            self.overview.refresh()
            self._last_overview_refresh = time.monotonic()
        elif current == 1:
            self.duration.refresh()
        self._refresh_detail_live()
        self._update_status()

    def _refresh_detail_live(self) -> None:
        today = date.today().isoformat()
        active, idle, lock = self.db.usage_totals(today, today)
        counts = self.db.event_counts(date.today())
        boot_time = None
        try:
            boot_time = datetime.fromtimestamp(psutil.boot_time())
        except (OSError, ValueError):
            pass
        self.detail.update_live(
            running=self.monitor.running,
            status_text=self._status_text(),
            session_start=self.tracker.session_start if self.tracker else None,
            boot_time=boot_time,
            today_active=active,
            today_idle=idle,
            today_lock=lock,
            counts=counts,
        )
        self.sidebar_events.setText(f"{sum(counts.values())} 条今日事件")
        self.sidebar_dirs.setText(f"{len(self.config.monitor_roots)} 个监测目录")

    # -------- power events --------

    def refresh_power_events(self) -> None:
        if self._power_worker is not None and self._power_worker.isRunning():
            return
        self.duration.set_power_note("正在读取系统事件日志…")
        worker = PowerEventsWorker(self.config.power_events_days, self)
        worker.loaded.connect(self._on_power_loaded)
        worker.finished.connect(self._on_power_finished)
        self._power_worker = worker
        worker.start()

    def _on_power_loaded(self, events: list, error: str) -> None:
        if events:
            try:
                self.db.insert_power_events(events)
            except sqlite3.Error:
                log.exception("cannot insert power events")
        if error:
            note = f"读取系统事件日志失败：{error}"
        else:
            note = f"已读取 {len(events)} 条电源事件 · 更新于 {datetime.now():%H:%M:%S}"
        self.duration.on_power_updated(note)
        if self.stack.currentIndex() == 0:
            self.overview.refresh()
            self._last_overview_refresh = time.monotonic()
        self._refresh_detail_live()

    def _on_power_finished(self) -> None:
        worker = self._power_worker
        self._power_worker = None
        if worker is not None:
            worker.deleteLater()

    # -------- settings callbacks --------

    def _on_config_saved(self, config: AppConfig) -> None:
        self.config = config
        self.tracker.set_idle_threshold(config.idle_threshold_sec)
        self.monitor.update_config(config)
        self.pm.update_config(config)
        self.nm.update_config(config)
        self.burst.update_config(config)
        self.app_limit.update_config(config)
        self.detail.set_scope(config.monitor_roots)
        if not self._paused_by_user:
            if config.monitor_roots:
                if not self.monitor.start(config) and self.monitor.errors:
                    QMessageBox.warning(self, "文件监测启动失败", "\n".join(self.monitor.errors))
            else:
                self.monitor.stop()
            if config.process_tracking and not self.pm.running:
                self.pm.start()
            elif not config.process_tracking and self.pm.running:
                self.pm.stop()
            if config.traffic_tracking and not self.nm.running:
                self.nm.start()
            elif not config.traffic_tracking and self.nm.running:
                self.nm.stop()
        try:
            self.db.purge_old_logs(config.retention_days)
        except sqlite3.Error:
            log.exception("cannot purge old logs")
        self._apply_sidebar_collapsed(config.sidebar_collapsed)
        self._update_status()
        self._refresh_detail_live()
        self.overview.refresh()
        self._last_overview_refresh = time.monotonic()

    def _on_events_cleared(self) -> None:
        self.events.refresh()
        self.overview.refresh()
        self.detail.clear_event()
        self._refresh_detail_live()
        self.settings_page.refresh_data_info()

    # -------- shutdown --------

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._quitting:
            event.accept()
            return
        if self.config.minimize_to_tray and self.tray is not None:
            event.ignore()
            self.hide()
            if not self._tray_notice_shown:
                self._tray_notice_shown = True
                self.tray.showMessage(
                    APP_NAME, "已最小化到系统托盘，监测将继续运行。",
                    QSystemTrayIcon.MessageIcon.Information, 3000,
                )
            return
        event.ignore()
        self._quit()

    def _quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        if hasattr(self, "drain_timer"):
            self.drain_timer.stop()
        if hasattr(self, "refresh_timer"):
            self.refresh_timer.stop()
        worker = self._power_worker
        if worker is not None and worker.isRunning():
            worker.wait(2500)
        self.monitor.stop()
        self.tracker.stop()
        self.pm.stop()
        self.nm.stop()
        self.burst.stop()
        self.db.close()
        if self.tray is not None:
            self.tray.hide()
        QApplication.quit()