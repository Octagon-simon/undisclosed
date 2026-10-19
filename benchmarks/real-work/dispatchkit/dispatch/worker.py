"""Delivery loop with retries."""

import time

from dispatch.backoff import retry_delay
from dispatch.store import DeliveryStore


class RateLimited(Exception):
    """The provider asked us to slow down."""


class Transient(Exception):
    """A temporary failure worth retrying."""


def deliver(
    event: dict,
    client,
    store: DeliveryStore,
    sleep=time.sleep,
    max_attempts: int = 3,
) -> str:
    """Deliver one event, retrying rate limits and transient failures."""
    if store.seen(event):
        return "duplicate"

    for attempt in range(1, max_attempts + 1):
        try:
            client.post(event)
        except RateLimited:
            raise
        except Transient:
            if attempt == max_attempts:
                raise
            sleep(retry_delay(attempt))
        else:
            store.mark(event)
            return "delivered"

    raise AssertionError("unreachable")
