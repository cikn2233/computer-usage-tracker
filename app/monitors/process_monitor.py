from __future__ import annotations

import ctypes
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime

import psutil
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from app.config import AppConfig
from app.database import Database
from app.utils import app_key_for_exe, exe_display_name, now_iso

log = logging.getLogger(__name__)


@dataclass
class _AppTrack:
    app_key: str
    name: str
    exe: str
    session_id: int
    fg_acc: int = 0
    bg_acc: int = 0
    running: bool = True
    extra: dict = field(default_factory=dict)


class ProcessMonitor(QObject):
    """进程 / 软件使用监测。

    只有处于前台窗口的软件才计入「有效使用（前台）」，其余在运行的软件计入后台时长。
    内置系统进程黑名单 + 用户黑白名单过滤；前台软件连续使用超阈值会触发温和提醒。
    """

    apps_updated = pyqtSignal()
    reminder = pyqtSignal(str, str)

    def __init__(self, db: Database, config: AppConfig, parent=None):
        super().__init__(parent)
        self._db = db
        self._config = config
        self._tracks: dict[str, _AppTrack] = {}
        self._pid_exe: dict[int, str] = {}
        self._name_cache: dict[str, str] = {}
        self._fg_key: str | None = None
        self._fg_streak_key: str | None = None
        self._fg_streak_sec = 0
        self._last_reminder_mono = 0.0
        self._last_fg_mono = 0.0
        self._running = False
        self._user32 = None
        try:
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        except OSError:
            log.warning("foreground window API unavailable")

        self._fg_timer = QTimer(self)
        self._fg_timer.setInterval(2000)
        self._fg_timer.timeout.connect(self._on_foreground)
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(5000)
        self._scan_timer.timeout.connect(self._on_scan)

    # -------- config --------

    def update_config(self, config: AppConfig) -> None:
        self._config = config

    @property
    def running(self) -> bool:
        return self._running

    def _allowed(self, proc_name: str) -> bool:
        name = (proc_name or "").lower()
        if not name:
            return False
        whitelist = {n.lower() for n in self._config.process_whitelist}
        if whitelist:
            return name in whitelist
        blacklist = {n.lower() for n in self._config.process_blacklist}
        return name not in blacklist

    # -------- lifecycle --------

    def start(self) -> None:
        if self._running or not self._config.process_tracking:
            return
        try:
            self._db.close_dangling_app_sessions()
        except sqlite3.Error:
            log.exception("cannot close dangling app sessions")
        self._last_fg_mono = time.monotonic()
        self._running = True
        self._scan_timer.start()
        self._fg_timer.start()
        self._on_scan()
        log.info("process monitor started")

    def stop(self) -> None:
        if not self._running:
            return
        self._fg_timer.stop()
        self._scan_timer.stop()
        self._running = False
        self._flush_all()
        for track in self._tracks.values():
            try:
                self._db.close_app_session(track.session_id, now_iso())
            except sqlite3.Error:
                log.exception("cannot close app session")
        self._tracks.clear()
        self._fg_key = None
        log.info("process monitor stopped")

    # -------- foreground --------

    def _foreground_exe(self) -> tuple[str, str]:
        """返回当前前台窗口的 (exe 路径, 进程名)。"""
        if self._user32 is None:
            return "", ""
        try:
            hwnd = self._user32.GetForegroundWindow()
            if not hwnd:
                return "", ""
            pid = ctypes.c_ulong()
            self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return "", ""
            exe = self._pid_exe.get(pid.value)
            if exe is None:
                try:
                    exe = psutil.Process(pid.value).exe() or ""
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    exe = ""
                self._pid_exe[pid.value] = exe
                if len(self._pid_exe) > 512:
                    self._pid_exe.clear()
            name = psutil.Process(pid.value).name() if exe else ""
            return exe, name
        except (psutil.Error, OSError):
            return "", ""

    def current_foreground(self) -> dict | None:
        if not self._fg_key:
            return None
        track = self._tracks.get(self._fg_key)
        if track is None:
            return None
        return {"app_key": track.app_key, "name": track.name, "exe": track.exe}

    def _ensure_track(self, app_key: str, exe: str, proc_name: str) -> _AppTrack | None:
        track = self._tracks.get(app_key)
        if track is not None:
            track.running = True
            return track
        if not self._allowed(proc_name):
            return None
        name = self._name_cache.get(app_key)
        if name is None:
            name = exe_display_name(exe) or proc_name
            self._name_cache[app_key] = name
        stamp = now_iso()
        try:
            self._db.upsert_app(app_key, name, exe, stamp)
            session_id = self._db.open_app_session(app_key, stamp)
        except sqlite3.Error:
            log.exception("cannot register app %s", app_key)
            return None
        track = _AppTrack(app_key, name, exe, session_id)
        self._tracks[app_key] = track
        return track

    def _on_foreground(self) -> None:
        if not self._running:
            return
        mono = time.monotonic()
        delta = mono - self._last_fg_mono
        self._last_fg_mono = mono
        if delta <= 0:
            return
        delta = min(delta, 10.0)
        seconds = int(round(delta))
        exe, proc_name = self._foreground_exe()
        fg_key = app_key_for_exe(exe) if exe else None
        if fg_key and not self._allowed(proc_name):
            fg_key = None
        if fg_key:
            self._ensure_track(fg_key, exe, proc_name)
        self._fg_key = fg_key

        # 前台时长只给当前前台软件；后台时长给其余在运行的软件
        for key, track in self._tracks.items():
            if not track.running:
                continue
            if key == fg_key:
                track.fg_acc += seconds
            else:
                track.bg_acc += seconds

        self._update_streak(fg_key, seconds)

    def _update_streak(self, fg_key: str | None, seconds: int) -> None:
        if not self._config.reminder_app_enabled:
            return
        if fg_key != self._fg_streak_key:
            self._fg_streak_key = fg_key
            self._fg_streak_sec = 0
        if fg_key is None:
            return
        self._fg_streak_sec += seconds
        limit = max(1, self._config.reminder_app_minutes) * 60
        cooldown = max(1, self._config.reminder_cooldown_min) * 60
        mono = time.monotonic()
        if self._fg_streak_sec >= limit and mono - self._last_reminder_mono >= cooldown:
            track = self._tracks.get(fg_key)
            name = track.name if track else fg_key
            self._last_reminder_mono = mono
            self._fg_streak_sec = 0
            self.reminder.emit(
                "用眼休息提醒",
                f"「{name}」已连续使用超过 {self._config.reminder_app_minutes} 分钟，起来活动一下吧。",
            )

    # -------- process scan --------

    def _on_scan(self) -> None:
        if not self._running:
            return
        seen: set[str] = set()
        try:
            for proc in psutil.process_iter(["pid", "name", "exe"]):
                info = proc.info
                proc_name = info.get("name") or ""
                exe = info.get("exe") or ""
                if not exe or not self._allowed(proc_name):
                    continue
                app_key = app_key_for_exe(exe)
                if app_key in seen:
                    continue
                seen.add(app_key)
                self._pid_exe[info["pid"]] = exe
                self._ensure_track(app_key, exe, proc_name)
        except (psutil.Error, OSError):
            log.exception("process scan failed")

        # 关闭已退出的软件会话
        for key in list(self._tracks):
            if key not in seen and key != self._fg_key:
                track = self._tracks.pop(key)
                self._flush_track(track)
                try:
                    self._db.close_app_session(track.session_id, now_iso())
                except sqlite3.Error:
                    log.exception("cannot close app session")
        self._flush_all()
        self.apps_updated.emit()

    # -------- persistence --------

    def _flush_track(self, track: _AppTrack) -> None:
        if track.fg_acc <= 0 and track.bg_acc <= 0:
            return
        day = datetime.now().strftime("%Y-%m-%d")
        stamp = now_iso()
        try:
            self._db.add_app_daily(day, track.app_key, track.fg_acc, track.bg_acc)
            self._db.touch_app_session(track.session_id, stamp, track.fg_acc, track.bg_acc)
        except sqlite3.Error:
            log.exception("cannot flush app %s", track.app_key)
        track.fg_acc = 0
        track.bg_acc = 0

    def _flush_all(self) -> None:
        for track in self._tracks.values():
            self._flush_track(track)

    # -------- queries for UI --------

    def running_apps(self) -> list[dict]:
        return [
            {"app_key": t.app_key, "name": t.name, "exe": t.exe,
             "foreground": t.app_key == self._fg_key}
            for t in self._tracks.values() if t.running
        ]