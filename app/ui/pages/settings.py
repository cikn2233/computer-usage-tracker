from __future__ import annotations

import os
import re
from dataclasses import replace
from datetime import date
from pathlib import Path

import psutil
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.config import DB_PATH, AppConfig
from app.database import Database
from app.ui.theme import ToggleSwitch, current_palette
from app.ui.widgets import Card, PageHeader, SegmentedControl, hline
from app.utils import human_size, is_autostart_enabled, open_terminal_folder, set_autostart

_SPLIT_RE = re.compile(r"[,，;；\s]+")


def _is_drive_root(path: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:\\?$", path))


def _split_tokens(text: str) -> list[str]:
    return [token for token in _SPLIT_RE.split(text.strip()) if token]


class SettingsPage(QWidget):
    config_saved = pyqtSignal(object)
    events_cleared = pyqtSignal()
    theme_changed = pyqtSignal(str)
    elevate_requested = pyqtSignal()

    def __init__(self, db: Database, config: AppConfig, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self.drive_checks: dict[str, QCheckBox] = {}
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(lambda: self.save_status.setText(""))
        self._build()
        self.load_values(config)

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 18)
        outer.setSpacing(14)
        self.header = PageHeader("设置", "配置监测范围、过滤规则、提醒与本地数据")
        self.save_status = QLabel("")
        self.save_status.setObjectName("NoticeOk")
        save_button = QPushButton("保存并应用")
        save_button.setObjectName("Primary")
        save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        save_button.clicked.connect(self.save)
        self.header.add_action(self.save_status)
        self.header.add_action(save_button)
        outer.addWidget(self.header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("ScrollBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 2, 8, 8)
        layout.setSpacing(14)
        layout.addWidget(self._build_scope_card())
        layout.addWidget(self._build_filter_card())
        layout.addWidget(self._build_process_card())
        layout.addWidget(self._build_usage_card())
        layout.addWidget(self._build_reminder_card())
        layout.addWidget(self._build_limit_card())
        layout.addWidget(self._build_startup_card())
        layout.addWidget(self._build_appearance_card())
        layout.addWidget(self._build_data_card())
        layout.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

    def _build_scope_card(self) -> Card:
        card = Card("监控目录", "勾选磁盘分区或添加文件夹；目录会被递归监测，嵌套目录自动去重")
        drives_title = QLabel("磁盘分区")
        drives_title.setObjectName("FieldLabel")
        card.body.addWidget(drives_title)
        self.drive_container = QWidget()
        self.drive_layout = QVBoxLayout(self.drive_container)
        self.drive_layout.setContentsMargins(0, 0, 0, 0)
        self.drive_layout.setSpacing(6)
        card.body.addWidget(self.drive_container)
        card.body.addWidget(hline())
        folders_title = QLabel("自定义文件夹")
        folders_title.setObjectName("FieldLabel")
        card.body.addWidget(folders_title)
        self.folder_list = QListWidget()
        self.folder_list.setMinimumHeight(96)
        self.folder_list.setMaximumHeight(150)
        card.body.addWidget(self.folder_list)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        add_button = QPushButton("添加文件夹…")
        add_button.setObjectName("Secondary")
        add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        add_button.clicked.connect(self._add_folder)
        remove_button = QPushButton("移除选中")
        remove_button.setObjectName("Ghost")
        remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_button.clicked.connect(self._remove_folder)
        actions.addWidget(add_button)
        actions.addWidget(remove_button)
        actions.addStretch(1)
        card.body.addLayout(actions)
        return card

    def _build_filter_card(self) -> Card:
        card = Card("文件过滤", "减少系统缓存与临时文件刷屏，只留下真正有价值的文件操作")
        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)
        self.ext_edit = QLineEdit()
        self.ext_edit.setPlaceholderText("docx, pdf, xlsx, py, dwg …")
        self._form_row(form, 0, "监测后缀", self.ext_edit, "留空表示监测全部后缀；多个后缀用逗号或空格分隔")
        self.office_edit = QLineEdit()
        self.office_edit.setPlaceholderText("docx, doc, xlsx, xls, pdf, pptx, ppt")
        self._form_row(form, 1, "办公后缀", self.office_edit, "用于「办公文档」分组与类型饼图，可自定义")
        self.excl_edit = QLineEdit()
        self.excl_edit.setPlaceholderText("例如：backup, cache, 下载临时")
        self._form_row(form, 2, "排除关键词", self.excl_edit, "路径中包含任一关键词的文件事件会被忽略")
        self.min_size_spin = QSpinBox()
        self.min_size_spin.setRange(0, 1048576)
        self.min_size_spin.setSuffix(" KB")
        self.min_size_spin.setMaximumWidth(160)
        self._form_row(form, 3, "最小文件大小", self.min_size_spin, "0 表示不限制；用于忽略极小的临时写入")
        self.ignore_junk = ToggleSwitch("忽略 Windows / 缓存 / 临时目录以及 .tmp、.log 等临时文件")
        form.addWidget(self.ignore_junk, 4, 0, 1, 3)
        card.body.addLayout(form)
        return card

    def _build_process_card(self) -> Card:
        card = Card("进程与流量", "内置系统进程黑名单已过滤 svchost 等；可自定义黑白名单")
        self.process_tracking = ToggleSwitch("启用软件使用时长监测（前台 / 后台）")
        self.traffic_tracking = ToggleSwitch("启用网络流量监测")
        card.body.addWidget(self.process_tracking)
        card.body.addWidget(self.traffic_tracking)
        card.body.addWidget(hline())
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        black_label = QLabel("进程黑名单（每行一个进程名）")
        black_label.setObjectName("FieldLabel")
        white_label = QLabel("进程白名单（填写后仅监测这些进程）")
        white_label.setObjectName("FieldLabel")
        self.blacklist_edit = QPlainTextEdit()
        self.blacklist_edit.setPlaceholderText("svchost.exe\nlsass.exe")
        self.blacklist_edit.setFixedHeight(120)
        self.whitelist_edit = QPlainTextEdit()
        self.whitelist_edit.setPlaceholderText("留空表示不启用白名单\nchrome.exe\nwinword.exe")
        self.whitelist_edit.setFixedHeight(120)
        grid.addWidget(black_label, 0, 0)
        grid.addWidget(white_label, 0, 1)
        grid.addWidget(self.blacklist_edit, 1, 0)
        grid.addWidget(self.whitelist_edit, 1, 1)
        card.body.addLayout(grid)
        elevate = QPushButton("以管理员身份重启（启用按软件流量统计）")
        elevate.setObjectName("Secondary")
        elevate.setCursor(Qt.CursorShape.PointingHandCursor)
        elevate.clicked.connect(self.elevate_requested.emit)
        note = QLabel("按软件统计流量需要管理员权限，且仅覆盖 TCP 连接；非管理员时自动降级为整机流量。")
        note.setObjectName("HelperText")
        note.setWordWrap(True)
        card.body.addWidget(elevate, 0, Qt.AlignmentFlag.AlignLeft)
        card.body.addWidget(note)
        return card

    def _build_usage_card(self) -> Card:
        card = Card("使用行为统计", "基于系统最后输入时间与锁屏状态区分活跃 / 闲置 / 锁屏")
        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)
        self.idle_spin = QSpinBox()
        self.idle_spin.setRange(10, 1800)
        self.idle_spin.setSuffix(" 秒")
        self.idle_spin.setMaximumWidth(160)
        self._form_row(form, 0, "闲置判定阈值", self.idle_spin, "鼠标键盘无操作超过该时长，计时记为挂机闲置")
        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(0, 3650)
        self.retention_spin.setSuffix(" 天")
        self.retention_spin.setMaximumWidth(160)
        self._form_row(form, 1, "日志保留天数", self.retention_spin, "启动时自动清理更早的文件 / 软件 / 流量日志；0 表示永久保留")
        card.body.addLayout(form)
        return card

    def _build_reminder_card(self) -> Card:
        card = Card("温和提醒", "非侵入式提示，可在托盘与界面看到，不会弹窗打断")
        self.reminder_app = ToggleSwitch("软件连续使用过久提醒")
        self.reminder_burst = ToggleSwitch("文档密集变动提醒")
        self.reminder_traffic = ToggleSwitch("异常流量提醒")
        card.body.addWidget(self.reminder_app)
        card.body.addWidget(self.reminder_burst)
        card.body.addWidget(self.reminder_traffic)
        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)
        self.app_minutes_spin = QSpinBox()
        self.app_minutes_spin.setRange(5, 600)
        self.app_minutes_spin.setSuffix(" 分钟")
        self.app_minutes_spin.setMaximumWidth(160)
        self._form_row(form, 0, "连续使用阈值", self.app_minutes_spin, "前台连续使用超过该时长触发休息提醒")
        self.burst_count_spin = QSpinBox()
        self.burst_count_spin.setRange(5, 500)
        self.burst_count_spin.setSuffix(" 次")
        self.burst_count_spin.setMaximumWidth(160)
        self._form_row(form, 1, "密集变动阈值", self.burst_count_spin, "短时间窗口内文件变动次数达到该值触发提醒")
        self.traffic_mb_spin = QSpinBox()
        self.traffic_mb_spin.setRange(5, 2000)
        self.traffic_mb_spin.setSuffix(" MB/分")
        self.traffic_mb_spin.setMaximumWidth(160)
        self._form_row(form, 2, "异常流量阈值", self.traffic_mb_spin, "每分钟流量超过该值触发提醒")
        self.cooldown_spin = QSpinBox()
        self.cooldown_spin.setRange(1, 240)
        self.cooldown_spin.setSuffix(" 分钟")
        self.cooldown_spin.setMaximumWidth(160)
        self._form_row(form, 3, "提醒冷却时间", self.cooldown_spin, "两次提醒之间的最小间隔，避免打扰")
        card.body.addLayout(form)
        return card

    def _build_limit_card(self) -> Card:
        card = Card("软件使用时长提醒", "为每个软件设定每日前台使用上限，达到后托盘提示一次")
        self.limit_card = card
        self.limit_list = QListWidget()
        self.limit_list.setMinimumHeight(96)
        self.limit_list.setMaximumHeight(150)
        card.body.addWidget(self.limit_list)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.limit_combo = QComboBox()
        self.limit_combo.setMinimumWidth(220)
        self.limit_minutes = QSpinBox()
        self.limit_minutes.setRange(1, 1440)
        self.limit_minutes.setValue(60)
        self.limit_minutes.setSuffix(" 分钟")
        add_button = QPushButton("添加提醒")
        add_button.setObjectName("Secondary")
        add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        add_button.clicked.connect(self._add_limit)
        remove_button = QPushButton("移除选中")
        remove_button.setObjectName("Ghost")
        remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_button.clicked.connect(self._remove_limit)
        row.addWidget(self.limit_combo, 1)
        row.addWidget(self.limit_minutes)
        row.addWidget(add_button)
        row.addWidget(remove_button)
        card.body.addLayout(row)
        hint = QLabel("软件列表来自使用记录；上限按当日前台累计时长计算，次日自动重新计数。")
        hint.setObjectName("HelperText")
        hint.setWordWrap(True)
        card.body.addWidget(hint)
        return card

    def _refresh_limit_combo(self) -> None:
        self.limit_combo.clear()
        today = date.today().isoformat()
        for row in self.db.app_ranking(today, today, limit=100):
            self.limit_combo.addItem(row.get("name") or row["app_key"], row["app_key"])

    def _refresh_limit_list(self) -> None:
        self.limit_list.clear()
        for key, minutes in self._limits.items():
            item = QListWidgetItem(f"{self.db.app_name(key)} — 每日 {minutes} 分钟")
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setToolTip(key)
            self.limit_list.addItem(item)

    def _add_limit(self) -> None:
        key = self.limit_combo.currentData()
        if not key:
            QMessageBox.information(self, "添加提醒", "暂无可选软件，先使用一段时间产生记录后再来设置。")
            return
        self._limits[str(key)] = self.limit_minutes.value()
        self._refresh_limit_list()

    def _remove_limit(self) -> None:
        for item in self.limit_list.selectedItems():
            self._limits.pop(item.data(Qt.ItemDataRole.UserRole), None)
        self._refresh_limit_list()

    def _build_startup_card(self) -> Card:
        card = Card("启动与后台", "程序以普通桌面应用运行，不安装系统服务")
        self.autostart_check = ToggleSwitch("开机自动启动（当前用户）")
        self.minimize_check = ToggleSwitch("关闭窗口时最小化到系统托盘，监测继续运行")
        self.start_monitor_check = ToggleSwitch("程序启动时自动开始监测")
        card.body.addWidget(self.autostart_check)
        card.body.addWidget(self.minimize_check)
        card.body.addWidget(self.start_monitor_check)
        hint = QLabel("开机自启使用当前用户的 HKCU Run 注册表项，可随时在此关闭。")
        hint.setObjectName("HelperText")
        card.body.addWidget(hint)
        return card

    def _build_appearance_card(self) -> Card:
        card = Card("外观", "柔和治愈系配色，长时间使用更舒适")
        row = QHBoxLayout()
        row.setSpacing(10)
        label = QLabel("主题模式")
        label.setObjectName("FieldLabel")
        self.theme_control = SegmentedControl([("light", "浅色"), ("dark", "深色")], "light")
        self.theme_control.changed.connect(self.theme_changed.emit)
        row.addWidget(label)
        row.addWidget(self.theme_control)
        row.addStretch(1)
        card.body.addLayout(row)
        self.sidebar_collapsed = ToggleSwitch("折叠左侧导航栏（仅显示图标）")
        card.body.addWidget(self.sidebar_collapsed)
        return card

    def _build_data_card(self) -> Card:
        card = Card("本地数据", "所有记录均保存在本机 SQLite 数据库，不会联网上传")
        path_caption = QLabel("数据库位置")
        path_caption.setObjectName("FieldLabel")
        self.path_label = QLabel(str(DB_PATH))
        self.path_label.setObjectName("DetailBody")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path_label.setWordWrap(True)
        self.db_size_label = QLabel("")
        self.db_size_label.setObjectName("HelperText")
        actions = QHBoxLayout()
        actions.setSpacing(8)
        open_button = QPushButton("打开数据目录")
        open_button.setObjectName("Secondary")
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.clicked.connect(lambda: open_terminal_folder(Path(str(DB_PATH)).parent))
        change_button = QPushButton("更改保存位置…")
        change_button.setObjectName("Secondary")
        change_button.setCursor(Qt.CursorShape.PointingHandCursor)
        change_button.clicked.connect(self._change_data_dir)
        clear_button = QPushButton("清空文件事件")
        clear_button.setObjectName("Danger")
        clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_button.clicked.connect(self._clear_events)
        actions.addWidget(open_button)
        actions.addWidget(change_button)
        actions.addWidget(clear_button)
        actions.addStretch(1)
        card.body.addWidget(path_caption)
        card.body.addWidget(self.path_label)
        card.body.addWidget(self.db_size_label)
        card.body.addLayout(actions)
        return card

    def _form_row(self, form: QGridLayout, row: int, label: str, widget, hint: str) -> None:
        text = QLabel(label)
        text.setObjectName("FieldLabel")
        helper = QLabel(hint)
        helper.setObjectName("HelperText")
        helper.setWordWrap(True)
        form.addWidget(text, row, 0)
        form.addWidget(widget, row, 1)
        form.addWidget(helper, row, 2)

    # -------- load / save --------

    def load_values(self, config: AppConfig) -> None:
        self.config = config
        self._clear_layout(self.drive_layout)
        self.drive_checks.clear()
        devices: list[str] = []
        try:
            for part in psutil.disk_partitions(all=False):
                if "cdrom" in part.opts or not part.fstype:
                    continue
                devices.append(part.device)
        except OSError:
            pass
        for root in config.monitor_roots:
            normalized = os.path.normpath(root)
            if _is_drive_root(normalized) and not any(
                os.path.normcase(d) == os.path.normcase(normalized) for d in devices
            ):
                devices.append(normalized)
        devices = sorted(dict.fromkeys(devices), key=str.lower)
        if not devices:
            empty = QLabel("未检测到本地磁盘分区")
            empty.setObjectName("HelperText")
            self.drive_layout.addWidget(empty)
        for device in devices:
            checkbox = QCheckBox(self._drive_label(device))
            checked = any(
                os.path.normcase(os.path.normpath(root)) == os.path.normcase(os.path.normpath(device))
                for root in config.monitor_roots
            )
            checkbox.setChecked(checked)
            self.drive_layout.addWidget(checkbox)
            self.drive_checks[device] = checkbox

        self.folder_list.clear()
        for root in config.monitor_roots:
            if not _is_drive_root(os.path.normpath(root)):
                self.folder_list.addItem(root)
                item = self.folder_list.item(self.folder_list.count() - 1)
                if item is not None:
                    item.setToolTip(root)

        self.ext_edit.setText(", ".join(config.extensions))
        self.office_edit.setText(", ".join(config.office_extensions))
        self.excl_edit.setText(", ".join(config.extra_excludes))
        self.ignore_junk.setChecked(config.ignore_junk)
        self.min_size_spin.setValue(config.min_size_kb)
        self.idle_spin.setValue(config.idle_threshold_sec)
        self.retention_spin.setValue(config.retention_days)
        self.process_tracking.setChecked(config.process_tracking)
        self.traffic_tracking.setChecked(config.traffic_tracking)
        self.blacklist_edit.setPlainText("\n".join(config.process_blacklist))
        self.whitelist_edit.setPlainText("\n".join(config.process_whitelist))
        self.reminder_app.setChecked(config.reminder_app_enabled)
        self.reminder_burst.setChecked(config.reminder_burst_enabled)
        self.reminder_traffic.setChecked(config.reminder_traffic_enabled)
        self.app_minutes_spin.setValue(config.reminder_app_minutes)
        self.burst_count_spin.setValue(config.reminder_burst_count)
        self.traffic_mb_spin.setValue(config.reminder_traffic_mb_per_min)
        self.cooldown_spin.setValue(config.reminder_cooldown_min)
        self._limits = dict(config.app_time_limits or {})
        self._refresh_limit_combo()
        self._refresh_limit_list()
        self.autostart_check.setChecked(config.autostart and is_autostart_enabled())
        self.minimize_check.setChecked(config.minimize_to_tray)
        self.start_monitor_check.setChecked(config.start_monitoring)
        self.theme_control.set_current(config.theme)
        self.sidebar_collapsed.setChecked(config.sidebar_collapsed)
        self.refresh_data_info()

    def _drive_label(self, device: str) -> str:
        try:
            usage = psutil.disk_usage(device)
            return f"{device}    可用 {human_size(usage.free)} / 共 {human_size(usage.total)}"
        except OSError:
            return f"{device}    当前不可用"

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择需要监测的文件夹")
        if not folder:
            return
        folder = os.path.normpath(folder)
        existing = {
            os.path.normcase(self.folder_list.item(i).text())
            for i in range(self.folder_list.count())
        }
        if os.path.normcase(folder) in existing:
            QMessageBox.information(self, "添加文件夹", "该文件夹已在监测列表中。")
            return
        self.folder_list.addItem(folder)
        item = self.folder_list.item(self.folder_list.count() - 1)
        if item is not None:
            item.setToolTip(folder)

    def _remove_folder(self) -> None:
        for item in self.folder_list.selectedItems():
            self.folder_list.takeItem(self.folder_list.row(item))

    def save(self) -> None:
        roots = [device for device, box in self.drive_checks.items() if box.isChecked()]
        roots.extend(self.folder_list.item(i).text() for i in range(self.folder_list.count()))
        normalized, invalid = [], []
        for root in roots:
            path = os.path.normpath(root)
            if os.path.isdir(path):
                normalized.append(path)
            else:
                invalid.append(path)
        if invalid:
            QMessageBox.warning(
                self, "部分目录不可用",
                "以下目录不存在或当前不可访问，保存时将被忽略：\n" + "\n".join(invalid),
            )
        if not normalized:
            answer = QMessageBox.question(
                self, "未选择监测目录",
                "当前没有可用的监测目录，文件事件将不会被记录。\n仍要保存设置吗？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        new_config = replace(
            self.config,
            monitor_roots=normalized,
            extensions=_split_tokens(self.ext_edit.text()),
            office_extensions=_split_tokens(self.office_edit.text()),
            ignore_junk=self.ignore_junk.isChecked(),
            extra_excludes=_split_tokens(self.excl_edit.text()),
            min_size_kb=self.min_size_spin.value(),
            idle_threshold_sec=self.idle_spin.value(),
            retention_days=self.retention_spin.value(),
            process_tracking=self.process_tracking.isChecked(),
            traffic_tracking=self.traffic_tracking.isChecked(),
            process_blacklist=_split_tokens(self.blacklist_edit.toPlainText()),
            process_whitelist=_split_tokens(self.whitelist_edit.toPlainText()),
            reminder_app_enabled=self.reminder_app.isChecked(),
            reminder_burst_enabled=self.reminder_burst.isChecked(),
            reminder_traffic_enabled=self.reminder_traffic.isChecked(),
            reminder_app_minutes=self.app_minutes_spin.value(),
            reminder_burst_count=self.burst_count_spin.value(),
            reminder_traffic_mb_per_min=self.traffic_mb_spin.value(),
            reminder_cooldown_min=self.cooldown_spin.value(),
            app_time_limits=dict(self._limits),
            autostart=self.autostart_check.isChecked(),
            minimize_to_tray=self.minimize_check.isChecked(),
            start_monitoring=self.start_monitor_check.isChecked(),
            theme=self.theme_control.current_value(),
            sidebar_collapsed=self.sidebar_collapsed.isChecked(),
        )
        new_config.normalize()
        try:
            new_config.save()
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", f"无法写入配置文件：\n{exc}")
            return
        if new_config.autostart != is_autostart_enabled():
            if not set_autostart(new_config.autostart):
                QMessageBox.warning(self, "开机自启设置失败", "无法写入当前用户的启动注册表项，请检查系统权限。")
        self.config = new_config
        self.save_status.setText("已保存并应用")
        self._status_timer.start(4000)
        self.refresh_data_info()
        self.config_saved.emit(new_config)

    def _change_data_dir(self) -> None:
        from app.config import write_data_location
        folder = QFileDialog.getExistingDirectory(self, "选择新的数据保存目录")
        if not folder:
            return
        try:
            write_data_location(folder)
        except OSError as exc:
            QMessageBox.warning(self, "设置失败", f"无法写入数据位置：\n{exc}")
            return
        QMessageBox.information(
            self, "已更改保存位置",
            f"新的数据目录：\n{folder}\n\n请重启程序后生效，原有数据可手动迁移。",
        )

    def _clear_events(self) -> None:
        count = self.db.count_events()
        if count == 0:
            QMessageBox.information(self, "清空文件事件", "当前没有文件事件记录。")
            return
        answer = QMessageBox.question(
            self, "确认清空",
            f"将永久删除全部 {count} 条文件事件记录（使用时长统计不受影响）。\n确定继续吗？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.db.clear_file_events()
        self.refresh_data_info()
        self.events_cleared.emit()
        QMessageBox.information(self, "已清空", "文件事件记录已全部清空。")

    def refresh_data_info(self) -> None:
        count = self.db.count_events()
        self.db_size_label.setText(f"数据库大小 {human_size(self.db.file_size())} · 文件事件 {count} 条")
        self.path_label.setText(str(DB_PATH))

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()