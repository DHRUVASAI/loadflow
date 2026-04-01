from __future__ import annotations

import csv
import io
import json
import os
import random
import sqlite3
import time
import uuid
from datetime import datetime, timezone

from flask import Blueprint, Flask, Response, jsonify, render_template, request, session, redirect, url_for

import config

try:
    from flask_cors import CORS
except Exception:
    CORS = None

try:
    from flask_session import Session
except Exception:
    Session = None

try:
    import boto3
except Exception:
    boto3 = None

try:
    from aws.ec2_manager import get_all_servers as aws_get_all_servers
    from aws.ec2_manager import start_server as aws_start_server
    from aws.ec2_manager import stop_server as aws_stop_server
    from aws.ec2_manager import deploy_server as aws_deploy_server
except Exception:
    aws_get_all_servers = None
    aws_start_server = None
    aws_stop_server = None
    aws_deploy_server = None

try:
    from aws.s3_logger import log_request as s3_log_request
except Exception:
    s3_log_request = None

try:
    from aws.cloudwatch import get_cpu_metrics, get_all_metrics
except Exception:
    get_cpu_metrics = None
    get_all_metrics = None


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__)

_fallback_secret = os.getenv("FLASK_SECRET_KEY")
app.secret_key = config.AWS_SECRET_KEY or _fallback_secret or os.urandom(32)

if CORS is not None:
    CORS(app)

if Session is not None:
    app.config["SESSION_TYPE"] = "filesystem"
    app.config["SESSION_PERMANENT"] = False
    Session(app)

balancer_bp = Blueprint("balancer", __name__)
aws_bp = Blueprint("aws", __name__)
history_bp = Blueprint("history", __name__)

app.register_blueprint(balancer_bp)
app.register_blueprint(aws_bp)
app.register_blueprint(history_bp)

DB_PATH = os.path.abspath(config.DATABASE_PATH)
SERVER_TAGS = list(config.EC2_INSTANCE_TAGS)

ALGORITHMS = {
    "round_robin": "Round Robin",
    "least_connections": "Least Connections",
    "weighted": "Weighted",
}

# ---------------------------------------------------------------------------
# In-memory server state
# Keys are server IDs (stable: "i-1", "i-2", "i-3" in demo; real IDs in live).
# ---------------------------------------------------------------------------

servers_state: dict = {}

# Canonical demo server IDs so state is always found.
_DEMO_IDS = ["i-1", "i-2", "i-3"]
_DEMO_NAMES = ["lb-server-1", "lb-server-2", "lb-server-3"]

# Map name → id for demo (used when AWS returns real instance IDs).
_name_to_demo_id: dict = {
    "lb-server-1": "i-1",
    "lb-server-2": "i-2",
    "lb-server-3": "i-3",
}

# Dynamic scaling: custom servers added at runtime.
_custom_servers: list = []
_next_server_num: int = 4  # starts at 4 since we already have 1-3


def _ensure_server_state(server_id: str) -> None:
    if server_id not in servers_state:
        servers_state[server_id] = {"requests_handled": 0, "connections": 0, "status": "running"}


# Initialise demo IDs upfront.
for _did in _DEMO_IDS:
    _ensure_server_state(_did)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(value: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(value)))


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Global State for Traffic & Algorithms
# ---------------------------------------------------------------------------

_global_algo_state = {
    "algorithm": "round_robin",
    "rr_index": 0,
    "weighted_index": 0,
    "traffic_running": False
}

def _get_active_algorithm_key() -> str:
    from flask import has_request_context
    if has_request_context() and session.get("algorithm"):
        algo = session.get("algorithm")
        if algo in ALGORITHMS:
            return algo
    return _global_algo_state["algorithm"]


def _is_server_eligible(server: dict) -> bool:
    status = str(server.get("status", "running")).strip().lower()
    health = str(server.get("health", "healthy")).strip().lower()
    return status == "running" and health != "critical"


def _merge_servers_with_state(servers: list, *, last_refreshed: str, avg_response_time: float) -> list:
    """
    Merge in-memory counters into server dicts returned by ec2_manager.
    The key insight: demo servers use ids "i-1".."i-3"; we also accept
    a name-based fallback so real EC2 instances map correctly.
    """
    merged = []
    for s in servers:
        raw_id = str(s.get("id") or s.get("name") or "")
        name = str(s.get("name") or raw_id)

        # Resolve canonical state key: prefer real id; fall back to demo id via name.
        state_key = raw_id
        if state_key not in servers_state:
            # Try name-based lookup (demo fallback).
            state_key = _name_to_demo_id.get(name, raw_id)

        _ensure_server_state(state_key)

        cpu = float(s.get("cpu_percent") or 0)
        response_time = float(s.get("response_time") or random.uniform(50, 300))

        health = s.get("health")
        if not health:
            health = "healthy" if cpu < 60 else ("warning" if cpu <= 80 else "critical")

        state = servers_state[state_key]
        out = dict(s)
        out["id"] = raw_id
        out["_state_key"] = state_key          # used internally for updates
        out["connections"] = _clamp(state.get("connections", 0), 0, 20)
        out["requests_handled"] = int(state.get("requests_handled", 0))
        out["cpu_percent"] = cpu
        out["response_time"] = response_time
        out["health"] = str(health)
        out["weight"] = int(s.get("weight", 1) or 1)
        out["last_refreshed"] = last_refreshed
        out["avg_response_time"] = float(avg_response_time)
        merged.append(out)
    return merged


def _apply_request_to_state(state_key: str) -> None:
    """
    Increment requests_handled; simulate connection churn.
    state_key must be the key present in servers_state.
    """
    _ensure_server_state(state_key)

    # Small random decay on all servers (simulates completed requests).
    for sid in servers_state:
        servers_state[sid]["connections"] = max(
            0, int(servers_state[sid].get("connections", 0)) - random.randint(0, 1)
        )

    servers_state[state_key]["requests_handled"] = (
        int(servers_state[state_key].get("requests_handled", 0)) + 1
    )
    servers_state[state_key]["connections"] = _clamp(
        int(servers_state[state_key].get("connections", 0)) + random.randint(1, 2),
        0, 20,
    )


def _select_server(servers: list, algo_key: str) -> dict:
    """
    Choose a server from the merged list using the specified algorithm.
    Updates the relevant session index in-place.
    """
    eligible = [s for s in servers if _is_server_eligible(s)]
    if not eligible:
        eligible = [s for s in servers if str(s.get("status", "running")).strip().lower() == "running"]
    if not eligible:
        raise RuntimeError("No eligible servers available")

    eligible_sorted = sorted(eligible, key=lambda s: str(s.get("name") or s.get("id") or ""))

    if algo_key == "round_robin":
        idx = int(_global_algo_state["rr_index"])
        chosen = eligible_sorted[idx % len(eligible_sorted)]
        _global_algo_state["rr_index"] = idx + 1
        return chosen

    if algo_key == "least_connections":
        min_conn = min(int(s.get("connections", 0) or 0) for s in eligible_sorted)
        candidates = [s for s in eligible_sorted if int(s.get("connections", 0) or 0) == min_conn]
        # Tie-break deterministically via name sort (already sorted).
        return candidates[0]

    if algo_key == "weighted":
        slots: list = []
        for s in eligible_sorted:
            w = max(1, min(5, int(s.get("weight", 1) or 1)))
            slots.extend([s] * w)
        idx = int(_global_algo_state["weighted_index"])
        chosen = slots[idx % len(slots)]
        _global_algo_state["weighted_index"] = idx + 1
        return chosen

    return eligible_sorted[0]


def _select_server_no_mutate(servers: list, algo_key: str, session_snapshot: dict) -> dict:
    """
    Like _select_server but reads from session_snapshot instead of the real session.
    Used by /api/compare so live session indexes are not advanced.
    """
    eligible = [s for s in servers if _is_server_eligible(s)]
    if not eligible:
        eligible = [s for s in servers if str(s.get("status", "running")).strip().lower() == "running"]
    if not eligible:
        raise RuntimeError("No eligible servers")

    eligible_sorted = sorted(eligible, key=lambda s: str(s.get("name") or s.get("id") or ""))

    if algo_key == "round_robin":
        idx = int(session_snapshot.get("rr_index", 0))
        return eligible_sorted[idx % len(eligible_sorted)]

    if algo_key == "least_connections":
        min_conn = min(int(s.get("connections", 0) or 0) for s in eligible_sorted)
        candidates = [s for s in eligible_sorted if int(s.get("connections", 0) or 0) == min_conn]
        return candidates[0]

    if algo_key == "weighted":
        slots: list = []
        for s in eligible_sorted:
            w = max(1, min(5, int(s.get("weight", 1) or 1)))
            slots.extend([s] * w)
        idx = int(session_snapshot.get("weighted_index", 0))
        return slots[idx % len(slots)]

    return eligible_sorted[0]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS server_loads (
                server_name TEXT PRIMARY KEY,
                load INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                request_no INTEGER NOT NULL,
                algorithm TEXT NOT NULL,
                server_name TEXT NOT NULL,
                load_before INTEGER NOT NULL,
                load_after INTEGER NOT NULL,
                simulated_latency_ms INTEGER NOT NULL,
                simulated_ok INTEGER NOT NULL
            );
            """
        )
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
        for name in SERVER_TAGS:
            row = conn.execute(
                "SELECT server_name FROM server_loads WHERE server_name = ?", (name,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO server_loads (server_name, load, updated_at) VALUES (?, ?, ?)",
                    (name, random.randint(5, 20), _utc_iso_now()),
                )
        conn.commit()
    finally:
        conn.close()


init_db()


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _get_avg_response_time_last_10(conn: sqlite3.Connection) -> float:
    try:
        rows = conn.execute(
            "SELECT response_time FROM requests ORDER BY id DESC LIMIT 10"
        ).fetchall()
        vals = [float(r[0]) for r in rows if r and r[0] is not None]
        return round(sum(vals) / len(vals), 1) if vals else 0.0
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Server snapshot helper (used by multiple routes)
# ---------------------------------------------------------------------------

def _get_fallback_servers(last_refreshed: str) -> list:
    def get_status(sid):
        return servers_state.get(sid, {}).get("status", "running")

    base = [
        {"id": "i-1", "name": "lb-server-1", "ip": "54.1.1.1", "status": get_status("i-1"),
         "instance_type": "t3.micro", "launch_time": last_refreshed,
         "cpu_percent": random.uniform(20, 75), "response_time": random.uniform(50, 300),
         "health": "healthy", "weight": 1},
        {"id": "i-2", "name": "lb-server-2", "ip": "54.1.1.2", "status": get_status("i-2"),
         "instance_type": "t3.micro", "launch_time": last_refreshed,
         "cpu_percent": random.uniform(20, 75), "response_time": random.uniform(50, 300),
         "health": "healthy", "weight": 2},
        {"id": "i-3", "name": "lb-server-3", "ip": "54.1.1.3", "status": get_status("i-3"),
         "instance_type": "t3.micro", "launch_time": last_refreshed,
         "cpu_percent": random.uniform(20, 75), "response_time": random.uniform(50, 300),
         "health": "healthy", "weight": 3},
    ]
    # Append any dynamically deployed servers.
    for cs in _custom_servers:
        cs_copy = dict(cs)
        cs_copy["status"] = get_status(cs["id"])
        base.append(cs_copy)
    return base


def _get_merged_servers(conn: sqlite3.Connection) -> tuple[list, str, float]:
    """
    Returns (merged_servers, last_refreshed, avg_response_time).
    Single source of truth for all routes that need a server list.
    """
    last_refreshed = _utc_iso_now()
    avg_response_time = _get_avg_response_time_last_10(conn)

    raw_servers = []
    if aws_get_all_servers is not None:
        try:
            raw_servers = aws_get_all_servers() or []
        except Exception:
            raw_servers = []

    if not raw_servers:
        raw_servers = _get_fallback_servers(last_refreshed)

    merged = _merge_servers_with_state(
        raw_servers,
        last_refreshed=last_refreshed,
        avg_response_time=avg_response_time,
    )
    return merged, last_refreshed, avg_response_time


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def landing():
    return render_template("landing.html")

@app.route("/dashboard", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/Dashboard", methods=["GET"])
def dashboard_alias():
    return redirect(url_for("index"))

@app.route("/servers", methods=["GET"])
def servers_page():
    return render_template("servers.html")

@app.route("/Servers", methods=["GET"])
def servers_alias():
    return redirect(url_for("servers_page"))

@app.route("/compare", methods=["GET"])
def compare_page():
    return render_template("compare.html")

@app.route("/Compare", methods=["GET"])
def compare_alias():
    return redirect(url_for("compare_page"))

@app.route("/history", methods=["GET"])
def history_page():
    return render_template("history.html")

@app.route("/History", methods=["GET"])
def history_alias():
    return redirect(url_for("history_page"))

@app.route("/test-js", methods=["GET"])
def test_js():
    return render_template("test_js.html")

@app.route("/debug", methods=["GET"])
def debug_dashboard():
    return render_template("index_debug.html")

@app.route("/connectivity-test", methods=["GET"])
def connectivity_test():
    return render_template("connectivity_test.html")


# ---------------------------------------------------------------------------
# API: Servers
# ---------------------------------------------------------------------------

@app.route("/api/servers", methods=["GET"])
def api_servers():
    conn = get_db()
    try:
        merged, _, avg_rt = _get_merged_servers(conn)
        # Strip internal key before sending to frontend.
        for s in merged:
            s.pop("_state_key", None)
        # Return as object with 'servers' property for frontend compatibility
        return jsonify({"servers": merged})
    finally:
        conn.close()


@app.route("/api/servers/<server_id>/start", methods=["POST"])
def api_server_start(server_id: str):
    """Start an EC2 instance (or no-op in demo mode)."""
    try:
        if aws_start_server is not None and not getattr(config, "DEMO_MODE", True):
            aws_start_server(server_id)

        # Optimistically update in-memory state so UI reflects change immediately.
        _ensure_server_state(server_id)
        servers_state[server_id]["status"] = "running"
        conn = get_db()
        try:
            merged, _, _ = _get_merged_servers(conn)
            for s in merged:
                s.pop("_state_key", None)
            return jsonify({"success": True, "servers": merged})
        finally:
            conn.close()
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/servers/<server_id>/stop", methods=["POST"])
def api_server_stop(server_id: str):
    """Stop an EC2 instance (or no-op in demo mode)."""
    try:
        if aws_stop_server is not None and not getattr(config, "DEMO_MODE", True):
            aws_stop_server(server_id)

        _ensure_server_state(server_id)
        servers_state[server_id]["status"] = "stopped"

        conn = get_db()
        try:
            merged, _, _ = _get_merged_servers(conn)
            for s in merged:
                s.pop("_state_key", None)
            return jsonify({"success": True, "servers": merged})
        finally:
            conn.close()
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/servers/add", methods=["POST"])
def api_add_server():
    """Deploy a new virtual server for dynamic scaling."""
    global _next_server_num
    try:
        num = _next_server_num
        _next_server_num += 1
        server_id = f"i-{num}"
        server_name = f"lb-server-{num}"
        ip = f"54.1.1.{num}"

        _DEMO_IDS.append(server_id)
        _DEMO_NAMES.append(server_name)
        _name_to_demo_id[server_name] = server_id

        _ensure_server_state(server_id)

        new_server = {
            "id": server_id,
            "name": server_name,
            "ip": ip,
            "status": "running",
            "instance_type": "t3.micro",
            "launch_time": _utc_iso_now(),
            "cpu_percent": random.uniform(5, 25),
            "response_time": random.uniform(30, 120),
            "health": "healthy",
            "weight": 1,
        }
        _custom_servers.append(new_server)

        return jsonify({"success": True, "server": {"id": server_id, "name": server_name}})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/servers/<server_id>/remove", methods=["POST"])
def api_remove_server(server_id: str):
    """Remove a dynamically deployed server."""
    global _custom_servers
    try:
        _custom_servers = [s for s in _custom_servers if s.get("id") != server_id]
        if server_id in servers_state:
            del servers_state[server_id]
        # Clean up name mappings
        name_to_remove = None
        for name, sid in _name_to_demo_id.items():
            if sid == server_id:
                name_to_remove = name
                break
        if name_to_remove:
            del _name_to_demo_id[name_to_remove]
        if server_id in _DEMO_IDS:
            _DEMO_IDS.remove(server_id)
        if name_to_remove and name_to_remove in _DEMO_NAMES:
            _DEMO_NAMES.remove(name_to_remove)
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/servers/deploy", methods=["POST"])
def api_deploy_server():
    """Provision a real EC2 t2.micro instance (or return a fake one in DEMO_MODE)."""
    try:
        if not getattr(config, "DEMO_MODE", True) and aws_deploy_server is not None:
            # --- Live mode: call AWS ------------------------------------------
            server = aws_deploy_server()
            if server is None:
                return jsonify({"success": False, "error": "EC2 deployment failed"}), 500

            # Register the new instance in in-memory state so it participates
            # in request routing immediately.
            _ensure_server_state(server["id"])
            _DEMO_IDS.append(server["id"])
            _DEMO_NAMES.append(server["name"])
            _name_to_demo_id[server["name"]] = server["id"]
            _custom_servers.append(server)

            return jsonify({"success": True, "server": server})

        else:
            # --- Demo mode: synthesise a fake server --------------------------
            suffix = "".join(
                random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=4)
            )
            server_id = f"i-demo-{suffix}"
            server_name = f"lb-server-{suffix}"
            fake_server = {
                "id": server_id,
                "name": server_name,
                "ip": f"54.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}",
                "status": "running",
                "instance_type": "t2.micro",
                "launch_time": _utc_iso_now(),
                "cpu_percent": random.uniform(5, 25),
                "response_time": random.uniform(30, 120),
                "health": "healthy",
                "weight": 1,
                "connections": 0,
                "requests_handled": 0,
                "demo": True,
            }

            _ensure_server_state(server_id)
            _DEMO_IDS.append(server_id)
            _DEMO_NAMES.append(server_name)
            _name_to_demo_id[server_name] = server_id
            _custom_servers.append(fake_server)

            return jsonify({"success": True, "server": fake_server})

    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/servers/<server_id>/metrics", methods=["GET"])
def api_server_metrics(server_id: str):
    """Return flat metrics format compatible with frontend metrics alert."""
    try:
        state = servers_state.get(server_id, {})
        return jsonify({
            "request_count": state.get("requests_handled", 0),
            "active_connections": state.get("connections", 0),
            "avg_response_time": int(random.uniform(50, 300)),
            "cpu_usage": int(random.uniform(20, 80))
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# API: Send Request / Auto Send
# ---------------------------------------------------------------------------

@app.route("/api/send-request", methods=["POST"])
def api_send_request():
    conn = get_db()
    try:
        algo_key = _get_active_algorithm_key()
        merged, _, avg_rt = _get_merged_servers(conn)

        chosen = _select_server(merged, algo_key)

        # Use _state_key (not raw id) so demo servers always resolve.
        state_key = chosen.get("_state_key") or str(chosen.get("id") or chosen.get("name"))
        server_name = chosen.get("name") or chosen.get("server_name") or state_key
        server_id = str(chosen.get("id") or state_key)

        response_time_ms = int(random.uniform(50, 300))
        timestamp = _utc_iso_now()
        status = str(chosen.get("health") or "healthy")

        # Update in-memory counters with the correct state key.
        _apply_request_to_state(state_key)

        # Persist to SQLite.
        conn.execute(
            "INSERT INTO requests (timestamp, algorithm, server_id, server_name, response_time, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, algo_key, server_id, server_name, response_time_ms, status),
        )
        conn.commit()

        # S3 logging (non-blocking).
        if s3_log_request is not None:
            try:
                s3_log_request(
                    algorithm=algo_key,
                    server_id=server_id,
                    server_name=server_name,
                    response_time=response_time_ms,
                    status=status,
                    timestamp=timestamp,
                )
            except Exception:
                pass

        new_avg_rt = _get_avg_response_time_last_10(conn)

        return jsonify(
            {
                "server_name": server_name,
                "server_id": server_id,
                "response_time": response_time_ms,
                "algorithm": algo_key,
                "timestamp": timestamp,
                "status": status,
                "avg_response_time": new_avg_rt,
                "requests_handled": int(servers_state[state_key]["requests_handled"]),
                "connections": int(servers_state[state_key]["connections"]),
                # Legacy compat field some UI versions read.
                "results": [
                    {
                        "server_name": server_name,
                        "response_time": response_time_ms,
                        "algorithm": algo_key,
                        "timestamp": timestamp,
                        "simulated_latency_ms": response_time_ms,
                        "simulated_ok": status != "critical",
                    }
                ],
            }
        )
    finally:
        conn.close()


@app.route("/api/auto-send/<int:count>", methods=["POST"])
def api_auto_send(count: int):
    if count < 1:
        return jsonify({"error": "count must be >= 1"}), 400
    if count > 500:
        return jsonify({"error": "count must be <= 500"}), 400

    conn = get_db()
    try:
        algo_key = _get_active_algorithm_key()
        per_server_counts: dict = {}
        response_times: list = []
        results = []

        for i in range(count):
            # Re-fetch merged snapshot each iteration so connections are current.
            merged, _, _ = _get_merged_servers(conn)

            chosen = _select_server(merged, algo_key)
            state_key = chosen.get("_state_key") or str(chosen.get("id") or chosen.get("name"))
            server_name = chosen.get("name") or chosen.get("server_name") or state_key
            server_id = str(chosen.get("id") or state_key)

            response_time_ms = int(random.uniform(50, 300))
            timestamp = _utc_iso_now()
            status = str(chosen.get("health") or "healthy")

            _apply_request_to_state(state_key)

            conn.execute(
                "INSERT INTO requests (timestamp, algorithm, server_id, server_name, response_time, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (timestamp, algo_key, server_id, server_name, response_time_ms, status),
            )

            per_server_counts[server_name] = per_server_counts.get(server_name, 0) + 1
            response_times.append(float(response_time_ms))

            results.append(
                {
                    "request_no": i + 1,
                    "server_name": server_name,
                    "response_time": response_time_ms,
                    "algorithm": algo_key,
                    "timestamp": timestamp,
                    "status": status,
                }
            )

            # S3 log (non-blocking).
            if s3_log_request is not None:
                try:
                    s3_log_request(
                        algorithm=algo_key,
                        server_id=server_id,
                        server_name=server_name,
                        response_time=response_time_ms,
                        status=status,
                        timestamp=timestamp,
                    )
                except Exception:
                    pass

            time.sleep(0.005)   # small delay; 5ms keeps 100-req batch under 0.5s

        conn.commit()
        avg_rt = round(sum(response_times) / len(response_times), 1) if response_times else 0.0

        return jsonify(
            {
                "total": count,
                "algorithm": algo_key,
                "per_server_counts": per_server_counts,
                "avg_response_time": avg_rt,
                "results": results,
            }
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API: Global Traffic Toggle
# ---------------------------------------------------------------------------

import threading
import time

def _background_traffic_worker():
    while True:
        if _global_algo_state["traffic_running"]:
            try:
                # Simulate a burst of 5 requests rapidly
                conn = get_db()
                try:
                    algo_key = _get_active_algorithm_key()
                    for _ in range(5):
                        merged, _, _ = _get_merged_servers(conn)
                        chosen = _select_server(merged, algo_key)
                        state_key = chosen.get("_state_key") or str(chosen.get("id") or chosen.get("name"))
                        server_name = chosen.get("name") or chosen.get("server_name") or state_key
                        server_id = str(chosen.get("id") or state_key)

                        response_time_ms = int(random.uniform(50, 300))
                        timestamp = _utc_iso_now()
                        status = str(chosen.get("health") or "healthy")

                        _apply_request_to_state(state_key)

                        conn.execute(
                            "INSERT INTO requests (timestamp, algorithm, server_id, server_name, response_time, status) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (timestamp, algo_key, server_id, server_name, response_time_ms, status),
                        )
                    conn.commit()
                finally:
                    conn.close()
            except Exception as e:
                pass
        time.sleep(1)

# Start global background thread once
threading.Thread(target=_background_traffic_worker, daemon=True).start()


@app.route("/api/toggle-traffic", methods=["POST"])
def api_toggle_traffic():
    _global_algo_state["traffic_running"] = not _global_algo_state["traffic_running"]
    return jsonify({"running": _global_algo_state["traffic_running"]})

@app.route("/api/traffic-status", methods=["GET"])
def api_traffic_status():
    return jsonify({"running": _global_algo_state["traffic_running"]})


# ---------------------------------------------------------------------------
# API: Algorithm
# ---------------------------------------------------------------------------


@app.route("/api/set-algorithm", methods=["POST"])
def api_set_algorithm():
    data = request.get_json(silent=True) or {}
    algo = data.get("algorithm")
    if algo not in ALGORITHMS:
        return jsonify({"error": "Invalid algorithm"}), 400
    session["algorithm"] = algo
    _global_algo_state["algorithm"] = algo
    # Reset algorithm-specific cursors so new algorithm starts cleanly.
    session["rr_index"] = 0
    session["weighted_index"] = 0
    _global_algo_state["rr_index"] = 0
    _global_algo_state["weighted_index"] = 0
    return jsonify({"algorithm": algo, "display_name": ALGORITHMS[algo]})


# ---------------------------------------------------------------------------
# API: Compare  (FIX: use snapshot so session is never mutated)
# ---------------------------------------------------------------------------

@app.route("/api/compare", methods=["GET"])
def api_compare():
    conn = get_db()
    try:
        merged, _, avg_rt = _get_merged_servers(conn)

        # Snapshot current session indexes — we will NOT advance them.
        session_snapshot = {
            "rr_index": session.get("rr_index", 0),
            "least_index": session.get("least_index", 0),
            "weighted_index": session.get("weighted_index", 0),
        }

        predictions: dict = {}
        for algo_key in ALGORITHMS:
            chosen = _select_server_no_mutate(list(merged), algo_key, session_snapshot)

            current_connections = int(chosen.get("connections", 0) or 0)
            predicted_connections = _clamp(current_connections + random.randint(1, 2), 0, 20)
            response_time_ms = int(random.uniform(50, 300))
            status = str(chosen.get("health") or "healthy")
            cpu = float(chosen.get("cpu_percent") or 0)

            # Generate a mock distribution array for the radar charts
            base = int(chosen.get("requests_handled", 0) / 3)
            v = random.randint(1, max(2, int(base * 0.2))) if base > 0 else 1
            dist = [max(0, base + random.randint(-v, v)) for _ in range(3)]

            predictions[algo_key] = {
                "server_name": chosen.get("name") or chosen.get("id"),
                "load_before": current_connections,
                "load_after": predicted_connections,
                "simulated_latency_ms": response_time_ms,
                "simulated_ok": status != "critical",
                "cpu_percent": cpu,
                "total_requests": int(chosen.get("requests_handled", 0)),
                "display_name": ALGORITHMS[algo_key],
                "algorithm": algo_key,
                "avg_response_time": response_time_ms,
                "distribution": dist,
                "min_response_time": int(response_time_ms * 0.8),
                "max_response_time": int(response_time_ms * 1.2),
            }

        return jsonify(
            {
                "active_algorithm": _get_active_algorithm_key(),
                "threshold": int(config.OVERLOAD_THRESHOLD),
                "avg_response_time": avg_rt,
                "predictions": predictions,
                "comparison": list(predictions.values()),  # Add for frontend compatibility
            }
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API: History  (FIX: pagination + filtering)
# ---------------------------------------------------------------------------

@app.route("/api/history", methods=["GET"])
def api_history():
    conn = get_db()
    try:
        algo   = request.args.get("algorithm", "all")
        server = request.args.get("server", "all")
        page   = max(1, int(request.args.get("page", 1)))
        per_page = max(1, min(200, int(request.args.get("per_page", 20))))

        # Build WHERE clause dynamically.
        conditions = []
        params: list = []
        if algo and algo != "all":
            conditions.append("algorithm = ?")
            params.append(algo)
        if server and server != "all":
            conditions.append("server_name = ?")
            params.append(server)

        where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        total = conn.execute(
            f"SELECT COUNT(*) FROM requests {where_sql}", params
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"""
            SELECT id, timestamp, algorithm, server_id, server_name, response_time, status
            FROM requests {where_sql}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            params + [per_page, offset],
        ).fetchall()

        history = [
            {
                "id": int(r["id"]),
                "timestamp": r["timestamp"],
                "created_at": r["timestamp"],
                "algorithm": r["algorithm"],
                "server_id": r["server_id"],
                "server_name": r["server_name"],
                "response_time": int(r["response_time"]),
                "status": r["status"],
            }
            for r in rows
        ]

        return jsonify(
            {
                "data": history,
                "history": history,  # Add for frontend compatibility
                "total": total,
                "page": page,
                "per_page": per_page,
                "pages": max(1, -(-total // per_page)),  # ceiling division
            }
        )
    finally:
        conn.close()


@app.route("/api/export-csv", methods=["GET"])
def api_export_csv():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, timestamp, algorithm, server_id, server_name, response_time, status "
            "FROM requests ORDER BY id ASC"
        ).fetchall()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "timestamp", "algorithm", "server_id", "server_name", "response_time", "status"])
        for r in rows:
            writer.writerow([r["id"], r["timestamp"], r["algorithm"], r["server_id"],
                             r["server_name"], r["response_time"], r["status"]])
        resp = Response(output.getvalue().encode("utf-8"), mimetype="text/csv")
        resp.headers["Content-Disposition"] = 'attachment; filename="history.csv"'
        return resp
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API: Misc
# ---------------------------------------------------------------------------

@app.route("/api/toggle-demo", methods=["POST"])
def api_toggle_demo():
    data = request.get_json(silent=True) or {}
    demo_enabled = bool(data.get("demo", True))
    session["demo_mode"] = demo_enabled
    return jsonify({"demo_mode": demo_enabled})


@app.route("/api/clear-history", methods=["POST"])
def api_clear_history():
    # Stop the live traffic thread FIRST to prevent race condition.
    # The background thread sleeps 1s between bursts; 80ms is enough to let
    # any in-flight INSERT finish before we DELETE.
    _global_algo_state["traffic_running"] = False
    time.sleep(0.08)
    conn = get_db()
    try:
        conn.execute("DELETE FROM requests")
        conn.commit()
        # Reset in-memory server counters.
        for sid in list(servers_state.keys()):
            servers_state[sid]["requests_handled"] = 0
            servers_state[sid]["connections"] = 0
        return jsonify({"cleared": True, "traffic_stopped": True})
    finally:
        conn.close()


@app.route("/api/reset", methods=["POST"])
def api_reset():
    # Stop auto-traffic so counters stay at zero after reset.
    _global_algo_state["traffic_running"] = False
    for sid in list(servers_state.keys()):
        servers_state[sid]["requests_handled"] = 0
        servers_state[sid]["connections"] = 0
    conn = get_db()
    try:
        conn.execute("DELETE FROM requests")
        conn.commit()
        return jsonify({"success": True, "traffic_stopped": True})
    finally:
        conn.close()


@app.route("/api/stats", methods=["GET"])
def api_stats():
    """Summary stats used by the dashboard header cards."""
    conn = get_db()
    try:
        total_requests = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        avg_rt = _get_avg_response_time_last_10(conn)
        # Count only servers whose in-memory status is 'running'.
        all_servers = _get_fallback_servers(_utc_iso_now())
        active_servers = sum(
            1 for s in all_servers
            if str(servers_state.get(s["id"], {}).get("status", "running")).lower() == "running"
        )
        return jsonify(
            {
                "total_requests": int(total_requests),
                "avg_response_time": avg_rt,
                "active_servers": active_servers,
                "total_servers": len(all_servers),
                "algorithm": _get_active_algorithm_key(),
                "algorithm_display": ALGORITHMS.get(_get_active_algorithm_key(), ""),
                "traffic_running": _global_algo_state["traffic_running"],
            }
        )
    finally:
        conn.close()


@app.route("/api/status", methods=["GET"])
def api_status():
    """Return connection mode and AWS config info for the UI status banner."""
    demo_mode = getattr(config, "DEMO_MODE", True)
    region = getattr(config, "AWS_DEFAULT_REGION", None) or getattr(config, "AWS_REGION", "us-east-1")

    account_id = None
    if not demo_mode and boto3 is not None:
        try:
            access_key = getattr(config, "AWS_ACCESS_KEY_ID", None) or getattr(config, "AWS_ACCESS_KEY", None)
            secret_key = getattr(config, "AWS_SECRET_ACCESS_KEY", None) or getattr(config, "AWS_SECRET_KEY", None)
            sts = boto3.client(
                "sts",
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )
            identity = sts.get_caller_identity()
            raw = identity.get("Account", "")
            # Mask: show last 4 digits only — e.g. ****1234
            account_id = ("*" * (len(raw) - 4) + raw[-4:]) if len(raw) > 4 else raw
        except Exception:
            account_id = None

    return jsonify({
        "demo_mode": demo_mode,
        "region": region,
        "account_id": account_id,
        "aws_connected": not demo_mode and account_id is not None,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)