from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from app.utils import day_bounds, parse_iso

log = logging.getLogger(__name__)

HOST_KEY = "__host__"

SCHEMA = """
CREATE TABLE IF NOT EXISTS file_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    ext TEXT NOT NULL DEFAULT '',
    size INTEGER,
    event_time TEXT NOT NULL,
    root TEXT NOT NULL DEFAULT '',
    process_name TEXT NOT NULL DEFAULT '',
    process_key TEXT NOT NULL DEFAULT '',
    old_path TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_file_events_time ON file_events(event_time);
CREATE INDEX IF NOT EXISTS idx_file_events_type ON file_events(event_type);
CREATE INDEX IF NOT EXISTS idx_file_events_ext ON file_events(ext);
CREATE INDEX IF NOT EXISTS idx_file_events_process ON file_events(process_key);

CREATE TABLE IF NOT EXISTS usage_stats (
    day TEXT NOT NULL,
    hour INTEGER NOT NULL,
    active_sec INTEGER NOT NULL DEFAULT 0,
    idle_sec INTEGER NOT NULL DEFAULT 0,
    lock_sec INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, hour)
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT NOT NULL,
    end_time TEXT,
    last_seen TEXT NOT NULL,
    active_sec INTEGER NOT NULL DEFAULT 0,
    idle_sec INTEGER NOT NULL DEFAULT 0,
    lock_sec INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS power_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_code INTEGER NOT NULL,
    kind TEXT NOT NULL,
    event_time TEXT NOT NULL,
    UNIQUE(event_code, event_time)
);
CREATE INDEX IF NOT EXISTS idx_power_events_time ON power_events(event_time);

CREATE TABLE IF NOT EXISTS app_registry (
    app_key TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    exe TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL DEFAULT '',
    last_seen TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS app_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,
    last_seen TEXT NOT NULL,
    foreground_sec INTEGER NOT NULL DEFAULT 0,
    background_sec INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_app_sessions_key ON app_sessions(app_key);
CREATE INDEX IF NOT EXISTS idx_app_sessions_time ON app_sessions(start_time);

CREATE TABLE IF NOT EXISTS app_daily (
    day TEXT NOT NULL,
    app_key TEXT NOT NULL,
    foreground_sec INTEGER NOT NULL DEFAULT 0,
    background_sec INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, app_key)
);

CREATE TABLE IF NOT EXISTS network_daily (
    day TEXT NOT NULL,
    app_key TEXT NOT NULL,
    bytes_in INTEGER NOT NULL DEFAULT 0,
    bytes_out INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, app_key)
);

CREATE TABLE IF NOT EXISTS network_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_time TEXT NOT NULL,
    bytes_in INTEGER NOT NULL DEFAULT 0,
    bytes_out INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_network_samples_time ON network_samples(sample_time);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# 旧版本（v1）缺失的列，启动时自动补齐
_MIGRATIONS = {
    "file_events": [
        ("process_name", "TEXT NOT NULL DEFAULT ''"),
        ("process_key", "TEXT NOT NULL DEFAULT ''"),
        ("old_path", "TEXT NOT NULL DEFAULT ''"),
    ],
    "usage_stats": [("lock_sec", "INTEGER NOT NULL DEFAULT 0")],
    "sessions": [("lock_sec", "INTEGER NOT NULL DEFAULT 0")],
}


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA temp_store=MEMORY")

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        for table, columns in _MIGRATIONS.items():
            existing = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            for column, decl in columns:
                if column not in existing:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        self.conn.commit()
        self.set_meta("schema_version", "2")

    def close(self) -> None:
        try:
            self.conn.commit()
            self.conn.close()
        except sqlite3.Error:
            pass

    # ---------------- file events ----------------

    def insert_file_events(self, events: Iterable[dict]) -> int:
        rows = [
            (
                e["event_type"],
                e["path"],
                e["name"],
                e.get("ext", ""),
                e.get("size"),
                e["event_time"],
                e.get("root", ""),
                e.get("process_name", ""),
                e.get("process_key", ""),
                e.get("old_path", ""),
            )
            for e in events
        ]
        if not rows:
            return 0
        with self.conn:
            self.conn.executemany(
                "INSERT INTO file_events(event_type, path, name, ext, size, event_time, root, "
                "process_name, process_key, old_path) VALUES(?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
        return len(rows)

    def query_file_events(
        self,
        *,
        event_type: str | None = None,
        ext: str | None = None,
        start_iso: str | None = None,
        end_iso: str | None = None,
        keyword: str | None = None,
        process_key: str | None = None,
        group: str | None = None,
        office_exts: list[str] | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        clauses: list[str] = []
        params: list[object] = []
        if event_type and event_type != "all":
            clauses.append("event_type = ?")
            params.append(event_type)
        if ext:
            clauses.append("ext = ?")
            params.append(ext.lower())
        if start_iso:
            clauses.append("event_time >= ?")
            params.append(start_iso)
        if end_iso:
            clauses.append("event_time < ?")
            params.append(end_iso)
        if keyword:
            pattern = f"%{_escape_like(keyword.strip())}%"
            clauses.append("(name LIKE ? ESCAPE '\\' OR path LIKE ? ESCAPE '\\')")
            params.extend([pattern, pattern])
        if process_key:
            clauses.append("process_key = ?")
            params.append(process_key)
        if group in ("office", "other") and office_exts:
            placeholders = ",".join("?" for _ in office_exts)
            if group == "office":
                clauses.append(f"ext IN ({placeholders})")
            else:
                clauses.append(f"(ext NOT IN ({placeholders}) OR ext = '')")
            params.extend(office_exts)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        total = self.conn.execute(f"SELECT COUNT(*) FROM file_events{where}", params).fetchone()[0]
        rows = self.conn.execute(
            f"SELECT * FROM file_events{where} ORDER BY event_time DESC, id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return [dict(r) for r in rows], int(total)

    def event_counts(self, day: date) -> dict[str, int]:
        start, end = day_bounds(day)
        rows = self.conn.execute(
            "SELECT event_type, COUNT(*) AS c FROM file_events "
            "WHERE event_time >= ? AND event_time < ? GROUP BY event_type",
            (start, end),
        ).fetchall()
        counts = {"created": 0, "modified": 0, "deleted": 0, "renamed": 0}
        for row in rows:
            if row["event_type"] in counts:
                counts[row["event_type"]] = int(row["c"])
        return counts

    def event_counts_between(self, start_iso: str, end_iso: str) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT event_type, COUNT(*) AS c FROM file_events "
            "WHERE event_time >= ? AND event_time < ? GROUP BY event_type",
            (start_iso, end_iso),
        ).fetchall()
        counts = {"created": 0, "modified": 0, "deleted": 0, "renamed": 0}
        for row in rows:
            if row["event_type"] in counts:
                counts[row["event_type"]] = int(row["c"])
        return counts

    def office_type_counts(
        self, start_iso: str, end_iso: str, office_exts: list[str]
    ) -> dict[str, int]:
        """办公文档按 Word / Excel / PDF / PPT 归类计数。"""
        groups = {
            "Word": {"docx", "doc"},
            "Excel": {"xlsx", "xls"},
            "PDF": {"pdf"},
            "PPT": {"pptx", "ppt"},
        }
        office = {e.lower().lstrip(".") for e in office_exts}
        rows = self.conn.execute(
            "SELECT ext, COUNT(*) AS c FROM file_events "
            "WHERE event_time >= ? AND event_time < ? GROUP BY ext",
            (start_iso, end_iso),
        ).fetchall()
        result = {name: 0 for name in groups}
        result["其他办公"] = 0
        for row in rows:
            ext = (row["ext"] or "").lower()
            if ext not in office:
                continue
            count = int(row["c"])
            for name, exts in groups.items():
                if ext in exts:
                    result[name] += count
                    break
            else:
                result["其他办公"] += count
        return result

    def group_counts_between(
        self, start_iso: str, end_iso: str, office_exts: list[str]
    ) -> dict[str, int]:
        office = {e.lower().lstrip(".") for e in office_exts}
        rows = self.conn.execute(
            "SELECT ext, COUNT(*) AS c FROM file_events "
            "WHERE event_time >= ? AND event_time < ? GROUP BY ext",
            (start_iso, end_iso),
        ).fetchall()
        office_count = 0
        other_count = 0
        for row in rows:
            count = int(row["c"])
            if (row["ext"] or "").lower() in office:
                office_count += count
            else:
                other_count += count
        return {"office": office_count, "other": other_count, "all": office_count + other_count}

    def recent_file_events(self, limit: int = 8, office_exts: list[str] | None = None) -> list[dict]:
        if office_exts:
            placeholders = ",".join("?" for _ in office_exts)
            rows = self.conn.execute(
                f"SELECT * FROM file_events WHERE ext IN ({placeholders}) "
                "ORDER BY event_time DESC, id DESC LIMIT ?",
                [*office_exts, limit],
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM file_events ORDER BY event_time DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def distinct_extensions(self, limit: int = 120) -> list[tuple[str, int]]:
        rows = self.conn.execute(
            "SELECT ext, COUNT(*) AS c FROM file_events WHERE ext <> '' "
            "GROUP BY ext ORDER BY c DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [(r["ext"], int(r["c"])) for r in rows]

    def distinct_processes(self, limit: int = 120) -> list[tuple[str, str, int]]:
        rows = self.conn.execute(
            "SELECT process_key, process_name, COUNT(*) AS c FROM file_events "
            "WHERE process_key <> '' GROUP BY process_key ORDER BY c DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [(r["process_key"], r["process_name"], int(r["c"])) for r in rows]

    def count_events_since(self, seconds: int) -> int:
        cutoff = (datetime.now() - timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM file_events WHERE event_time >= ?", (cutoff,)
            ).fetchone()[0]
        )

    def clear_file_events(self) -> int:
        with self.conn:
            count = self.conn.execute("SELECT COUNT(*) FROM file_events").fetchone()[0]
            self.conn.execute("DELETE FROM file_events")
            self.conn.execute("DELETE FROM sqlite_sequence WHERE name='file_events'")
        return int(count)

    def purge_old_logs(self, retention_days: int) -> dict[str, int]:
        if retention_days <= 0:
            return {}
        cutoff = (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%d 00:00:00")
        removed: dict[str, int] = {}
        with self.conn:
            for table, column in (
                ("file_events", "event_time"),
                ("app_sessions", "start_time"),
                ("network_samples", "sample_time"),
            ):
                cur = self.conn.execute(f"DELETE FROM {table} WHERE {column} < ?", (cutoff,))
                removed[table] = int(cur.rowcount or 0)
        return removed

    # 兼容旧调用
    def purge_file_events(self, retention_days: int) -> int:
        return self.purge_old_logs(retention_days).get("file_events", 0)

    # ---------------- usage ----------------

    def add_usage(
        self, day: str, hour: int, active_delta: int = 0, idle_delta: int = 0, lock_delta: int = 0
    ) -> None:
        if active_delta <= 0 and idle_delta <= 0 and lock_delta <= 0:
            return
        with self.conn:
            self.conn.execute(
                "INSERT INTO usage_stats(day, hour, active_sec, idle_sec, lock_sec) VALUES(?,?,?,?,?) "
                "ON CONFLICT(day, hour) DO UPDATE SET "
                "active_sec = active_sec + excluded.active_sec, "
                "idle_sec = idle_sec + excluded.idle_sec, "
                "lock_sec = lock_sec + excluded.lock_sec",
                (day, hour, active_delta, idle_delta, lock_delta),
            )

    def usage_hour_map(self, day: str) -> tuple[list[int], list[int], list[int]]:
        active = [0] * 24
        idle = [0] * 24
        lock = [0] * 24
        rows = self.conn.execute(
            "SELECT hour, active_sec, idle_sec, lock_sec FROM usage_stats WHERE day = ?", (day,)
        ).fetchall()
        for row in rows:
            hour = int(row["hour"])
            if 0 <= hour < 24:
                active[hour] = int(row["active_sec"])
                idle[hour] = int(row["idle_sec"])
                lock[hour] = int(row["lock_sec"])
        return active, idle, lock

    def usage_daily_map(self, start_day: str, end_day: str) -> dict[str, tuple[int, int, int]]:
        rows = self.conn.execute(
            "SELECT day, SUM(active_sec) AS a, SUM(idle_sec) AS i, SUM(lock_sec) AS l "
            "FROM usage_stats WHERE day >= ? AND day <= ? GROUP BY day",
            (start_day, end_day),
        ).fetchall()
        return {r["day"]: (int(r["a"] or 0), int(r["i"] or 0), int(r["l"] or 0)) for r in rows}

    def usage_totals(self, start_day: str, end_day: str) -> tuple[int, int, int]:
        row = self.conn.execute(
            "SELECT SUM(active_sec) AS a, SUM(idle_sec) AS i, SUM(lock_sec) AS l FROM usage_stats "
            "WHERE day >= ? AND day <= ?",
            (start_day, end_day),
        ).fetchone()
        return int(row["a"] or 0), int(row["i"] or 0), int(row["l"] or 0)

    # ---------------- sessions ----------------

    def open_session(self, start_iso: str, last_seen: str) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO sessions(start_time, last_seen) VALUES(?,?)", (start_iso, last_seen)
            )
        return int(cur.lastrowid)

    def touch_session(
        self, session_id: int, last_seen: str,
        active_delta: int = 0, idle_delta: int = 0, lock_delta: int = 0,
    ) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE sessions SET last_seen = ?, active_sec = active_sec + ?, "
                "idle_sec = idle_sec + ?, lock_sec = lock_sec + ? WHERE id = ?",
                (last_seen, active_delta, idle_delta, lock_delta, session_id),
            )

    def close_session(self, session_id: int, end_iso: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE sessions SET end_time = ?, last_seen = ? WHERE id = ? AND end_time IS NULL",
                (end_iso, end_iso, session_id),
            )

    def close_dangling_sessions(self) -> None:
        with self.conn:
            self.conn.execute("UPDATE sessions SET end_time = last_seen WHERE end_time IS NULL")

    def current_session(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE end_time IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def recent_sessions(self, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM sessions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------------- apps ----------------

    def upsert_app(self, app_key: str, name: str, exe: str, seen_iso: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO app_registry(app_key, name, exe, first_seen, last_seen) VALUES(?,?,?,?,?) "
                "ON CONFLICT(app_key) DO UPDATE SET name=excluded.name, exe=excluded.exe, "
                "last_seen=excluded.last_seen",
                (app_key, name, exe, seen_iso, seen_iso),
            )

    def app_name(self, app_key: str) -> str:
        row = self.conn.execute(
            "SELECT name FROM app_registry WHERE app_key = ?", (app_key,)
        ).fetchone()
        return row["name"] if row else app_key

    def refresh_app_names(self, namer) -> int:
        """按当前命名规则重算已登记软件的显示名（规则升级后同步历史数据）。"""
        rows = self.conn.execute("SELECT app_key, exe, name FROM app_registry").fetchall()
        changed = 0
        with self.conn:
            for row in rows:
                new = namer(row["exe"]) if row["exe"] else ""
                if new and new != row["name"]:
                    self.conn.execute(
                        "UPDATE app_registry SET name = ? WHERE app_key = ?",
                        (new, row["app_key"]),
                    )
                    changed += 1
        return changed

    def open_app_session(self, app_key: str, start_iso: str) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO app_sessions(app_key, start_time, last_seen) VALUES(?,?,?)",
                (app_key, start_iso, start_iso),
            )
        return int(cur.lastrowid)

    def touch_app_session(
        self, session_id: int, last_seen: str, foreground_delta: int = 0, background_delta: int = 0
    ) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE app_sessions SET last_seen = ?, foreground_sec = foreground_sec + ?, "
                "background_sec = background_sec + ? WHERE id = ?",
                (last_seen, foreground_delta, background_delta, session_id),
            )

    def close_app_session(self, session_id: int, end_iso: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE app_sessions SET end_time = ?, last_seen = ? WHERE id = ? AND end_time IS NULL",
                (end_iso, end_iso, session_id),
            )

    def close_dangling_app_sessions(self) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE app_sessions SET end_time = last_seen WHERE end_time IS NULL"
            )

    def add_app_daily(self, day: str, app_key: str, foreground: int = 0, background: int = 0) -> None:
        if foreground <= 0 and background <= 0:
            return
        with self.conn:
            self.conn.execute(
                "INSERT INTO app_daily(day, app_key, foreground_sec, background_sec) VALUES(?,?,?,?) "
                "ON CONFLICT(day, app_key) DO UPDATE SET "
                "foreground_sec = foreground_sec + excluded.foreground_sec, "
                "background_sec = background_sec + excluded.background_sec",
                (day, app_key, foreground, background),
            )

    def app_ranking(self, start_day: str, end_day: str, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT d.app_key, COALESCE(r.name, d.app_key) AS name, COALESCE(r.exe, '') AS exe, "
            "SUM(d.foreground_sec) AS fg, SUM(d.background_sec) AS bg "
            "FROM app_daily d LEFT JOIN app_registry r ON r.app_key = d.app_key "
            "WHERE d.day >= ? AND d.day <= ? GROUP BY d.app_key "
            "ORDER BY fg DESC, bg DESC LIMIT ?",
            (start_day, end_day, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def app_daily_series(self, app_key: str, start_day: str, end_day: str) -> dict[str, tuple[int, int]]:
        rows = self.conn.execute(
            "SELECT day, foreground_sec, background_sec FROM app_daily "
            "WHERE app_key = ? AND day >= ? AND day <= ?",
            (app_key, start_day, end_day),
        ).fetchall()
        return {r["day"]: (int(r["foreground_sec"]), int(r["background_sec"])) for r in rows}

    def app_sessions_on(self, app_key: str, start_iso: str, end_iso: str, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM app_sessions WHERE app_key = ? AND start_time < ? "
            "AND COALESCE(end_time, last_seen) >= ? ORDER BY start_time DESC LIMIT ?",
            (app_key, end_iso, start_iso, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------------- network ----------------

    def add_network_daily(self, day: str, app_key: str, bytes_in: int = 0, bytes_out: int = 0) -> None:
        if bytes_in <= 0 and bytes_out <= 0:
            return
        with self.conn:
            self.conn.execute(
                "INSERT INTO network_daily(day, app_key, bytes_in, bytes_out) VALUES(?,?,?,?) "
                "ON CONFLICT(day, app_key) DO UPDATE SET "
                "bytes_in = bytes_in + excluded.bytes_in, bytes_out = bytes_out + excluded.bytes_out",
                (day, app_key, bytes_in, bytes_out),
            )

    def network_ranking(self, start_day: str, end_day: str, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT d.app_key, COALESCE(r.name, d.app_key) AS name, "
            "SUM(d.bytes_in) AS bin, SUM(d.bytes_out) AS bout "
            "FROM network_daily d LEFT JOIN app_registry r ON r.app_key = d.app_key "
            "WHERE d.day >= ? AND d.day <= ? AND d.app_key <> ? GROUP BY d.app_key "
            "ORDER BY (bin + bout) DESC LIMIT ?",
            (start_day, end_day, HOST_KEY, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def network_host_totals(self, start_day: str, end_day: str) -> tuple[int, int]:
        row = self.conn.execute(
            "SELECT SUM(bytes_in) AS bin, SUM(bytes_out) AS bout FROM network_daily "
            "WHERE day >= ? AND day <= ? AND app_key = ?",
            (start_day, end_day, HOST_KEY),
        ).fetchone()
        return int(row["bin"] or 0), int(row["bout"] or 0)

    def add_network_sample(self, sample_time: str, bytes_in: int, bytes_out: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO network_samples(sample_time, bytes_in, bytes_out) VALUES(?,?,?)",
                (sample_time, bytes_in, bytes_out),
            )
            self.conn.execute(
                "DELETE FROM network_samples WHERE id NOT IN "
                "(SELECT id FROM network_samples ORDER BY id DESC LIMIT 900)"
            )

    def network_samples(self, limit: int = 180) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM (SELECT * FROM network_samples ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------------- power events ----------------

    def insert_power_events(self, events: Iterable[dict]) -> int:
        rows = [
            (int(e["event_code"]), e["kind"], e["event_time"])
            for e in events
            if e.get("event_code") is not None and e.get("event_time")
        ]
        if not rows:
            return 0
        before = self.conn.execute("SELECT COUNT(*) FROM power_events").fetchone()[0]
        with self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO power_events(event_code, kind, event_time) VALUES(?,?,?)",
                rows,
            )
        after = self.conn.execute("SELECT COUNT(*) FROM power_events").fetchone()[0]
        return int(after - before)

    def power_events_between(self, start_iso: str, end_iso: str, limit: int = 500) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM power_events WHERE event_time >= ? AND event_time < ? "
            "ORDER BY event_time ASC LIMIT ?",
            (start_iso, end_iso, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def power_events_latest(self, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM power_events ORDER BY event_time DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def power_event_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM power_events").fetchone()[0])

    # ---------------- meta / maintenance ----------------

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO meta(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def file_size(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            if candidate.exists():
                try:
                    total += candidate.stat().st_size
                except OSError:
                    pass
        return total

    def count_events(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM file_events").fetchone()[0])

    def session_span(self, session: dict) -> tuple[datetime | None, datetime | None]:
        start = parse_iso(session.get("start_time", ""))
        end = parse_iso(session.get("end_time") or "") or parse_iso(session.get("last_seen") or "")
        return start, end