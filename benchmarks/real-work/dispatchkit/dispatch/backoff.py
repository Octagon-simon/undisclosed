"""Retry delays for the delivery worker."""

MAX_DELAY_SECONDS = 8.0


def retry_delay(attempt: int, base: float = 0.5) -> float:
    """Seconds to wait before retrying. `attempt` is 1-based."""
    return min(MAX_DELAY_SECONDS, base * (2**attempt))
