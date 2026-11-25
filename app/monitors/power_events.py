from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from datetime import datetime, timedelta

from PyQt6.QtCore import QThread, pyqtSignal

from app.database import Database
from app.utils import parse_iso, to_iso

log = logging.getLogger(__name__)

POWER_KIND_LABELS = {
    "boot": "开机",
    "shutdown": "关机",
    "sleep": "进入睡眠",
    "resume": "从睡眠唤醒",
    "unexpected": "异常断电 / 重启",
}

POWER_EVENT_IDS = {
    12: "boot",
    6005: "boot",
    13: "shutdown",
    6006: "shutdown",
    42: "sleep",
    107: "resume",
    1: "resume",
    41: "unexpected",
    6008: "unexpected",
}

_NO_EVENT_HINTS = ("no events were found", "没有找到", "未找到")

_PS_SCRIPT = """
$ErrorActionPreference = 'Stop'
try {{
  $events = Get-WinEvent -FilterHashtable @{{LogName='System'; Id=12,13,41,42,107,1,6005,6006,6008; StartTime=(Get-Date).AddDays(-{days})}} -ErrorAction Stop
  $out = @($events | Sort-Object TimeCreated | ForEach-Object {{
    [pscustomobject]@{{ Id = $_.Id; Time = $_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss') }}
  }})
  if ($out.Count -eq 0) {{ '[]' }} else {{ ConvertTo-Json -InputObject $out -Compress }}
}} catch {{
  [Console]::Error.WriteLine($_.Exception.Message)
  '[]'
}}
"""


def kind_label(kind: str) -> str:
    return POWER_KIND_LABELS.get(kind, kind)


def fetch_power_events(days: int = 30) -> tuple[list[dict], str]:
    script = _PS_SCRIPT.format(days=max(1, int(days)))
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("power event query failed: %s", exc)
        return [], f"读取系统事件日志失败：{exc}"
    stdout = (result.stdout or "").strip().lstrip("\ufeff")
    stderr = (result.stderr or "").strip()
    payload = None
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("[") or line.startswith("{"):
            payload = line
            break
    events: list[dict] = []
    if payload:
        try:
            data = json.loads(payload)
            if isinstance(data, dict):
                data = [data]
            for item in data:
                try:
                    code = int(item.get("Id"))
                except (TypeError, ValueError):
                    continue
                kind = POWER_EVENT_IDS.get(code)
                stamp = str(item.get("Time") or "").strip()
                if not kind or not stamp:
                    continue
                try:
                    datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                events.append({"event_code": code, "kind": kind, "event_time": stamp})
        except (ValueError, TypeError):
            log.warning("cannot parse power event output: %s", payload[:200])
    error = ""
    if not events:
        lowered = stderr.lower()
        if stderr and not any(hint in lowered for hint in _NO_EVENT_HINTS):
            error = stderr.splitlines()[-1][:300]
    return events, error


class PowerEventsWorker(QThread):
    loaded = pyqtSignal(list, str)

    def __init__(self, days: int = 30, parent=None):
        super().__init__(parent)
        self._days = days

    def run(self) -> None:
        started = time.monotonic()
        events, error = fetch_power_events(self._days)
        log.info("power events loaded: %d in %.1fs", len(events), time.monotonic() - started)
        self.loaded.emit(events, error)


def compute_powered_seconds(db: Database, start: datetime, end: datetime) -> int | None:
    if end <= start:
        return 0
    lookback = start - timedelta(days=7)
    events = db.power_events_between(to_iso(lookback), to_iso(end))
    if not events:
        return None
    total = 0.0
    on_since: datetime | None = None
    for event in events:
        moment = parse_iso(event["event_time"])
        if moment is None:
            continue
        kind = event["kind"]
        if moment < start:
            if kind in ("boot", "resume"):
                on_since = start
            elif kind in ("shutdown", "sleep", "unexpected"):
                on_since = None
            continue
        if moment > end:
            break
        if kind in ("boot", "resume"):
            if on_since is None:
                on_since = moment
        elif on_since is not None:
            total += max(0.0, (moment - on_since).total_seconds())
            on_since = None
    if on_since is not None:
        total += max(0.0, (end - on_since).total_seconds())
    return int(total)