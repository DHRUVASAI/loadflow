from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

try:
    import boto3
except Exception:
    boto3 = None

try:
    import config
except Exception:
    config = None


def _get_s3_client():
    if config is None or boto3 is None:
        return None
    if getattr(config, "DEMO_MODE", True):
        return None
    if not (getattr(config, "AWS_ACCESS_KEY", None) and getattr(config, "AWS_SECRET_KEY", None)):
        return None
    try:
        return boto3.client(
            "s3",
            region_name=getattr(config, "AWS_REGION", "us-east-1"),
            aws_access_key_id=config.AWS_ACCESS_KEY,
            aws_secret_access_key=config.AWS_SECRET_KEY,
        )
    except Exception:
        return None


def log_request(
    *,
    algorithm: str,
    server_id: str,
    server_name: str,
    response_time: int,
    status: str,
    timestamp: Optional[str] = None,
) -> bool:
    """
    Write a single request log entry to S3.
    Key pattern: logs/YYYY/MM/DD/<timestamp>_<server_id>.json
    Returns True on success, False on failure/demo mode.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()

    log_entry = {
        "timestamp": timestamp,
        "algorithm": algorithm,
        "server_id": server_id,
        "server_name": server_name,
        "response_time_ms": response_time,
        "status": status,
    }

    s3 = _get_s3_client()
    if s3 is None:
        # Demo mode — just print so developer can see it would have logged.
        return False

    bucket = getattr(config, "S3_BUCKET", "load-balancer-logs")
    # Build a dated key so logs are easy to query.
    date_prefix = timestamp[:10].replace("-", "/")   # e.g. 2025/01/15
    safe_ts = timestamp.replace(":", "-").replace("+", "")[:23]
    key = f"logs/{date_prefix}/{safe_ts}_{server_id}.json"

    try:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(log_entry).encode("utf-8"),
            ContentType="application/json",
        )
        return True
    except Exception:
        return False


def upload_history_csv(csv_bytes: bytes, filename: str = "history.csv") -> bool:
    """
    Upload a full history CSV dump to S3.
    Key: exports/<filename>
    """
    s3 = _get_s3_client()
    if s3 is None:
        return False

    bucket = getattr(config, "S3_BUCKET", "load-balancer-logs")
    key = f"exports/{filename}"

    try:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=csv_bytes,
            ContentType="text/csv",
        )
        return True
    except Exception:
        return False
