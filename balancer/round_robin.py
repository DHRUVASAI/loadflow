from __future__ import annotations

from typing import Dict, List, Any


def _is_eligible(server: Dict[str, Any]) -> bool:
    status = str(server.get("status", "running")).strip().lower()
    health = str(server.get("health", "healthy")).strip().lower()

    stopped_states = {"stopped", "stop", "terminated", "disabled"}
    if status in stopped_states:
        return False
    if health != "healthy":
        return False
    return True


class RoundRobin:
    def __init__(self) -> None:
        self._index = 0

    def get_next_server(self, servers: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not servers:
            raise RuntimeError("No servers provided")

        if self._index >= len(servers):
            self._index = 0

        n = len(servers)
        # Try at most n times to find an eligible server.
        for _ in range(n):
            candidate = servers[self._index % n]
            self._index += 1
            if _is_eligible(candidate):
                return candidate

        raise RuntimeError("No eligible servers (all stopped/unhealthy)")

