from __future__ import annotations

import logging
import time
from datetime import date

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from app.config import AppConfig
from app.database import Database
from app.utils import human_duration

log = logging.getLogger(__name__)


class DocBurstReminder(QObject):
    """文档密集编辑提醒：短时间内大量办公文档变动时温和提示。"""

    reminder = pyqtSignal(str, str)

    def __init__(self, db: Database, config: AppConfig, parent=None):
        super().__init__(parent)
        self._db = db
        self._config = config
        self._last_mono = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(15000)
        self._timer.timeout.connect(self._check)

    def update_config(self, config: AppConfig) -> None:
        self._config = config

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _check(self) -> None:
        if not self._config.reminder_burst_enabled:
            return
        window = max(10, self._config.reminder_burst_window_sec)
        try:
            count = self._db.count_events_since(window)
        except Exception:
            return
        cooldown = max(1, self._config.reminder_cooldown_min) * 60
        mono = time.monotonic()
        if count >= self._config.reminder_burst_count and mono - self._last_mono >= cooldown:
            self._last_mono = mono
            self.reminder.emit(
                "文档变动提醒",
                f"最近 {window} 秒内有 {count} 次文件变动，注意及时保存重要文档。",
            )


class AppLimitReminder(QObject):
    """按软件自定义每日前台使用上限，达到后当天提示一次。"""

    reminder = pyqtSignal(str, str)

    def __init__(self, db: Database, config: AppConfig, parent=None):
        super().__init__(parent)
        self._db = db
        self._config = config
        self._notified: dict[str, str] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(30000)
        self._timer.timeout.connect(self._check)

    def update_config(self, config: AppConfig) -> None:
        self._config = config

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _check(self) -> None:
        limits = self._config.app_time_limits or {}
        if not limits:
            return
        today = date.today().isoformat()
        try:
            ranking = self._db.app_ranking(today, today, limit=500)
        except Exception:
            return
        fg = {row["app_key"]: int(row["fg"]) for row in ranking}
        for key, minutes in limits.items():
            seconds = fg.get(key, 0)
            if seconds < minutes * 60 or self._notified.get(key) == today:
                continue
            self._notified[key] = today
            self.reminder.emit(
                "使用时长提醒",
                f"「{self._db.app_name(key)}」今日已使用 {human_duration(seconds)}，"
                f"达到你设定的 {minutes} 分钟上限。",
            )