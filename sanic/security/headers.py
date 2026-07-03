"""Security response headers.

This module provides an opt-in helper that adds a small set of hardening
response headers using ``setdefault`` semantics: it never overwrites a header
that a route handler (or earlier middleware) has already set.

Everything here is driven by the application config and is off by default.
The relevant config keys are:

- ``SECURITY_HEADERS`` (bool, default ``False``): master switch. Nothing is
  applied unless this is truthy or you call :func:`install_security_headers`
  directly.
- ``SECURITY_HEADERS_CONTENT_TYPE_OPTIONS`` (bool, default ``True``): when
  truthy, sets ``X-Content-Type-Options: nosniff``.
- ``SECURITY_HEADERS_FRAME_OPTIONS`` (str | None, default ``"DENY"``): value
  for ``X-Frame-Options``; set to ``None``/empty to disable.
- ``SECURITY_HEADERS_REFERRER_POLICY`` (str | None, default
  ``"strict-origin-when-cross-origin"``): value for ``Referrer-Policy``; set
  to ``None``/empty to disable.
- ``SECURITY_HEADERS_CONTENT_SECURITY_POLICY`` (str | None, default ``None``):
  value for ``Content-Security-Policy``. There is deliberately no default CSP
  because a safe policy is application specific.
- ``SECURITY_HEADERS_HSTS`` (bool, default ``False``): whether to emit
  ``Strict-Transport-Security``. HSTS is dangerous to enable blindly (it can
  make a host unreachable over http), so it defaults OFF and is only ever sent
  on ``https`` requests.
- ``SECURITY_HEADERS_HSTS_MAX_AGE`` (int, default ``31536000``): ``max-age``
  for HSTS in seconds.
- ``SECURITY_HEADERS_HSTS_INCLUDE_SUBDOMAINS`` (bool, default ``True``): add
  ``includeSubDomains`` to the HSTS header.
- ``SECURITY_HEADERS_HSTS_PRELOAD`` (bool, default ``False``): add ``preload``
  to the HSTS header.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable


if TYPE_CHECKING:
    from sanic import Request, Sanic
    from sanic.response import BaseHTTPResponse


def _build_hsts_value(config) -> str:
    parts = [f"max-age={int(config.SECURITY_HEADERS_HSTS_MAX_AGE)}"]
    if config.SECURITY_HEADERS_HSTS_INCLUDE_SUBDOMAINS:
        parts.append("includeSubDomains")
    if config.SECURITY_HEADERS_HSTS_PRELOAD:
        parts.append("preload")
    return "; ".join(parts)


def security_headers_middleware(
    config,
) -> Callable[[Request, BaseHTTPResponse], None]:
    """Build a response middleware that applies security headers.

    The returned callable reads its values from ``config`` at request time, so
    changing config values after installation is respected. All headers are
    applied with ``setdefault`` semantics: a header already present on the
    response is left untouched.

    Args:
        config: The application config (``app.config``).

    Returns:
        A response middleware ``(request, response) -> None``.
    """

    def _apply(request: Request, response: BaseHTTPResponse) -> None:
        headers = response.headers

        if config.SECURITY_HEADERS_CONTENT_TYPE_OPTIONS:
            headers.setdefault("X-Content-Type-Options", "nosniff")

        frame_options = config.SECURITY_HEADERS_FRAME_OPTIONS
        if frame_options:
            headers.setdefault("X-Frame-Options", frame_options)

        referrer_policy = config.SECURITY_HEADERS_REFERRER_POLICY
        if referrer_policy:
            headers.setdefault("Referrer-Policy", referrer_policy)

        csp = config.SECURITY_HEADERS_CONTENT_SECURITY_POLICY
        if csp:
            headers.setdefault("Content-Security-Policy", csp)

        # HSTS is only ever emitted on secure requests, and only when the app
        # has explicitly opted in. Sending it over plain http is meaningless
        # and enabling it accidentally can lock clients out of a host.
        if config.SECURITY_HEADERS_HSTS and request.scheme == "https":
            headers.setdefault(
                "Strict-Transport-Security", _build_hsts_value(config)
            )

    return _apply


def install_security_headers(app: Sanic, *, priority: int = 0) -> None:
    """Install the security-headers response middleware on ``app``.

    This is idempotent-ish in intent but does not guard against being called
    twice; call it once during setup. It attaches an ``on_response``
    middleware that applies the configured headers with ``setdefault``
    semantics.

    Args:
        app: The Sanic application.
        priority: Middleware priority forwarded to ``app.on_response``.
    """
    app.on_response(
        security_headers_middleware(app.config), priority=priority
    )
