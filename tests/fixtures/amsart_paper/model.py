"""Toy adoption model for the acceptance fixture."""


def adoption(share: float, rate: float = 0.1) -> float:
    return share + rate * (1 - share)
