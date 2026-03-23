from __future__ import annotations

import json
import queue
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .models import CrossingEvent, MetricsSnapshot
from .utils import isoformat, utc_now


@dataclass
class StorageBacklog:
    oldest_item_ts: datetime | None = None
    latest_write_ts: datetime | None = None


class StorageWriter:
    def __init__(self, sqlite_path: Path, retention_days: int) -> None:
        self.sqlite_path = sqlite_path
        self.retention_days = retention_days
        self.queue: queue.Queue[tuple[str, datetime, dict]] = queue.Queue()
        self.backlog = StorageBacklog()
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    ts TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS crossing_events (
                    event_id TEXT PRIMARY KEY,
                    ts TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    track_id INTEGER NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS validation_sessions (
                    session_id TEXT PRIMARY KEY,
                    started_at TEXT,
                    ended_at TEXT,
                    saved_at TEXT NOT NULL,
                    total_error INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    config_snapshot TEXT NOT NULL
                )
                """
            )

    def start(self) -> None:
        self._running.set()
        self._thread = threading.Thread(target=self._run, name="storage-writer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread:
            self.queue.put(("__stop__", utc_now(), {}))
            self._thread.join(timeout=5)

    def enqueue_snapshot(self, snapshot: MetricsSnapshot) -> None:
        now = utc_now()
        if self.backlog.oldest_item_ts is None:
            self.backlog.oldest_item_ts = now
        self.queue.put(("snapshot", now, snapshot.model_dump(mode="json")))

    def enqueue_event(self, event: CrossingEvent) -> None:
        now = utc_now()
        if self.backlog.oldest_item_ts is None:
            self.backlog.oldest_item_ts = now
        self.queue.put(("event", now, event.model_dump(mode="json")))

    def backlog_age_ms(self) -> int:
        if self.backlog.oldest_item_ts is None:
            return 0
        return int((utc_now() - self.backlog.oldest_item_ts).total_seconds() * 1000)

    def recent_events(self, limit: int = 50) -> list[dict]:
        with sqlite3.connect(self.sqlite_path) as conn:
            rows = conn.execute(
                "SELECT payload FROM crossing_events ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def history(self, minutes: int) -> list[dict]:
        since = isoformat(utc_now() - timedelta(minutes=minutes))
        with sqlite3.connect(self.sqlite_path) as conn:
            rows = conn.execute(
                "SELECT payload FROM snapshots WHERE ts >= ? ORDER BY ts ASC",
                (since,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_validation_session(self, payload: dict, config_snapshot: dict, saved_at: str) -> None:
        stored_payload = dict(payload)
        stored_payload["saved_at"] = saved_at
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO validation_sessions(
                    session_id,
                    started_at,
                    ended_at,
                    saved_at,
                    total_error,
                    payload,
                    config_snapshot
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stored_payload["session_id"],
                    stored_payload.get("started_at"),
                    stored_payload.get("ended_at"),
                    saved_at,
                    stored_payload.get("total_error", 0),
                    json.dumps(stored_payload),
                    json.dumps(config_snapshot),
                ),
            )

    def validation_sessions(self, limit: int = 20) -> list[dict]:
        with sqlite3.connect(self.sqlite_path) as conn:
            rows = conn.execute(
                """
                SELECT payload, config_snapshot
                FROM validation_sessions
                ORDER BY COALESCE(ended_at, started_at, saved_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items: list[dict] = []
        for payload_raw, config_raw in rows:
            item = json.loads(payload_raw)
            item["config_snapshot"] = json.loads(config_raw)
            items.append(item)
        return items

    def _run(self) -> None:
        while self._running.is_set() or not self.queue.empty():
            try:
                kind, _, payload = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if kind == "__stop__":
                if self.queue.empty():
                    self.backlog.oldest_item_ts = None
                continue
            with sqlite3.connect(self.sqlite_path) as conn:
                if kind == "snapshot":
                    conn.execute(
                        "INSERT OR REPLACE INTO snapshots(ts, payload) VALUES(?, ?)",
                        (payload["ts"], json.dumps(payload)),
                    )
                else:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO crossing_events(event_id, ts, direction, track_id, payload)
                        VALUES(?, ?, ?, ?, ?)
                        """,
                        (
                            payload["event_id"],
                            payload["ts"],
                            payload["direction"],
                            payload["track_id"],
                            json.dumps(payload),
                        ),
                    )
            self.backlog.latest_write_ts = utc_now()
            if self.queue.empty():
                self.backlog.oldest_item_ts = None
            self._prune()

    def _prune(self) -> None:
        cutoff = isoformat(utc_now() - timedelta(days=self.retention_days))
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute("DELETE FROM snapshots WHERE ts < ?", (cutoff,))
            conn.execute("DELETE FROM crossing_events WHERE ts < ?", (cutoff,))
            conn.execute("DELETE FROM validation_sessions WHERE saved_at < ?", (cutoff,))
