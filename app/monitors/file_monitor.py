from __future__ import annotations

import logging
import os
import queue
import threading
import time
from typing import Iterable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from app.config import (
    BLOCKED_EXTENSIONS,
    BLOCKED_FILENAMES,
    DATA_DIR,
    DEFAULT_JUNK_SEGMENTS,
    AppConfig,
)
from app.utils import now_iso

log = logging.getLogger(__name__)

_QUEUE_MAX = 20000
_DEDUPE_WINDOW = 2.0
_CREATED_GUARD = 3.0


def _fold(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def normalize_roots(roots: Iterable[str]) -> list[str]:
    existing: list[str] = []
    for raw in roots:
        text = os.path.normpath(str(raw))
        if text and os.path.isdir(text):
            existing.append(text)
    existing.sort(key=len)
    result: list[str] = []
    for candidate in existing:
        folded = _fold(candidate)
        if any(
            folded == _fold(parent) or folded.startswith(_fold(parent) + os.sep)
            for parent in result
        ):
            continue
        result.append(candidate)
    return result


class _WatchHandler(FileSystemEventHandler):
    def __init__(self, monitor: "FileMonitor", root: str):
        self.monitor = monitor
        self.root = root

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle(event, "created")

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle(event, "modified")

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._handle(event, "deleted")

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src = str(event.src_path)
        dest = str(event.dest_path)
        self.monitor.forget_size(src)
        self._submit(dest, "renamed", old_path=src)

    def _handle(self, event: FileSystemEvent, kind: str) -> None:
        if event.is_directory:
            return
        self._submit(str(event.src_path), kind)

    def _submit(self, path: str, kind: str, old_path: str = "") -> None:
        try:
            if not self.monitor.accepts(path):
                return
            size = self.monitor.size_for(path, is_delete=kind == "deleted")
            self.monitor.enqueue(kind, path, size, self.root, old_path=old_path)
        except Exception:  # watchdog threads must never die
            log.exception("file event handling failed: %s", path)


class FileMonitor:
    def __init__(self, config: AppConfig):
        self._cfg = config
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=_QUEUE_MAX)
        self._observer: Observer | None = None
        self._root_list: list[str] = []
        self._lock = threading.Lock()
        self._sizes: dict[str, int] = {}
        self._dedupe: dict[str, tuple[str, float]] = {}
        self._recent_created: dict[str, float] = {}
        self.started_at: str | None = None
        self.accepted = 0
        self.dropped = 0
        self.last_event_at: str | None = None
        self.errors: list[str] = []
        self._app_provider = None
        self._apply_config(config)

    def set_app_provider(self, provider) -> None:
        """provider() -> {'name','app_key'} | None，用于推测操作文件的软件。"""
        self._app_provider = provider

    # -------- filters --------

    def _apply_config(self, config: AppConfig) -> None:
        self._extensions = {e.lower().lstrip(".") for e in config.extensions if e.strip()}
        self._ignore_junk = bool(config.ignore_junk)
        self._extra_excludes = [x.lower() for x in config.extra_excludes if x.strip()]
        self._min_size = max(0, int(config.min_size_kb)) * 1024
        self._data_root = _fold(str(DATA_DIR))

    def update_config(self, config: AppConfig) -> None:
        self._cfg = config
        self._apply_config(config)

    def accepts(self, path: str) -> bool:
        folded = _fold(path)
        if folded == self._data_root or folded.startswith(self._data_root + os.sep):
            return False
        name = os.path.basename(path)
        lower_name = name.lower()
        if lower_name.startswith("~$"):
            return False
        if self._ignore_junk:
            if lower_name in BLOCKED_FILENAMES:
                return False
            if lower_name.startswith("ntuser.dat") or lower_name.startswith("iconcache"):
                return False
            ext = os.path.splitext(lower_name)[1].lstrip(".")
            if ext in BLOCKED_EXTENSIONS:
                return False
            haystack = path.lower() + "\\"
            if any(segment in haystack for segment in DEFAULT_JUNK_SEGMENTS):
                return False
        if self._extra_excludes and any(token in path.lower() for token in self._extra_excludes):
            return False
        ext = os.path.splitext(lower_name)[1].lstrip(".")
        if self._extensions and ext not in self._extensions:
            return False
        return True

    def size_for(self, path: str, is_delete: bool = False) -> int | None:
        key = path.lower()
        if is_delete:
            return self._sizes.pop(key, None)
        try:
            size = os.path.getsize(path)
        except OSError:
            return self._sizes.get(key)
        if len(self._sizes) < 100000:
            self._sizes[key] = size
        else:
            self._sizes.clear()
            self._sizes[key] = size
        return size

    def forget_size(self, path: str) -> None:
        self._sizes.pop(path.lower(), None)

    def enqueue(self, kind: str, path: str, size: int | None, root: str, old_path: str = "") -> None:
        if size is not None and size < self._min_size:
            return
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        process_name, process_key = "", ""
        if self._app_provider is not None:
            try:
                info = self._app_provider()
                if info:
                    process_name = info.get("name", "")
                    process_key = info.get("app_key", "")
            except Exception:
                pass
        item = {
            "event_type": kind,
            "path": path,
            "name": name,
            "ext": ext,
            "size": size,
            "event_time": now_iso(),
            "root": root,
            "process_name": process_name,
            "process_key": process_key,
            "old_path": old_path,
            "_mono": time.monotonic(),
        }
        with self._lock:
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                self.dropped += 1
                return
            self.accepted += 1
            self.last_event_at = item["event_time"]

    # -------- lifecycle --------

    @property
    def running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()

    @property
    def watched_roots(self) -> list[str]:
        return list(self._root_list)

    def start(self, config: AppConfig | None = None) -> bool:
        if config is not None:
            self.update_config(config)
        self.stop()
        self.errors = []
        roots = normalize_roots(self._cfg.monitor_roots)
        if not roots:
            self.errors.append("未选择有效的监测目录")
            self._root_list = []
            return False
        observer = Observer(timeout=1)
        watched: list[str] = []
        for root in roots:
            try:
                observer.schedule(_WatchHandler(self, root), root, recursive=True)
                watched.append(root)
            except OSError as exc:
                self.errors.append(f"{root}：{exc}")
                log.warning("cannot watch %s: %s", root, exc)
        if not watched:
            self._root_list = []
            return False
        observer.start()
        self._observer = observer
        self._root_list = watched
        self.started_at = now_iso()
        self.accepted = 0
        self.dropped = 0
        self.last_event_at = None
        log.info("file monitor started on %s", ", ".join(watched))
        return True

    def stop(self) -> None:
        observer = self._observer
        self._observer = None
        if observer is not None:
            try:
                observer.stop()
                observer.join(timeout=3)
            except RuntimeError:
                pass
            log.info("file monitor stopped")

    def drain(self, max_items: int = 800) -> list[dict]:
        items: list[dict] = []
        while len(items) < max_items:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            key = item["path"].lower()
            kind = item["event_type"]
            mono = item.pop("_mono", time.monotonic())
            if kind == "modified" and mono - self._recent_created.get(key, 0.0) < _CREATED_GUARD:
                continue
            previous = self._dedupe.get(key)
            if previous and previous[0] == kind and mono - previous[1] < _DEDUPE_WINDOW:
                continue
            self._dedupe[key] = (kind, mono)
            if kind == "created":
                self._recent_created[key] = mono
            items.append(item)
        if len(self._dedupe) > 60000:
            self._dedupe.clear()
            self._recent_created.clear()
        return items

    def clear_queue(self) -> int:
        count = 0
        while True:
            try:
                self._queue.get_nowait()
                count += 1
            except queue.Empty:
                break
        return count

    def status_text(self) -> str:
        if self.running:
            return f"文件监测中 · {len(self._root_list)} 个目录"
        if not self._cfg.monitor_roots:
            return "未配置监测目录"
        return "文件监测已暂停"