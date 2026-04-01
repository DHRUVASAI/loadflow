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


class WeightedRoundRobin:
    """
    Distributes requests based on integer `weight` (1-5).

    Higher weight => proportionally more requests.
    Implemented via an expanded "slots" list, rebuilt each call.
    """

    def __init__(self) -> None:
        self._index = 0

    def get_next_server(self, servers: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not servers:
            raise RuntimeError("No servers provided")

        eligible = [s for s in servers if _is_eligible(s)]
        if not eligible:
            raise RuntimeError("No eligible servers (all stopped/unhealthy)")

        slots: List[Dict[str, Any]] = []
        for s in eligible:
            w_raw = s.get("weight", 1)
            try:
                w = int(w_raw)
            except Exception:
                w = 1
            w = max(1, min(5, w))
            slots.extend([s] * w)

        if not slots:
            raise RuntimeError("No eligible servers available")

        chosen = slots[self._index % len(slots)]
        self._index += 1
        return chosen

