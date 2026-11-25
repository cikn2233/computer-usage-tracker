from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_NAME = "电脑使用行为溯源监测系统"
APP_SHORT_NAME = "溯源监测"
APP_SLUG = "ComputerUsageTracker"
VERSION = "2.0.0"

_DATA_DIR_ENV = "CUT_DATA_DIR"


def _default_base() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_SLUG


def _resolve_data_dir() -> Path:
    override = os.environ.get(_DATA_DIR_ENV)
    if override:
        return Path(override).expanduser()
    base = _default_base()
    pointer = base / "location.json"
    try:
        if pointer.exists():
            target = json.loads(pointer.read_text(encoding="utf-8")).get("data_dir")
            if target:
                path = Path(str(target)).expanduser()
                if path.is_absolute():
                    return path
    except (OSError, ValueError):
        pass
    return base


DATA_DIR = _resolve_data_dir()
DB_PATH = DATA_DIR / "tracker.db"
SETTINGS_PATH = DATA_DIR / "settings.json"
LOG_DIR = DATA_DIR / "logs"
WEB_DIR = DATA_DIR / "web"
LOCATION_POINTER = _default_base() / "location.json"

DEFAULT_EXTENSIONS = [
    "docx", "doc", "pdf", "xlsx", "xls", "pptx", "ppt",
    "txt", "md", "csv", "py", "js", "ts", "json", "sql",
    "java", "c", "cpp", "h", "cs", "dwg", "dxf", "psd", "ai",
    "zip", "rar", "7z",
]

DEFAULT_OFFICE_EXTENSIONS = ["docx", "doc", "xlsx", "xls", "pdf", "pptx", "ppt"]

DEFAULT_JUNK_SEGMENTS = [
    "\\windows\\winsxs\\",
    "\\windows\\servicing\\",
    "\\windows\\system32\\",
    "\\windows\\syswow64\\",
    "\\windows\\assembly\\",
    "\\windows\\temp\\",
    "\\windows\\logs\\",
    "\\windows\\softwaredistribution\\",
    "\\windows\\panther\\",
    "\\$recycle.bin\\",
    "\\system volume information\\",
    "\\appdata\\local\\temp\\",
    "\\appdata\\local\\microsoft\\windows\\inetcache\\",
    "\\appdata\\local\\microsoft\\windows\\webcache\\",
    "\\appdata\\local\\microsoft\\windows\\explorer\\",
    "\\appdata\\local\\packages\\",
    "\\appdata\\locallow\\microsoft\\",
    "\\programdata\\microsoft\\windows\\wer\\",
    "\\node_modules\\",
    "\\.git\\",
    "\\.svn\\",
    "\\__pycache__\\",
    "\\.venv\\",
    "\\venv\\",
    "\\site-packages\\",
    "\\temp\\",
    "\\tmp\\",
]

BLOCKED_EXTENSIONS = {
    "tmp", "temp", "log", "etl", "dmp", "crdownload", "part", "partial",
    "pyc", "pyo", "swp", "cache", "lock", "lnk", "url", "evtx",
}

BLOCKED_FILENAMES = {
    "pagefile.sys", "hiberfil.sys", "swapfile.sys", "thumbs.db",
    "desktop.ini", "ntuser.dat", "ntuser.dat.log1", "ntuser.dat.log2",
    "iconcache.db",
}

# 系统服务 / 无界面进程默认不计入软件使用统计（可在设置中增删）
DEFAULT_PROCESS_BLACKLIST = [
    "system", "registry", "idle", "smss.exe", "csrss.exe", "wininit.exe",
    "winlogon.exe", "services.exe", "lsass.exe", "lsaiso.exe", "svchost.exe",
    "fontdrvhost.exe", "dwm.exe", "sihost.exe", "taskhostw.exe", "conhost.exe",
    "dllhost.exe", "wmiprvse.exe", "runtimebroker.exe", "applicationframehost.exe",
    "shellexperiencehost.exe", "startmenuexperiencehost.exe", "textinputhost.exe",
    "searchindexer.exe", "searchprotocolhost.exe", "searchfilterhost.exe",
    "spoolsv.exe", "audiodg.exe", "ctfmon.exe", "dashost.exe", "dasbroker.exe",
    "securityhealthservice.exe", "msmpeng.exe", "nissrv.exe", "mpdefendercoreservice.exe",
    "wudfhost.exe", "wudfcompanionhost.exe", "trustedinstaller.exe", "tiworker.exe",
    "usocoreworker.exe", "mousocoreworker.exe", "sedsvc.exe", "remsh.exe",
    "consent.exe", "lockapp.exe", "logonui.exe", "vmmem", "vmcompute.exe", "vmms.exe",
    "comppkgsrv.exe", "musnotification.exe", "systemsettingsbroker.exe",
]


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DIR.mkdir(parents=True, exist_ok=True)


def _default_roots() -> list[str]:
    home = Path.home()
    candidates = [
        home / "Desktop", home / "Documents", home / "Downloads",
        home / "OneDrive" / "Desktop", home / "OneDrive" / "Documents",
        home / "OneDrive" / "Downloads",
    ]
    roots: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path).lower()
        if path.is_dir() and key not in seen:
            seen.add(key)
            roots.append(str(path))
    return roots or [str(home)]


@dataclass
class AppConfig:
    monitor_roots: list[str] = field(default_factory=_default_roots)
    extensions: list[str] = field(default_factory=lambda: list(DEFAULT_EXTENSIONS))
    office_extensions: list[str] = field(default_factory=lambda: list(DEFAULT_OFFICE_EXTENSIONS))
    ignore_junk: bool = True
    extra_excludes: list[str] = field(default_factory=list)
    min_size_kb: int = 0
    idle_threshold_sec: int = 120
    retention_days: int = 90
    autostart: bool = False
    minimize_to_tray: bool = True
    start_monitoring: bool = True
    power_events_days: int = 30

    theme: str = "light"
    sidebar_collapsed: bool = False

    process_tracking: bool = True
    process_blacklist: list[str] = field(default_factory=lambda: list(DEFAULT_PROCESS_BLACKLIST))
    process_whitelist: list[str] = field(default_factory=list)

    traffic_tracking: bool = True

    reminder_app_enabled: bool = True
    reminder_app_minutes: int = 120
    reminder_burst_enabled: bool = True
    reminder_burst_count: int = 30
    reminder_burst_window_sec: int = 60
    reminder_traffic_enabled: bool = True
    reminder_traffic_mb_per_min: int = 60
    reminder_cooldown_min: int = 30
    app_time_limits: dict = field(default_factory=dict)

    def normalize(self) -> None:
        roots: list[str] = []
        seen: set[str] = set()
        for raw in self.monitor_roots or []:
            text = os.path.normpath(str(raw).strip())
            if not text or text == ".":
                continue
            key = text.lower()
            if key not in seen:
                seen.add(key)
                roots.append(text)
        self.monitor_roots = roots

        self.extensions = _norm_tokens(self.extensions, strip_dot=True)
        self.office_extensions = _norm_tokens(self.office_extensions, strip_dot=True)
        self.extra_excludes = [str(x).strip() for x in (self.extra_excludes or []) if str(x).strip()]
        self.process_blacklist = _norm_tokens(self.process_blacklist)
        self.process_whitelist = _norm_tokens(self.process_whitelist)

        self.min_size_kb = max(0, int(self.min_size_kb or 0))
        self.idle_threshold_sec = min(3600, max(10, int(self.idle_threshold_sec or 120)))
        self.retention_days = min(3650, max(0, int(self.retention_days or 0)))
        self.power_events_days = min(365, max(1, int(self.power_events_days or 30)))
        self.theme = self.theme if self.theme in ("light", "dark") else "light"
        self.reminder_app_minutes = min(1440, max(5, int(self.reminder_app_minutes or 120)))
        self.reminder_burst_count = min(10000, max(2, int(self.reminder_burst_count or 30)))
        self.reminder_burst_window_sec = min(3600, max(10, int(self.reminder_burst_window_sec or 60)))
        self.reminder_traffic_mb_per_min = min(100000, max(1, int(self.reminder_traffic_mb_per_min or 60)))
        self.reminder_cooldown_min = min(1440, max(1, int(self.reminder_cooldown_min or 30)))
        limits: dict[str, int] = {}
        for key, value in (self.app_time_limits or {}).items():
            text = str(key).strip().lower()
            if not text:
                continue
            try:
                minutes = int(value)
            except (TypeError, ValueError):
                continue
            limits[text] = min(1440, max(1, minutes))
        self.app_time_limits = limits

    @classmethod
    def load(cls, path: Path = SETTINGS_PATH) -> "AppConfig":
        config = cls()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                known = {f.name: f for f in fields(cls)}
                for key, value in data.items():
                    if key not in known:
                        continue
                    default = getattr(config, key)
                    if isinstance(default, bool):
                        setattr(config, key, bool(value))
                    elif isinstance(default, int):
                        setattr(config, key, int(value))
                    elif isinstance(default, list):
                        if isinstance(value, list):
                            setattr(config, key, [str(v) for v in value])
                    elif isinstance(default, dict):
                        if isinstance(value, dict):
                            setattr(config, key, {str(k): v for k, v in value.items()})
                    else:
                        setattr(config, key, value)
            except (ValueError, OSError, TypeError):
                pass
        config.normalize()
        return config

    def save(self, path: Path = SETTINGS_PATH) -> None:
        self.normalize()
        ensure_dirs()
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    def is_office(self, ext: str) -> bool:
        return (ext or "").lower().lstrip(".") in set(self.office_extensions)


def _norm_tokens(values: list[str] | None, strip_dot: bool = False) -> list[str]:
    out: list[str] = []
    for raw in values or []:
        text = str(raw).strip().lower()
        if strip_dot:
            text = text.lstrip("*").lstrip(".")
        if text and text not in out:
            out.append(text)
    return out


def write_data_location(target: Path) -> None:
    """记录自定义数据目录；下次启动生效。"""
    base = _default_base()
    base.mkdir(parents=True, exist_ok=True)
    LOCATION_POINTER.write_text(
        json.dumps({"data_dir": str(target)}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def clear_data_location() -> None:
    try:
        LOCATION_POINTER.unlink(missing_ok=True)
    except OSError:
        pass