from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import sqlite3
import time
from datetime import date, datetime

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from app.database import Database
from app.utils import now_iso

log = logging.getLogger(__name__)


class _LastInputInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


class SessionTracker(QObject):
    """整机使用时长采集：区分活跃 / 闲置挂机 / 锁屏三种状态。

    - 活跃：鼠标键盘在阈值内有操作；
    - 闲置：超过阈值无操作（挂机）；
    - 锁屏：当前输入桌面不可访问（Win+L 或自动锁屏）。
    """

    tick = pyqtSignal(int, int, int, float)

    def __init__(self, db: Database, idle_threshold_sec: int = 120, parent=None):
        super().__init__(parent)
        self._db = db
        self._threshold = max(10, int(idle_threshold_sec))
        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._on_tick)
        self._running = False
        self._session_id: int | None = None
        self._last_mono = 0.0
        self._acc_active = 0
        self._acc_idle = 0
        self._acc_lock = 0
        self._ticks_since_touch = 0
        self.session_start: str | None = None
        self.idle_seconds = 0.0
        self.locked = False
        self._user32 = None
        self._kernel32 = None
        try:
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except OSError:
            log.warning("GetLastInputInfo unavailable; idle detection disabled")

    def set_idle_threshold(self, seconds: int) -> None:
        self._threshold = max(10, int(seconds))

    @property
    def running(self) -> bool:
        return self._running

    def get_idle_seconds(self) -> float:
        if self._user32 is None or self._kernel32 is None:
            return 0.0
        info = _LastInputInfo()
        info.cbSize = ctypes.sizeof(_LastInputInfo)
        if not self._user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        tick_count = self._kernel32.GetTickCount() & 0xFFFFFFFF
        idle_ms = (tick_count - info.dwTime) & 0xFFFFFFFF
        return idle_ms / 1000.0

    def is_locked(self) -> bool:
        """OpenInputDesktop 失败通常意味着处于锁屏 / 安全桌面。"""
        if self._user32 is None:
            return False
        try:
            handle = self._user32.OpenInputDesktop(0, False, 0x0100)
            if handle:
                self._user32.CloseDesktop(handle)
                return False
            return True
        except OSError:
            return False

    def start(self) -> None:
        if self._running:
            return
        try:
            self._db.close_dangling_sessions()
            stamp = now_iso()
            self._session_id = self._db.open_session(stamp, stamp)
        except sqlite3.Error:
            log.exception("cannot open session")
            return
        self.session_start = stamp
        self._acc_active = 0
        self._acc_idle = 0
        self._acc_lock = 0
        self._ticks_since_touch = 0
        self._last_mono = time.monotonic()
        self._running = True
        self._timer.start()
        log.info("session tracker started (%s)", stamp)

    def stop(self) -> None:
        if not self._running:
            return
        self._timer.stop()
        self._running = False
        self._flush_session()
        if self._session_id is not None:
            try:
                self._db.close_session(self._session_id, now_iso())
            except sqlite3.Error:
                log.exception("cannot close session")
        self._session_id = None
        log.info("session tracker stopped")

    def _flush_session(self) -> None:
        if self._session_id is None:
            return
        try:
            self._db.touch_session(
                self._session_id, now_iso(),
                self._acc_active, self._acc_idle, self._acc_lock,
            )
        except sqlite3.Error:
            log.exception("cannot update session")
        self._acc_active = 0
        self._acc_idle = 0
        self._acc_lock = 0
        self._ticks_since_touch = 0

    def _on_tick(self) -> None:
        if not self._running:
            return
        mono = time.monotonic()
        delta = mono - self._last_mono
        self._last_mono = mono
        if delta <= 0:
            return
        if delta > 30:
            # 长时间无 tick（睡眠 / 卡顿），不计入使用时长
            self._flush_session()
            return
        delta = min(delta, 15.0)
        idle = self.get_idle_seconds()
        self.idle_seconds = idle
        self.locked = self.is_locked()
        seconds = int(round(delta))
        if self.locked:
            active_delta, idle_delta, lock_delta = 0, 0, seconds
        elif idle <= self._threshold:
            active_delta, idle_delta, lock_delta = seconds, 0, 0
        else:
            active_delta, idle_delta, lock_delta = 0, seconds, 0
        if active_delta == 0 and idle_delta == 0 and lock_delta == 0:
            return
        current = datetime.now()
        try:
            self._db.add_usage(
                current.strftime("%Y-%m-%d"), current.hour,
                active_delta, idle_delta, lock_delta,
            )
        except sqlite3.Error:
            log.exception("cannot record usage")
        self._acc_active += active_delta
        self._acc_idle += idle_delta
        self._acc_lock += lock_delta
        self._ticks_since_touch += 1
        if self._ticks_since_touch >= 3:
            self._flush_session()
        self.tick.emit(active_delta, idle_delta, lock_delta, idle)

    def today_usage(self) -> tuple[int, int, int]:
        day = date.today().isoformat()
        return self._db.usage_totals(day, day)