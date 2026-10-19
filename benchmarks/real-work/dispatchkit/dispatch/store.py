"""In-memory delivery ledger."""


class DeliveryStore:
    """Tracks which events have been delivered."""

    def __init__(self) -> None:
        self._delivered: set[tuple[str | None, str]] = set()

    def key(self, event: dict) -> str:
        """Identity of an event."""
        return event["id"]

    def seen(self, event: dict) -> bool:
        """True when this event has already been delivered."""
        return self.key(event) in self._delivered

    def mark(self, event: dict) -> None:
        """Record a successful delivery."""
        self._delivered.add(self.key(event))
