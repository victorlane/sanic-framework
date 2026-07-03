import pytest

from sanic.exceptions import TooManyRequests
from sanic.response import text
from sanic.security.ratelimit import (
    InMemoryRateLimitBackend,
    TokenBucket,
    identify,
    ratelimit,
)


class FakeClock:
    """A controllable monotonic clock for driving TokenBucket timing."""

    def __init__(self):
        self.t = 1000.0

    def now(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(TokenBucket, "_now", staticmethod(fake.now))
    return fake


@pytest.mark.asyncio
async def test_bucket_consume_until_empty(clock):
    bucket = TokenBucket("id", 3, refill_interval=10)
    await bucket.consume()
    await bucket.consume()
    await bucket.consume()
    with pytest.raises(TooManyRequests):
        await bucket.consume()


@pytest.mark.asyncio
async def test_bucket_refill_by_elapsed_time(clock):
    bucket = TokenBucket("id", 2, refill_interval=2)
    # rate = 2 tokens / 2s = 1 token/s
    await bucket.consume()
    await bucket.consume()
    with pytest.raises(TooManyRequests):
        await bucket.consume()

    clock.advance(1.0)  # regain 1 token
    await bucket.consume()
    with pytest.raises(TooManyRequests):
        await bucket.consume()

    clock.advance(10.0)  # fully refill, but cap at max_size
    assert bucket.tokens == 2
    await bucket.consume()
    await bucket.consume()
    with pytest.raises(TooManyRequests):
        await bucket.consume()


@pytest.mark.asyncio
async def test_bucket_partial_refill_does_not_exceed_max(clock):
    bucket = TokenBucket("id", 5, refill_interval=5)
    clock.advance(100.0)
    assert bucket.tokens == 5


def test_bucket_invalid_args():
    with pytest.raises(ValueError):
        TokenBucket("id", 0, 1)
    with pytest.raises(ValueError):
        TokenBucket("id", 1, 0)


@pytest.mark.asyncio
async def test_inmemory_backend_fetch_creates_and_shares(clock):
    backend = InMemoryRateLimitBackend(2, 10)
    b1 = await backend.fetch("a")
    b2 = await backend.fetch("a")
    assert b1 is b2
    b3 = await backend.fetch("b")
    assert b3 is not b1


class _FakeRequest:
    def __init__(self, remote_addr="", client_ip="", ip=""):
        self._remote_addr = remote_addr
        self._client_ip = client_ip

    @property
    def remote_addr(self):
        return self._remote_addr

    @property
    def client_ip(self):
        return self._client_ip


def test_identify_uses_remote_addr():
    req = _FakeRequest(remote_addr="1.2.3.4", client_ip="5.6.7.8")
    assert identify(req) == "1.2.3.4"


def test_identify_falls_back_to_client_ip():
    req = _FakeRequest(remote_addr="", client_ip="5.6.7.8")
    assert identify(req) == "5.6.7.8"


def test_identify_fails_closed():
    # No address at all -> a single shared bucket, never a unique id
    req = _FakeRequest(remote_addr="", client_ip="")
    a = identify(req)
    b = identify(_FakeRequest(remote_addr="", client_ip=""))
    assert a == b == "__anonymous__"


def test_ratelimit_returns_429_after_n_and_resets(app, clock):
    @app.get("/")
    @ratelimit(2, refill_interval=2)
    async def handler(request):
        return text("ok")

    headers = {"X-Forwarded-For": "9.9.9.9"}
    app.config.PROXIES_COUNT = 1

    _, r1 = app.test_client.get("/", headers=headers)
    _, r2 = app.test_client.get("/", headers=headers)
    _, r3 = app.test_client.get("/", headers=headers)
    assert r1.status == 200
    assert r2.status == 200
    assert r3.status == 429

    # After enough time, tokens refill and requests succeed again
    clock.advance(2.0)
    _, r4 = app.test_client.get("/", headers=headers)
    assert r4.status == 200


def test_ratelimit_separate_ids_independent(app, clock):
    @app.get("/")
    @ratelimit(1, refill_interval=100)
    async def handler(request):
        return text("ok")

    app.config.PROXIES_COUNT = 1

    _, a1 = app.test_client.get("/", headers={"X-Forwarded-For": "1.1.1.1"})
    _, a2 = app.test_client.get("/", headers={"X-Forwarded-For": "1.1.1.1"})
    assert a1.status == 200
    assert a2.status == 429

    # A different client is unaffected
    _, b1 = app.test_client.get("/", headers={"X-Forwarded-For": "2.2.2.2"})
    assert b1.status == 200


@pytest.mark.asyncio
async def test_ratelimit_custom_backend(clock):
    backend = InMemoryRateLimitBackend(1, 100)

    calls = []

    @ratelimit(1, 100, backend=backend, identify=lambda req: "fixed")
    async def handler(request):
        calls.append(1)
        return "ok"

    class Req:
        pass

    req = Req()
    assert await handler(req) == "ok"
    with pytest.raises(TooManyRequests):
        await handler(req)
    assert len(calls) == 1
