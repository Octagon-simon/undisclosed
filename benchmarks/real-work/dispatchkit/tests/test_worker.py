import pytest

from dispatch.store import DeliveryStore
from dispatch.worker import RateLimited, Transient, deliver


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def post(self, event):
        self.calls.append(event)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_rate_limited_then_success_retries():
    client = FakeClient([RateLimited(), None])
    sleeps = []
    result = deliver(
        {"kind": "invoice", "id": "e1"},
        client,
        DeliveryStore(),
        sleep=sleeps.append,
    )
    assert result == "delivered"
    assert len(client.calls) == 2
    assert sleeps == [0.5]


def test_transient_retries_then_succeeds():
    client = FakeClient([Transient(), Transient(), None])
    sleeps = []
    result = deliver(
        {"kind": "invoice", "id": "e1"},
        client,
        DeliveryStore(),
        sleep=sleeps.append,
    )
    assert result == "delivered"
    assert sleeps == [0.5, 1.0]


def test_rate_limit_is_retried_until_attempts_run_out():
    client = FakeClient([RateLimited(), RateLimited(), RateLimited()])
    with pytest.raises(RateLimited):
        deliver(
            {"kind": "invoice", "id": "e1"},
            client,
            DeliveryStore(),
            sleep=lambda _: None,
        )
    assert len(client.calls) == 3


def test_duplicate_is_not_posted():
    store = DeliveryStore()
    event = {"kind": "invoice", "id": "e1"}
    store.mark(event)
    client = FakeClient([])
    assert deliver(event, client, store) == "duplicate"
    assert client.calls == []


def test_failed_delivery_is_not_marked():
    store = DeliveryStore()
    event = {"kind": "invoice", "id": "e1"}
    client = FakeClient([RateLimited(), RateLimited(), RateLimited()])
    with pytest.raises(RateLimited):
        deliver(event, client, store, sleep=lambda _: None)
    assert store.seen(event) is False


def test_same_id_different_kind_is_delivered():
    store = DeliveryStore()
    store.mark({"kind": "invoice", "id": "e1"})
    client = FakeClient([None])
    result = deliver(
        {"kind": "receipt", "id": "e1"},
        client,
        store,
        sleep=lambda _: None,
    )
    assert result == "delivered"
    assert len(client.calls) == 1
