from .round_robin import RoundRobin
from .least_connections import LeastConnections
from .weighted import WeightedRoundRobin


def get_algorithm(name: str):
    """
    name: one of:
      - round_robin
      - least_connections
      - weighted
    """
    if not isinstance(name, str):
        raise ValueError("Algorithm name must be a string")

    normalized = name.strip().lower()
    if normalized == "round_robin":
        return RoundRobin()
    if normalized == "least_connections":
        return LeastConnections()
    if normalized == "weighted":
        return WeightedRoundRobin()

    valid = ["round_robin", "least_connections", "weighted"]
    raise ValueError(f"Invalid algorithm '{name}'. Valid: {valid}")

