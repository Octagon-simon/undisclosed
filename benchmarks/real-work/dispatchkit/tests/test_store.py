from dispatch.store import DeliveryStore


def test_mark_makes_the_same_event_seen():
    store = DeliveryStore()
    event = {"kind": "invoice", "id": "e1"}
    assert store.seen(event) is False
    store.mark(event)
    assert store.seen(event) is True


def test_same_id_different_kind_is_distinct():
    store = DeliveryStore()
    store.mark({"kind": "invoice", "id": "e1"})
    assert store.seen({"kind": "receipt", "id": "e1"}) is False


def test_kind_is_optional():
    store = DeliveryStore()
    store.mark({"id": "e1"})
    assert store.seen({"id": "e1"}) is True
