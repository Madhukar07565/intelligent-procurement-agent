"""Bedrock client: rate limit (hackathon rule: under 1 request/second) and retries."""
import threading

import pytest
from botocore.exceptions import ClientError

from procurement.llm import MIN_INTERVAL_FLOOR, BedrockClient, LLMServiceError, RateLimiter


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


class RecordingClient:
    def __init__(self, t, errors=()):
        self.t = t
        self.errors = list(errors)
        self.call_times = []

    def converse(self, **kwargs):
        self.call_times.append(self.t.now)
        if self.errors:
            code = self.errors.pop(0)
            raise ClientError({"Error": {"Code": code, "Message": code}}, "Converse")
        return {"output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}}}


def make(errors=(), interval=1.2, attempts=4):
    t = FakeTime()
    limiter = RateLimiter(interval, clock=t.clock, sleep=t.sleep)
    raw = RecordingClient(t, errors)
    return BedrockClient(model_id="m", client=raw, limiter=limiter, max_attempts=attempts, sleep=t.sleep), raw, t


def gaps(times):
    return [b - a for a, b in zip(times, times[1:])]


def test_RL1_consecutive_calls_are_spaced_over_one_second():
    client, raw, _ = make()
    for _ in range(5):
        client.converse("s", [])
    assert len(raw.call_times) == 5
    assert all(g >= 1.2 - 1e-9 for g in gaps(raw.call_times))


def test_RL2_interval_can_never_be_configured_at_or_below_one_second():
    for value in (0, 0.5, 1.0):
        assert RateLimiter(value).min_interval == MIN_INTERVAL_FLOOR > 1.0


def test_RL3_first_call_is_not_delayed():
    client, raw, t = make()
    client.converse("s", [])
    assert t.sleeps == [] and raw.call_times == [0.0]


def test_RL4_retries_also_respect_the_limit():
    client, raw, _ = make(errors=["ThrottlingException", "ThrottlingException"])
    client.converse("s", [])
    assert len(raw.call_times) == 3
    assert all(g > 1.0 for g in gaps(raw.call_times))


def test_RL5_gives_up_with_friendly_error_after_max_attempts():
    client, raw, _ = make(errors=["ThrottlingException"] * 10, attempts=3)
    with pytest.raises(LLMServiceError, match="busy"):
        client.converse("s", [])
    assert len(raw.call_times) == 3


def test_RL6_non_retryable_errors_are_not_retried():
    client, raw, _ = make(errors=["AccessDeniedException"])
    with pytest.raises(ClientError):
        client.converse("s", [])
    assert len(raw.call_times) == 1


def test_RL7_limiter_holds_across_threads():
    """Real clock: 4 threads calling at once must still be spaced out."""
    import time
    limiter = RateLimiter(1.05)
    times = []

    def go():
        limiter.acquire()
        times.append(time.monotonic())

    ts = [threading.Thread(target=go) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    times.sort()
    assert all(g >= 1.04 for g in gaps(times))


def test_RL8_default_clients_share_one_limiter():
    a = BedrockClient(model_id="m", client=object())
    b = BedrockClient(model_id="m", client=object())
    assert a._limiter is b._limiter


def test_RL9_real_boto_client_has_botocore_retries_disabled():
    c = BedrockClient(region="us-east-1")
    assert c._client.meta.config.retries["total_max_attempts"] == 1
    assert c._client.meta.region_name == "us-east-1"
