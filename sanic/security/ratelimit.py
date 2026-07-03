"""Token-bucket rate limiting.

A small, dependency-free reimplementation of the token-bucket algorithm plus a
handler decorator. The design mirrors the shape of the ``sanic-bucket`` project
(bucket + pluggable backend + identify function) but is implemented from
scratch here.

.. important::
    The shipped :class:`InMemoryRateLimitBackend` stores buckets in a plain
    dict on the worker process. It is therefore **per-worker** and **not**
    shared across workers or hosts. Running Sanic with multiple workers means
    each worker enforces the limit independently, so the effective limit is
    roughly ``max_size * num_workers``. For a correct global limit across
    workers you need a shared store (e.g. Redis). A Redis backend is left as a
    documented extension point: subclass :class:`BaseRateLimitBackend` and
    implement ``create``/``fetch``/``persist`` against your store.
"""

from __future__ import annotations

import time

from abc import ABC, abstractmethod
from functools import wraps
from typing import TYPE_CHECKING, Awaitable, Callable

from sanic.exceptions import TooManyRequests


if TYPE_CHECKING:
    from sanic import Request


class TokenBucket:
    """A single token bucket.

    Tokens refill continuously based on elapsed monotonic time
    (``time.monotonic()``), which is immune to wall-clock adjustments and does
    not require a running event loop. The token count is tracked as a float so
    that partial refills are represented exactly and the bucket is
    deterministically testable by driving a controllable clock (patch
    ``TokenBucket._now``).

    Args:
        ident: An opaque identifier for whom this bucket belongs to.
        max_size: The maximum (and initial) number of tokens.
        refill_interval: The number of seconds it takes to fully refill the
            bucket from empty. Tokens are added at ``max_size /
            refill_interval`` per second.
    """

    __slots__ = ("ident", "max_size", "refill_interval", "_tokens", "_last")

    def __init__(
        self, ident: str, max_size: float, refill_interval: float
    ) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be greater than 0")
        if refill_interval <= 0:
            raise ValueError("refill_interval must be greater than 0")
        self.ident = ident
        self.max_size = float(max_size)
        self.refill_interval = float(refill_interval)
        self._tokens = float(max_size)
        self._last = self._now()

    @staticmethod
    def _now() -> float:
        return time.monotonic()

    @property
    def tokens(self) -> float:
        """Current token count without mutating the bucket (post-refill)."""
        return min(self.max_size, self._tokens + self._elapsed_tokens())

    def _elapsed_tokens(self) -> float:
        elapsed = self._now() - self._last
        if elapsed <= 0:
            return 0.0
        return elapsed * (self.max_size / self.refill_interval)

    def _refill(self) -> None:
        gained = self._elapsed_tokens()
        if gained > 0:
            self._tokens = min(self.max_size, self._tokens + gained)
            self._last = self._now()

    async def consume(self, amount: float = 1.0) -> None:
        """Consume ``amount`` tokens or raise.

        Refills based on elapsed time first, then attempts to consume. If not
        enough tokens are available, raises :class:`TooManyRequests` and does
        not partially consume.

        Args:
            amount: Number of tokens to consume. Defaults to ``1``.

        Raises:
            TooManyRequests: If the bucket does not have ``amount`` tokens.
        """
        self._refill()
        if self._tokens >= amount:
            self._tokens -= amount
            return
        raise TooManyRequests("Too many requests")


class BaseRateLimitBackend(ABC):
    """Abstract storage backend for token buckets.

    Implementations decide how buckets are created, fetched, and persisted.
    The default core backend is in-memory; a distributed backend (e.g. Redis)
    would serialize the bucket's token count and timestamp to a shared store.
    """

    def __init__(self, max_size: float, refill_interval: float) -> None:
        self.max_size = max_size
        self.refill_interval = refill_interval

    @abstractmethod
    async def create(self, ident: str) -> TokenBucket:
        """Create a fresh, full bucket for ``ident``."""

    @abstractmethod
    async def fetch(self, ident: str) -> TokenBucket:
        """Return the existing bucket for ``ident``, creating one if absent."""

    @abstractmethod
    async def persist(self, bucket: TokenBucket) -> None:
        """Persist the (mutated) bucket back to the store."""


class InMemoryRateLimitBackend(BaseRateLimitBackend):
    """A dict-backed, per-worker rate-limit backend.

    Suitable for single-worker deployments or best-effort limiting. See the
    module docstring for the multi-worker caveat.
    """

    def __init__(self, max_size: float, refill_interval: float) -> None:
        super().__init__(max_size, refill_interval)
        self._buckets: dict[str, TokenBucket] = {}

    async def create(self, ident: str) -> TokenBucket:
        bucket = TokenBucket(ident, self.max_size, self.refill_interval)
        self._buckets[ident] = bucket
        return bucket

    async def fetch(self, ident: str) -> TokenBucket:
        bucket = self._buckets.get(ident)
        if bucket is None:
            bucket = await self.create(ident)
        return bucket

    async def persist(self, bucket: TokenBucket) -> None:
        # In-memory buckets are mutated in place, so nothing to do. A
        # distributed backend would write the token count/timestamp here.
        self._buckets[bucket.ident] = bucket


def identify(request: Request) -> str:
    """Default identity function for rate limiting.

    Uses the client's address (``request.remote_addr`` when behind a
    configured proxy, otherwise ``request.client_ip``). This **fails closed**:
    if no address can be determined it returns a single fixed bucket key
    (``"__anonymous__"``) so that un-addressable clients share one limited
    bucket rather than each getting an unlimited unique bucket.

    Args:
        request: The incoming request.

    Returns:
        A stable string key for the client.
    """
    return request.remote_addr or request.client_ip or "__anonymous__"


def ratelimit(
    max_size: float,
    refill_interval: float,
    *,
    backend: BaseRateLimitBackend | None = None,
    identify: Callable[[Request], str] = identify,
) -> Callable:
    """Decorate a Sanic handler with token-bucket rate limiting.

    On each request the flow is: ``identify(request)`` -> ``backend.fetch`` ->
    ``bucket.consume()`` -> ``backend.persist``. When the bucket is empty,
    :class:`TooManyRequests` propagates and Sanic renders a 429 response.

    If no ``backend`` is supplied, a default :class:`InMemoryRateLimitBackend`
    (sized by ``max_size``/``refill_interval``) is created lazily and stored on
    ``app.ctx`` keyed by these parameters, so repeated calls with the same
    limits share a backend within a worker.

    Args:
        max_size: Maximum burst size (tokens) per identity.
        refill_interval: Seconds to fully refill an empty bucket.
        backend: Optional explicit backend. Defaults to a per-worker
            in-memory backend stored on ``app.ctx``.
        identify: Function mapping a request to a bucket key. Defaults to
            :func:`identify`, which fails closed.

    Returns:
        A decorator wrapping an async handler.
    """
    identify_fn = identify

    def decorator(handler: Callable[..., Awaitable]) -> Callable:
        # functools.wraps sets __wrapped__ so inspect.signature() resolves to
        # the handler's real signature. This lets sanic-ext (and anything else
        # that introspects the handler) still see injected parameters such as
        # DI-provided services when @ratelimit is stacked with them.
        @wraps(handler)
        async def wrapper(request: Request, *args, **kwargs):
            active_backend = backend
            if active_backend is None:
                active_backend = _get_default_backend(
                    request, max_size, refill_interval
                )
            ident = identify_fn(request)
            bucket = await active_backend.fetch(ident)
            await bucket.consume()
            await active_backend.persist(bucket)
            return await handler(request, *args, **kwargs)

        return wrapper

    return decorator


def _get_default_backend(
    request: Request, max_size: float, refill_interval: float
) -> InMemoryRateLimitBackend:
    key = (max_size, refill_interval)
    registry = getattr(request.app.ctx, "_ratelimit_backends", None)
    if registry is None:
        registry = {}
        request.app.ctx._ratelimit_backends = registry
    backend = registry.get(key)
    if backend is None:
        backend = InMemoryRateLimitBackend(max_size, refill_interval)
        registry[key] = backend
    return backend
