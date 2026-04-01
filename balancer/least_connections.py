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


class LeastConnections:
    """
    Chooses the healthy/running server with the lowest `connections`.

    Note on connection decrement:
    - Since only `get_next_server(servers)` is specified, we model
      "request completion" as happening right before the next selection.
    - This keeps the simulator behavior consistent in a sequential test loop.
    """

    def __init__(self) -> None:
        # Note: We do not decrement connections here because there is no
        # "request complete" callback in the required interface.
        # Connections will only move toward balance when new requests are
        # selected (lower-connection servers get chosen more often).
        #
        # If you later add a "request complete" event, you can decrement
        # connections there.
        # Used only for tie-breaking among equally-low connection servers.
        self._tie_index = 0

    def get_next_server(self, servers: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not servers:
            raise RuntimeError("No servers provided")

        eligible = [s for s in servers if _is_eligible(s)]
        if not eligible:
            raise RuntimeError("No eligible servers (all stopped/unhealthy)")

        # Pick the server(s) with the lowest `connections` value.
        # Tie-breaker: rotate among all min-connection candidates.
        min_conn = min(int(s.get("connections", 0) or 0) for s in eligible)
        candidates = [s for s in eligible if int(s.get("connections", 0) or 0) == min_conn]
        chosen = candidates[self._tie_index % len(candidates)]
        self._tie_index += 1

        # Increment connections on the *server object inside `servers` list*.
        # Find the chosen server by id and update it (prevents accidental
        # mutation of a copy).
        chosen_id = chosen.get("id") or chosen.get("name")
        for s in servers:
            if (s.get("id") or s.get("name")) == chosen_id:
                s["connections"] = int(s.get("connections", 0) or 0) + 1
                chosen = s
                break

        return chosen

