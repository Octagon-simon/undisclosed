from dispatch.backoff import MAX_DELAY_SECONDS, retry_delay


def test_first_retry_waits_half_a_second():
    assert retry_delay(1) == 0.5


def test_delay_doubles_each_attempt():
    assert [retry_delay(1), retry_delay(2), retry_delay(3)] == [0.5, 1.0, 2.0]


def test_delay_is_capped():
    assert retry_delay(10) == MAX_DELAY_SECONDS


def test_custom_base_is_respected():
    assert retry_delay(1, base=0.25) == 0.25
