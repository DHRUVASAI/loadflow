from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any, Dict, List

try:
    import boto3  # type: ignore
except Exception:  # pragma: no cover
    boto3 = None

try:
    import config  # type: ignore
except Exception:  # pragma: no cover
    config = None


def _demo_servers() -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    fake = []
    tag_names = getattr(config, "EC2_INSTANCE_TAGS", ["lb-server-1", "lb-server-2", "lb-server-3"])

    # Demo servers are always returned; Flask backend merges in-memory
    # counters (`connections`, `requests_handled`) on every /api/servers call.
    for i in range(1, min(3, len(tag_names)) + 1):
        name = tag_names[i - 1]
        cpu_percent = random.uniform(20, 75)  # as requested
        response_time_ms = random.uniform(50, 300)

        if cpu_percent < 60:
            health = "healthy"
        elif cpu_percent <= 80:
            health = "warning"
        else:
            health = "critical"

        fake.append(
            {
                "id": f"i-{i}",
                "name": name,
                "ip": f"54.123.{i}.10",
                "status": "running",
                "instance_type": random.choice(["t3.micro", "t3.small", "t3.medium"]),
                "launch_time": now,
                # Dynamic metrics
                "cpu_percent": cpu_percent,
                "response_time": response_time_ms,
                "health": health,
                # Weighted round robin uses this (1-5)
                "weight": min(5, i),
                # Placeholders; Flask overrides from in-memory state.
                "connections": 0,
                "requests_handled": 0,
            }
        )

    return fake


def _get_ec2_resource():
    if config is None:
        return None
    if getattr(config, "DEMO_MODE", True):
        return None
    if boto3 is None:
        return None

    # Prefer new standard key names; fall back to legacy aliases.
    access_key = (
        getattr(config, "AWS_ACCESS_KEY_ID", None)
        or getattr(config, "AWS_ACCESS_KEY", None)
    )
    secret_key = (
        getattr(config, "AWS_SECRET_ACCESS_KEY", None)
        or getattr(config, "AWS_SECRET_KEY", None)
    )
    region = (
        getattr(config, "AWS_DEFAULT_REGION", None)
        or getattr(config, "AWS_REGION", "us-east-1")
    )

    if not (access_key and secret_key):
        return None

    try:
        return boto3.resource(
            "ec2",
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
    except Exception:
        return None


def _get_latest_amazon_linux2_ami(region: str, access_key: str, secret_key: str) -> str | None:
    """Use SSM Parameter Store to discover the latest Amazon Linux 2 AMI for the region."""
    try:
        ssm = boto3.client(
            "ssm",
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        response = ssm.get_parameter(
            Name="/aws/service/ami-amazon-linux-latest/amzn2-ami-hvm-x86_64-gp2"
        )
        return response["Parameter"]["Value"]
    except Exception:
        return None

def _deploy_worker(ami_id: str, tag_name: str, pending_instance: dict):
    try:
        ec2 = _get_ec2_resource()
        if ec2 is not None:
            ec2.create_instances(
                ImageId=ami_id,
                InstanceType="t2.micro",
                MinCount=1,
                MaxCount=1,
                TagSpecifications=[
                    {
                        "ResourceType": "instance",
                        "Tags": [{"Key": "Name", "Value": tag_name}],
                    }
                ],
            )
    except Exception as e:
        import traceback
        print("EXCEPTION IN BACKGROUND DEPLOY SERVER:")
        traceback.print_exc()
    finally:
        # Give AWS describe APIs 5-10 seconds to catch up after the synchronous create
        import time
        time.sleep(10)
        if pending_instance in _pending_deployments:
            _pending_deployments.remove(pending_instance)


def deploy_server() -> Dict[str, Any] | None:
    """
    Provision a new EC2 t2.micro instance tagged as 'lb-server-<4 random chars>' in the background.
    In demo mode, or on any error, returns None.

    Returns:
        A server dict on success (same shape as get_all_servers entries), or None.
    """
    try:
        ec2 = _get_ec2_resource()
        if ec2 is None:
            return None

        # Resolve credentials and region for SSM lookup.
        access_key = (
            getattr(config, "AWS_ACCESS_KEY_ID", None)
            or getattr(config, "AWS_ACCESS_KEY", None)
        )
        secret_key = (
            getattr(config, "AWS_SECRET_ACCESS_KEY", None)
            or getattr(config, "AWS_SECRET_KEY", None)
        )
        region = (
            getattr(config, "AWS_DEFAULT_REGION", None)
            or getattr(config, "AWS_REGION", "us-east-1")
        )

        ami_id = _get_latest_amazon_linux2_ami(region, access_key, secret_key)
        if not ami_id:
            return None

        suffix = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=4))
        tag_name = f"lb-server-{suffix}"
        temp_id = f"i-booting-{suffix}"

        launch_time = datetime.now(timezone.utc).isoformat()

        pending_instance = {
            "id": temp_id,
            "name": tag_name,
            "ip": "assigning...",
            "status": "pending",
            "instance_type": "t2.micro",
            "launch_time": launch_time,
            "cpu_percent": 0.0,
            "response_time": 0.0,
            "health": "healthy",
            "weight": 1,
            "connections": 0,
            "requests_handled": 0,
        }
        
        _pending_deployments.append(pending_instance)

        threading.Thread(target=_deploy_worker, args=(ami_id, tag_name, pending_instance)).start()

        return pending_instance

    except Exception as e:
        import traceback
        print("EXCEPTION IN DEPLOY SERVER INIT:")
        traceback.print_exc()
        return None

def get_all_servers() -> List[Dict[str, Any]]:
    """
    Returns server dicts for instances matching tag Name containing 'lb-server'.
    Each server dict:
      id, name, ip, status, instance_type, launch_time
    """
    try:
        ec2 = _get_ec2_resource()
        if ec2 is None:
            return _demo_servers()

        servers: List[Dict[str, Any]] = list(_pending_deployments)

        # Use paginator via client under the hood if possible.
        client = ec2.meta.client
        paginator = client.get_paginator("describe_instances")
        for page in paginator.paginate():
            for reservation in page.get("Reservations", []):
                for inst in reservation.get("Instances", []):
                    instance_type = inst.get("InstanceType", "")
                    instance_id = inst.get("InstanceId", "")
                    state = (inst.get("State") or {}).get("Name", "unknown")
                    launch_time = inst.get("LaunchTime")

                    name_tag = ""
                    for tag in inst.get("Tags", []) or []:
                        if tag.get("Key") == "Name":
                            name_tag = str(tag.get("Value") or "")
                            break

                    # Tag Name containing "lb-server"
                    if "lb-server" not in name_tag:
                        continue

                    ip = inst.get("PublicIpAddress") or inst.get("PrivateIpAddress") or ""
                    if launch_time is None:
                        launch_time_iso = datetime.now(timezone.utc).isoformat()
                    else:
                        # Boto returns datetime for LaunchTime.
                        try:
                            launch_time_iso = launch_time.astimezone(timezone.utc).isoformat()
                        except Exception:
                            launch_time_iso = str(launch_time)

                    servers.append(
                        {
                            "id": instance_id,
                            "name": name_tag,
                            "ip": ip,
                            "status": state,
                            "instance_type": instance_type,
                            "launch_time": launch_time_iso,
                        }
                    )

        return servers if servers else _demo_servers()
    except Exception:
        return _demo_servers()


def start_server(instance_id: str) -> List[Dict[str, Any]]:
    """
    Starts an EC2 instance. In demo mode (or on AWS failure), returns 3 fake server dicts.
    """
    try:
        ec2 = _get_ec2_resource()
        if ec2 is None:
            return _demo_servers()

        ec2.meta.client.start_instances(InstanceIds=[instance_id])
        return get_all_servers()
    except Exception:
        return _demo_servers()


def stop_server(instance_id: str) -> List[Dict[str, Any]]:
    """
    Stops an EC2 instance. In demo mode (or on AWS failure), returns 3 fake server dicts.
    """
    try:
        ec2 = _get_ec2_resource()
        if ec2 is None:
            return _demo_servers()

        ec2.meta.client.stop_instances(InstanceIds=[instance_id])
        return get_all_servers()
    except Exception:
        return _demo_servers()

