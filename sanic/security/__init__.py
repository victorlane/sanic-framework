"""Application-security battery for Sanic (opt-in, dependency-free core).

Every submodule is independently usable and **off by default**. Importing
``sanic`` (or this package) changes no behavior: nothing activates unless the
application calls an installer or sets a config flag.

Public API:

- Response security headers: :func:`install_security_headers`.
- Host-header validation: :func:`install_trusted_hosts`.
- Token-bucket rate limiting: :func:`ratelimit`, :class:`TokenBucket`,
  :class:`InMemoryRateLimitBackend`, :class:`BaseRateLimitBackend`.
- The 429 exception: :class:`TooManyRequests`.
- Convenience installer: :func:`enable_security`.

Planned CSRF (TODO — not implemented in this pass)
--------------------------------------------------
CSRF protection needs a place to store per-session state, which Sanic core
does not provide, so it is intentionally deferred. The planned design is a
**double-submit cookie** keyed on the ``SECRET`` config value:

1. On a safe request (GET/HEAD/OPTIONS) with no CSRF cookie present, generate
   a random token, store it in a cookie, and make it available to templates.
2. The token is signed/HMAC'd using ``config.SECRET`` so the server can verify
   authenticity without server-side session storage.
3. On unsafe requests (POST/PUT/PATCH/DELETE), require the token to be echoed
   in a header or form field and verify it matches (and validates against
   ``SECRET``) the cookie value. Reject with 403 otherwise.

Until that lands, set ``config.SECRET`` now if you want signed-cookie / CSRF
features to pick it up later.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sanic.exceptions import TooManyRequests
from sanic.security.headers import (
    install_security_headers,
    security_headers_middleware,
)
from sanic.security.ratelimit import (
    BaseRateLimitBackend,
    InMemoryRateLimitBackend,
    TokenBucket,
    ratelimit,
)
from sanic.security.trusted_hosts import install_trusted_hosts


if TYPE_CHECKING:
    from sanic import Sanic


__all__ = (
    "BaseRateLimitBackend",
    "InMemoryRateLimitBackend",
    "TokenBucket",
    "TooManyRequests",
    "enable_security",
    "install_security_headers",
    "install_trusted_hosts",
    "ratelimit",
    "security_headers_middleware",
)


def enable_security(
    app: Sanic,
    *,
    headers: bool | None = None,
    trusted_hosts: bool = True,
) -> None:
    """Install the config-driven security features on ``app``.

    This is a convenience wrapper that wires up the header and trusted-host
    installers. The installers themselves are no-ops at request time unless the
    relevant config is enabled, so calling this is always safe.

    Args:
        app: The Sanic application.
        headers: Whether to install the security-headers middleware. When
            ``None`` (default), it is installed only if
            ``config.SECURITY_HEADERS`` is truthy. Pass ``True``/``False`` to
            force.
        trusted_hosts: Whether to install the trusted-hosts middleware. It
            self-disables when ``config.TRUSTED_HOSTS`` is empty/``None``, so
            installing it unconditionally is safe. Defaults to ``True``.
    """
    install_headers = (
        app.config.SECURITY_HEADERS if headers is None else headers
    )
    if install_headers:
        install_security_headers(app)
    if trusted_hosts:
        install_trusted_hosts(app)
