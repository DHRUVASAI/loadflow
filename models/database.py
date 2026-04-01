from __future__ import annotations

import csv
import io
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import config  # type: ignore
except Exception:  # pragma: no cover
    config = None


def _db_path() -> str:
    if config is not None and getattr(config, "DATABASE_PATH", None):
        return os.path.abspath(str(config.DATABASE_PATH))
    return os.path.abspath("database.db")


def init_db() -> None:
    """
    Creates the `requests` table if it does not exist.
    """
    path = _db_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                algorithm TEXT NOT NULL,
                server_id TEXT NOT NULL,
                server_name TEXT NOT NULL,
                response_time INTEGER NOT NULL,
                status TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def insert_request(data: Dict[str, Any]) -> int:
    """
    Inserts one record into the requests table.
    Expected keys:
      timestamp, algorithm, server_id, server_name, response_time, status
    """
    path = _db_path()
    conn = sqlite3.connect(path)
    try:
        timestamp = data.get("timestamp") or datetime.utcnow().isoformat()
        algorithm = str(data.get("algorithm") or "")
        server_id = str(data.get("server_id") or "")
        server_name = str(data.get("server_name") or "")
        response_time = int(data.get("response_time") or 0)
        status = str(data.get("status") or "")

        cur = conn.execute(
            """
            INSERT INTO requests (
                timestamp, algorithm, server_id, server_name, response_time, status
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (timestamp, algorithm, server_id, server_name, response_time, status),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "timestamp": row["timestamp"],
        "algorithm": row["algorithm"],
        "server_id": row["server_id"],
        "server_name": row["server_name"],
        "response_time": int(row["response_time"]),
        "status": row["status"],
    }


def get_all_requests() -> List[Dict[str, Any]]:
    """
    Returns all records as a list of dicts.
    """
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, timestamp, algorithm, server_id, server_name, response_time, status
            FROM requests
            ORDER BY id DESC
            """
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_requests_by_algorithm(algo: str) -> List[Dict[str, Any]]:
    """
    Filter records by algorithm name.
    """
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, timestamp, algorithm, server_id, server_name, response_time, status
            FROM requests
            WHERE algorithm = ?
            ORDER BY id DESC
            """,
            (algo,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def export_to_csv() -> str:
    """
    Returns CSV string of all records.
    """
    history = get_all_requests()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["id", "timestamp", "algorithm", "server_id", "server_name", "response_time", "status"]
    )
    # history is returned newest-first; reverse for chronological.
    for r in reversed(history):
        writer.writerow(
            [
                r["id"],
                r["timestamp"],
                r["algorithm"],
                r["server_id"],
                r["server_name"],
                r["response_time"],
                r["status"],
            ]
        )
    return output.getvalue()


def clear_history() -> None:
    """
    Deletes all records.
    """
    conn = sqlite3.connect(_db_path())
    try:
        conn.execute("DELETE FROM requests")
        conn.commit()
    finally:
        conn.close()

