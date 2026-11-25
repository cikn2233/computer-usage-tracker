from __future__ import annotations

import calendar
import ctypes
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import LOG_DIR

ISO_FMT = "%Y-%m-%d %H:%M:%S"
DATE_FMT = "%Y-%m-%d"
CN_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
AUTOSTART_VALUE_NAME = "ComputerUsageTracker"
AUTOSTART_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def now() -> datetime:
    return datetime.now()


def now_iso() -> str:
    return datetime.now().strftime(ISO_FMT)


def to_iso(dt: datetime) -> str:
    return dt.strftime(ISO_FMT)


def parse_iso(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, ISO_FMT)
    except (TypeError, ValueError):
        return None


def day_bounds(d: date) -> tuple[str, str]:
    start = datetime.combine(d, datetime.min.time())
    end = start + timedelta(days=1)
    return to_iso(start), to_iso(end)


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def month_bounds(d: date) -> tuple[date, date]:
    first = d.replace(day=1)
    last = d.replace(day=calendar.monthrange(d.year, d.month)[1])
    return first, last


def human_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "—"
    total = max(0, int(round(seconds)))
    if total < 60:
        return f"{total}秒"
    if total < 3600:
        minutes, sec = divmod(total, 60)
        return f"{minutes}分" if sec < 30 else f"{minutes}分{sec}秒"
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f"{days}天{hours}小时" if hours else f"{days}天"
    return f"{hours}小时{minutes}分" if minutes else f"{hours}小时"


def human_size(size: float | int | None) -> str:
    if size is None:
        return "—"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{value:.0f} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def event_type_label(value: str) -> str:
    return {
        "created": "新建", "modified": "修改", "deleted": "删除", "renamed": "重命名",
    }.get(value, value)


def weekday_cn(d: date) -> str:
    return CN_WEEKDAYS[d.weekday()]


def greeting() -> str:
    hour = datetime.now().hour
    if hour < 6:
        return "凌晨好"
    if hour < 9:
        return "早上好"
    if hour < 12:
        return "上午好"
    if hour < 14:
        return "中午好"
    if hour < 18:
        return "下午好"
    return "晚上好"


def open_folder(path: str | Path) -> bool:
    target = Path(path)
    if not target.exists():
        target = target.parent
    try:
        if target.is_dir():
            os.startfile(str(target))  # noqa: S606 - local shell open
        elif target.is_file():
            subprocess.Popen(["explorer", "/select,", os.path.normpath(str(target))])
        else:
            return False
        return True
    except OSError:
        return False


def reveal_in_explorer(path: str) -> bool:
    target = Path(path)
    try:
        if target.exists():
            subprocess.Popen(["explorer", "/select,", os.path.normpath(str(target))])
            return True
        if target.parent.exists():
            os.startfile(str(target.parent))  # noqa: S606
            return True
    except OSError:
        pass
    return False


def open_terminal_folder(path: str | Path) -> bool:
    try:
        os.startfile(str(path))  # noqa: S606
        return True
    except OSError:
        return False


def setup_logging() -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_DIR / "app.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(handler)
    except OSError:
        logging.basicConfig(level=logging.INFO)


def _autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else exe
    script = Path(__file__).resolve().parents[1] / "main.py"
    return f'"{runner}" "{script}"'


def set_autostart(enabled: bool) -> bool:
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, AUTOSTART_RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enabled:
                winreg.SetValueEx(key, AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, _autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def is_autostart_enabled() -> bool:
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, AUTOSTART_RUN_KEY, 0, winreg.KEY_READ
        ) as key:
            winreg.QueryValueEx(key, AUTOSTART_VALUE_NAME)
            return True
    except (OSError, FileNotFoundError):
        return False


# ---------------- Windows 进程 / 权限辅助 ----------------

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def relaunch_elevated() -> bool:
    """以管理员身份重新启动本程序（用于按软件流量统计）。"""
    try:
        if getattr(sys, "frozen", False):
            params = ""
            executable = sys.executable
        else:
            script = Path(__file__).resolve().parents[1] / "main.py"
            params = f'"{script}"'
            executable = sys.executable
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, params, None, 1)
        return int(ret) > 32
    except (AttributeError, OSError):
        return False


def app_key_for_exe(exe: str) -> str:
    return (exe or "").strip().lower()


def exe_display_name(exe: str) -> str:
    """优先读取可执行文件的 FileDescription / ProductName（软件产品名），失败则用文件名。"""
    fallback = Path(exe).stem if exe else "未知软件"
    if not exe or not os.path.isfile(exe):
        return fallback
    try:
        version = ctypes.WinDLL("version", use_last_error=True)
        size = version.GetFileVersionInfoSizeW(exe, None)
        if not size:
            return fallback
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(exe, 0, size, buffer):
            return fallback
        blocks: list[str] = []
        ptr = ctypes.c_void_p()
        length = ctypes.c_uint()
        if version.VerQueryValueW(
            buffer, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(length)
        ) and length.value:
            pairs = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint16))
            for i in range(length.value // 4):
                blocks.append(f"\\StringFileInfo\\{pairs[2 * i]:04x}{pairs[2 * i + 1]:04x}")
        blocks += [
            "\\StringFileInfo\\080404b0",
            "\\StringFileInfo\\040904b0",
            "\\StringFileInfo\\040904e4",
        ]
        # FileDescription 是具体软件名（Notepad / Google Chrome），
        # ProductName 常为套件或系统族名（Microsoft® Windows® Operating System）
        for field in ("FileDescription", "ProductName"):
            for block in blocks:
                if version.VerQueryValueW(
                    buffer, f"{block}\\{field}", ctypes.byref(ptr), ctypes.byref(length)
                ) and length.value:
                    text = ctypes.wstring_at(ptr.value, length.value - 1).strip()
                    # 版本块可能带 NUL  padding 与控制字符，Excel/HTML 都不接受
                    text = "".join(ch for ch in text if ch.isprintable())
                    if text:
                        return text
    except (OSError, AttributeError, ValueError):
        pass
    return fallback


def human_rate(bytes_per_sec: float) -> str:
    return human_size(bytes_per_sec) + "/s"