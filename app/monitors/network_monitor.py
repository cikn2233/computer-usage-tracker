from __future__ import annotations

import ctypes
import logging
import socket
import sqlite3
import time
from datetime import datetime

import psutil
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from app.config import AppConfig
from app.database import HOST_KEY, Database
from app.utils import app_key_for_exe, exe_display_name, is_admin, now_iso

log = logging.getLogger(__name__)


class _TcpRow(ctypes.Structure):
    _fields_ = [
        ("dwState", ctypes.c_ulong),
        ("dwLocalAddr", ctypes.c_ulong),
        ("dwLocalPort", ctypes.c_ulong),
        ("dwRemoteAddr", ctypes.c_ulong),
        ("dwRemotePort", ctypes.c_ulong),
    ]


class _DataRw(ctypes.Structure):
    _fields_ = [("EnableCollection", ctypes.c_ubyte)]


class _DataRod(ctypes.Structure):
    # 完整 TCP_ESTATS_DATA_ROD_v0（96 字节）；缓冲区小于真实结构会报 ERROR_INVALID_USER_BUFFER
    _fields_ = [
        ("DataBytesOut", ctypes.c_ulonglong),
        ("DataSegsOut", ctypes.c_ulonglong),
        ("DataBytesIn", ctypes.c_ulonglong),
        ("DataSegsIn", ctypes.c_ulonglong),
        ("SegsOut", ctypes.c_ulonglong),
        ("SegsIn", ctypes.c_ulonglong),
        ("SoftErrors", ctypes.c_ulong),
        ("SoftErrorReason", ctypes.c_ulong),
        ("SndUna", ctypes.c_ulong),
        ("SndNxt", ctypes.c_ulong),
        ("SndMax", ctypes.c_ulong),
        ("ThruBytesAcked", ctypes.c_ulonglong),
        ("RcvNxt", ctypes.c_ulong),
        ("ThruBytesReceived", ctypes.c_ulonglong),
    ]


class NetworkMonitor(QObject):
    """网络流量监测。

    - 整机流量：始终可用（psutil 网卡计数差值），写入主机聚合与实时采样；
    - 按软件流量：需要管理员权限，通过 TCP ESTATS 读取每条连接的收发字节并归属到进程。
      非管理员时自动降级为仅整机统计，界面会如实说明。
    """

    traffic_updated = pyqtSignal()
    reminder = pyqtSignal(str, str)

    def __init__(self, db: Database, config: AppConfig, parent=None):
        super().__init__(parent)
        self._db = db
        self._config = config
        self._running = False
        self._last_counters = None
        self._last_mono = 0.0
        self._last_reminder_mono = 0.0
        self._recent_bytes: list[tuple[float, int]] = []
        self.per_app_available = False
        self._iphlpapi = None
        self._conn_cache: dict[tuple, dict] = {}
        self._pid_exe: dict[int, str] = {}
        self._name_cache: dict[str, str] = {}
        self._live: dict[str, tuple[float, float]] = {}
        self._last_app_mono = 0.0

        self._host_timer = QTimer(self)
        self._host_timer.setInterval(2000)
        self._host_timer.timeout.connect(self._on_host)
        self._app_timer = QTimer(self)
        self._app_timer.setInterval(5000)
        self._app_timer.timeout.connect(self._on_apps)

    def update_config(self, config: AppConfig) -> None:
        self._config = config

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running or not self._config.traffic_tracking:
            return
        try:
            self._last_counters = psutil.net_io_counters()
        except (OSError, RuntimeError):
            self._last_counters = None
        self._last_mono = time.monotonic()
        self._running = True
        self._host_timer.start()
        if is_admin():
            try:
                self._iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
                self._iphlpapi.SetPerTcpConnectionEStats.argtypes = [
                    ctypes.POINTER(_TcpRow), ctypes.c_int, ctypes.c_void_p,
                    ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
                ]
                self._iphlpapi.SetPerTcpConnectionEStats.restype = ctypes.c_ulong
                self._iphlpapi.GetPerTcpConnectionEStats.argtypes = [
                    ctypes.POINTER(_TcpRow), ctypes.c_int,
                    ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                    ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                    ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                ]
                self._iphlpapi.GetPerTcpConnectionEStats.restype = ctypes.c_ulong
                self.per_app_available = True
                self._last_app_mono = time.monotonic()
                self._app_timer.start()
            except OSError:
                self.per_app_available = False
        log.info("network monitor started (per_app=%s)", self.per_app_available)

    def stop(self) -> None:
        if not self._running:
            return
        self._host_timer.stop()
        self._app_timer.stop()
        self._running = False
        self._conn_cache.clear()
        self._live.clear()
        log.info("network monitor stopped")

    # -------- host totals --------

    def _on_host(self) -> None:
        if not self._running:
            return
        try:
            counters = psutil.net_io_counters()
        except (OSError, RuntimeError):
            return
        mono = time.monotonic()
        elapsed = max(0.001, mono - self._last_mono)
        self._last_mono = mono
        if self._last_counters is None:
            self._last_counters = counters
            return
        recv = max(0, counters.bytes_recv - self._last_counters.bytes_recv)
        sent = max(0, counters.bytes_sent - self._last_counters.bytes_sent)
        self._last_counters = counters
        day = datetime.now().strftime("%Y-%m-%d")
        try:
            self._db.add_network_daily(day, HOST_KEY, recv, sent)
            self._db.add_network_sample(now_iso(), recv, sent)
        except sqlite3.Error:
            log.exception("cannot record host traffic")
        self._check_spike(recv + sent, elapsed, mono)
        self.traffic_updated.emit()

    def _check_spike(self, total_bytes: int, elapsed: float, mono: float) -> None:
        if not self._config.reminder_traffic_enabled:
            return
        self._recent_bytes.append((mono, total_bytes))
        self._recent_bytes = [(t, b) for t, b in self._recent_bytes if mono - t <= 60]
        per_min = sum(b for _, b in self._recent_bytes)
        limit = max(1, self._config.reminder_traffic_mb_per_min) * 1024 * 1024
        cooldown = max(1, self._config.reminder_cooldown_min) * 60
        if per_min >= limit and mono - self._last_reminder_mono >= cooldown:
            self._last_reminder_mono = mono
            self.reminder.emit(
                "流量异常提醒",
                f"近一分钟网络流量约 {per_min / 1024 / 1024:.0f} MB，明显高于平时，可留意是否有异常下载。",
            )

    # -------- per-app (admin) --------

    def _exe_for_pid(self, pid: int) -> str:
        exe = self._pid_exe.get(pid)
        if exe is None:
            try:
                exe = psutil.Process(pid).exe() or ""
            except (psutil.Error, OSError):
                exe = ""
            self._pid_exe[pid] = exe
            if len(self._pid_exe) > 512:
                self._pid_exe.clear()
        return exe

    def _on_apps(self) -> None:
        if not self._running or self._iphlpapi is None:
            return
        try:
            connections = psutil.net_connections(kind="tcp")
        except (psutil.AccessDenied, OSError):
            return
        active: set[tuple] = set()
        day = datetime.now().strftime("%Y-%m-%d")
        mono = time.monotonic()
        elapsed = max(0.001, mono - self._last_app_mono)
        self._last_app_mono = mono
        tick: dict[str, list[int]] = {}
        for conn in connections:
            if conn.status != psutil.CONN_ESTABLISHED or not conn.pid:
                continue
            if not conn.laddr or not conn.raddr:
                continue
            key = (conn.laddr.ip, conn.laddr.port, conn.raddr.ip, conn.raddr.port)
            active.add(key)
            entry = self._conn_cache.get(key)
            if entry is None:
                entry = self._enable_estats(conn)
                if entry is None:
                    continue
                self._conn_cache[key] = entry
            rod = self._read_rod(entry["row"])
            if rod is None:
                continue
            prev_out, prev_in = entry["bytes_out"], entry["bytes_in"]
            d_out = max(0, rod.DataBytesOut - prev_out)
            d_in = max(0, rod.DataBytesIn - prev_in)
            entry["bytes_out"] = rod.DataBytesOut
            entry["bytes_in"] = rod.DataBytesIn
            if d_out == 0 and d_in == 0:
                continue
            exe = self._exe_for_pid(conn.pid)
            if not exe:
                continue
            app_key = app_key_for_exe(exe)
            acc = tick.setdefault(app_key, [0, 0])
            acc[0] += d_in
            acc[1] += d_out
            name = self._name_cache.get(app_key)
            if name is None:
                name = exe_display_name(exe)
                self._name_cache[app_key] = name
                try:
                    self._db.upsert_app(app_key, name, exe, now_iso())
                except sqlite3.Error:
                    pass
            try:
                self._db.add_network_daily(day, app_key, d_in, d_out)
            except sqlite3.Error:
                log.exception("cannot record app traffic")
        for key in list(self._conn_cache):
            if key not in active:
                del self._conn_cache[key]
        self._live = {k: (v[0] / elapsed, v[1] / elapsed) for k, v in tick.items()}

    def _enable_estats(self, conn) -> dict | None:
        try:
            local_addr = int.from_bytes(socket.inet_aton(conn.laddr.ip), "little")
            remote_addr = int.from_bytes(socket.inet_aton(conn.raddr.ip), "little")
        except OSError:
            return None  # 该 API 仅支持 IPv4，IPv6 连接跳过
        row = _TcpRow()
        row.dwState = 5  # MIB_TCP_STATE_ESTAB
        row.dwLocalAddr = local_addr
        row.dwLocalPort = socket.htons(conn.laddr.port)
        row.dwRemoteAddr = remote_addr
        row.dwRemotePort = socket.htons(conn.raddr.port)
        # Rw 必须指向 TCP_ESTATS_DATA_RW_v0 结构；直接传布尔值会报 ERROR_NOT_SUPPORTED
        rw = _DataRw()
        rw.EnableCollection = 1
        try:
            ret = self._iphlpapi.SetPerTcpConnectionEStats(
                ctypes.byref(row), 1, ctypes.byref(rw), 0, ctypes.sizeof(rw), 0
            )
            if ret != 0:
                return None
        except OSError:
            return None
        rod = self._read_rod(row)
        if rod is None:
            return None
        return {"row": row, "bytes_out": rod.DataBytesOut, "bytes_in": rod.DataBytesIn}

    def _read_rod(self, row: _TcpRow) -> _DataRod | None:
        rw = _DataRw()
        rod = _DataRod()
        try:
            ret = self._iphlpapi.GetPerTcpConnectionEStats(
                ctypes.byref(row), 1,
                ctypes.byref(rw), 0, ctypes.sizeof(rw),
                None, 0, 0,
                ctypes.byref(rod), 0, ctypes.sizeof(rod),
            )
            if ret != 0 or not rw.EnableCollection:
                return None
        except OSError:
            return None
        return rod

    # -------- queries --------

    def live_rates(self) -> dict[str, tuple[float, float]]:
        """最近一个采集周期内各软件的下载/上传速率（字节/秒）。"""
        return dict(self._live)

    def current_rate(self) -> tuple[float, float]:
        samples = self._db.network_samples(limit=2)
        if len(samples) < 2:
            return 0.0, 0.0
        last = samples[-1]
        return float(last["bytes_in"]) / 2.0, float(last["bytes_out"]) / 2.0