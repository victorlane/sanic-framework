"""Host-header validation.

An opt-in guard that rejects requests whose ``Host`` header is not in an
allow-list. This mitigates host-header injection and cache-poisoning attacks
when the application is reachable under an untrusted set of names.

Driven by the ``TRUSTED_HOSTS`` config key:

- ``None`` or an empty list (the default): validation is disabled and all
  hosts are accepted.
- A non-empty ``list[str]``: only hosts matching an entry are accepted. Both
  exact matches (``"example.com"``) and leading-wildcard matches
  (``"*.example.com"``, which matches any single-or-multi-label subdomain but
  not the bare apex) are supported. Matching is case-insensitive and ignores
  any port in the request host.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from sanic.exceptions import BadRequest
from sanic.headers import parse_host


if TYPE_CHECKING:
    from sanic import Request, Sanic


def host_matches(hostname: str, pattern: str) -> bool:
    """Return whether ``hostname`` matches a single allow-list ``pattern``.

    Matching is case-insensitive. A pattern of the form ``*.example.com``
    matches any subdomain of ``example.com`` (e.g. ``a.example.com`` and
    ``a.b.example.com``) but not the apex ``example.com`` itself. Any other
    pattern is compared for exact equality.

    Args:
        hostname: The request hostname (no port).
        pattern: A single allow-list entry.

    Returns:
        ``True`` if the hostname is allowed by the pattern.
    """
    hostname = hostname.lower()
    pattern = pattern.lower()
    if pattern.startswith("*."):
        suffix = pattern[1:]  # keep leading dot, e.g. ".example.com"
        return hostname.endswith(suffix) and len(hostname) > len(suffix)
    return hostname == pattern


def is_trusted_host(host: str, trusted_hosts: Iterable[str]) -> bool:
    """Return whether ``host`` matches any entry in ``trusted_hosts``.

    Args:
        host: The raw request host (may include a port).
        trusted_hosts: The allow-list of host patterns.

    Returns:
        ``True`` if the host is trusted.
    """
    hostname, _ = parse_host(host)
    if not hostname:
        return False
    return any(host_matches(hostname, pattern) for pattern in trusted_hosts)


def install_trusted_hosts(app: Sanic, *, priority: int = 100) -> None:
    """Install the trusted-hosts request middleware on ``app``.

    The middleware runs at a high priority (before most user middleware and
    any routing side effects) and, when ``config.TRUSTED_HOSTS`` is a
    non-empty list, raises :class:`sanic.exceptions.BadRequest` (400) for
    requests whose host is not allowed. When the config is empty/``None`` the
    middleware is a no-op, so installing it unconditionally is safe.

    Args:
        app: The Sanic application.
        priority: Middleware priority forwarded to ``app.on_request``.
    """

    async def _validate_host(request: Request) -> None:
        trusted_hosts = request.app.config.TRUSTED_HOSTS
        if not trusted_hosts:
            return
        if not is_trusted_host(request.host, trusted_hosts):
            raise BadRequest("Invalid host header")

    app.on_request(_validate_host, priority=priority)
