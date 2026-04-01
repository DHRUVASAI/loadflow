from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

try:
    import boto3  # type: ignore
except Exception:  # pragma: no cover
    boto3 = None

try:
    import config  # type: ignore
except Exception:  # pragma: no cover
    config = None


def _get_cloudwatch_client():
    if config is None:
        return None
    if getattr(config, "DEMO_MODE", True):
        return None
    if boto3 is None:
        return None
    if not (getattr(config, "AWS_ACCESS_KEY", None) and getattr(config, "AWS_SECRET_KEY", None)):
        return None
    try:
        return boto3.client(
            "cloudwatch",
            region_name=getattr(config, "AWS_REGION", "us-east-1"),
            aws_access_key_id=getattr(config, "AWS_ACCESS_KEY", None),
            aws_secret_access_key=getattr(config, "AWS_SECRET_KEY", None),
        )
    except Exception:
        return None


def _fake_cpu(instance_id: str) -> List[float]:
    return [random.randint(5, 95) for _ in range(10)]


def _fake_network(instance_id: str) -> Dict[str, List[float]]:
    # Bytes/sec-ish simulated values.
    return {
        "network_in": [random.randint(0, 2_000_000) for _ in range(10)],
        "network_out": [random.randint(0, 2_000_000) for _ in range(10)],
    }


def get_cpu_metrics(instance_id: str) -> List[float]:
    """
    Returns last 10 CPU datapoints (Average) for an EC2 instance.
    """
    try:
        cw = _get_cloudwatch_client()
        if cw is None:
            return _fake_cpu(instance_id)

        now = datetime.now(timezone.utc)
        period_seconds = 300  # 5 minutes
        end_time = now
        start_time = now - timedelta(seconds=period_seconds * 10)

        resp = cw.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[
                {"Name": "InstanceId", "Value": instance_id},
            ],
            StartTime=start_time,
            EndTime=end_time,
            Period=period_seconds,
            Statistics=["Average"],
        )

        datapoints = resp.get("Datapoints", []) or []
        datapoints_sorted = sorted(datapoints, key=lambda d: d.get("Timestamp"))
        last = datapoints_sorted[-10:]
        series: List[float] = []
        for d in last:
            v = d.get("Average")
            try:
                series.append(float(v))
            except Exception:
                pass
        if len(series) < 10:
            # Pad with the last value if sparse.
            while len(series) < 10:
                series.append(float(series[-1]) if series else random.randint(5, 95))
        return series[-10:]
    except Exception:
        return _fake_cpu(instance_id)


def get_network_metrics(instance_id: str) -> Dict[str, List[float]]:
    """
    Returns simulated network in/out datapoints.
    """
    try:
        cw = _get_cloudwatch_client()
        if cw is None:
            return _fake_network(instance_id)

        now = datetime.now(timezone.utc)
        period_seconds = 300  # 5 minutes
        end_time = now
        start_time = now - timedelta(seconds=period_seconds * 10)

        def _get_metric(metric_name: str) -> List[float]:
            resp = cw.get_metric_statistics(
                Namespace="AWS/EC2",
                MetricName=metric_name,
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=period_seconds,
                Statistics=["Sum"],
            )
            datapoints = resp.get("Datapoints", []) or []
            datapoints_sorted = sorted(datapoints, key=lambda d: d.get("Timestamp"))
            last = datapoints_sorted[-10:]
            series: List[float] = []
            for d in last:
                v = d.get("Sum")
                try:
                    series.append(float(v))
                except Exception:
                    pass
            if len(series) < 10:
                while len(series) < 10:
                    series.append(float(series[-1]) if series else random.randint(0, 2_000_000))
            return series[-10:]

        return {
            "network_in": _get_metric("NetworkIn"),
            "network_out": _get_metric("NetworkOut"),
        }
    except Exception:
        return _fake_network(instance_id)


def get_all_metrics(instance_id: str) -> Dict[str, Any]:
    """
    Returns dict with cpu, network, timestamp.
    """
    try:
        cpu = get_cpu_metrics(instance_id)
        network = get_network_metrics(instance_id)
        ts = datetime.now(timezone.utc).isoformat()
        return {"cpu": cpu, "network": network, "timestamp": ts}
    except Exception:
        return {
            "cpu": _fake_cpu(instance_id),
            "network": _fake_network(instance_id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

