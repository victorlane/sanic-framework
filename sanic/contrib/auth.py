"""Reusable, pure-core authentication primitives.

These helpers generalize the token-retrieval and route-guarding patterns
found in plugins such as ``sanic-jwt`` *without* bundling any particular
token format (JWT, opaque session id, ...). They depend only on
:class:`~sanic.request.Request`, ``request.ctx`` and the existing
exceptions, so they add no third-party dependencies and act as the seam
that external JWT/session plugins can plug into.

- :func:`get_token` — tri-source token retrieval (header, cookie, query).
- :func:`protected` — guard a handler behind an async ``verify`` callable,
  raising :class:`~sanic.exceptions.Unauthorized` on failure and storing
  the resolved principal at ``request.ctx.user`` on success.
- :func:`scoped` — require that the principal carries a set of scopes,
  raising :class:`~sanic.exceptions.Forbidden` otherwise.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Awaitable, Callable, Iterable

from sanic.exceptions import Forbidden, Unauthorized
from sanic.headers import parse_credentials
from sanic.request import Request


__all__ = ["get_token", "protected", "scoped"]


def get_token(
    request: Request,
    *,
    header: str | None = "Authorization",
    scheme: str = "Bearer",
    cookie: str | None = None,
    query: str | None = None,
) -> str | None:
    """Retrieve a raw token from a request, checking multiple sources.

    Sources are checked in order and the first hit wins:

    1. The ``header`` request header (default ``Authorization``), matched
       against ``scheme`` using :func:`sanic.headers.parse_credentials`,
       which performs an anchored, case-insensitive scheme match (so a
       value like ``"NotBearer abc"`` is *not* treated as a Bearer token).
    2. The ``cookie`` cookie, if a name is given.
    3. The ``query`` query-string key, if a name is given.

    Args:
        request (Request): The incoming request.
        header (Optional[str]): Header name to read the credentials from.
            Pass ``None`` to skip the header source. Defaults to
            ``"Authorization"``.
        scheme (str): The authorization scheme to match, e.g. ``"Bearer"``,
            ``"Token"`` or ``"Basic"``. Defaults to ``"Bearer"``.
        cookie (Optional[str]): Cookie name to read the token from, if any.
        query (Optional[str]): Query-string key to read the token from, if
            any.

    Returns:
        Optional[str]: The raw token, or ``None`` if no source matched.
    """
    if header is not None:
        raw = request.headers.get(header)
        if raw is not None:
            prefix, credentials = parse_credentials(raw, (scheme,))
            if prefix is not None and credentials:
                return credentials

    if cookie is not None:
        token = request.cookies.get(cookie)
        if token:
            return token

    if query is not None:
        token = request.args.get(query)
        if token:
            return token

    return None


def protected(
    verify: Callable[[Request], Awaitable[Any]],
) -> Callable[[Callable], Callable]:
    """Guard a handler behind an async ``verify`` callable.

    ``verify`` is awaited with the request and must return the
    authenticated *principal* (any truthy object identifying the caller).
    If it returns a falsy value or raises, the request is rejected with
    :class:`~sanic.exceptions.Unauthorized` (HTTP 401). On success the
    principal is stored at ``request.ctx.user`` and the wrapped handler is
    called as usual.

    Example::

        async def verify(request):
            token = get_token(request)
            return await lookup_user(token)  # None if invalid

        @app.get("/me")
        @protected(verify)
        async def me(request):
            return json({"user": request.ctx.user})

    Args:
        verify (Callable[[Request], Awaitable[Any]]): Async callable that
            resolves a request to a principal, or a falsy value / raises on
            failure.

    Returns:
        Callable: A decorator that wraps a request handler.
    """

    def decorator(handler: Callable) -> Callable:
        @wraps(handler)
        async def wrapper(request: Request, *args: Any, **kwargs: Any):
            try:
                principal = await verify(request)
            except Unauthorized:
                raise
            except Exception:
                raise Unauthorized("Authentication required")
            if not principal:
                raise Unauthorized("Authentication required")
            request.ctx.user = principal
            return await handler(request, *args, **kwargs)

        return wrapper

    return decorator


def scoped(
    required_scopes: str | Iterable[str],
    *,
    get_scopes: Callable[[Request], Iterable[str]],
) -> Callable[[Callable], Callable]:
    """Require that the caller carries a set of scopes.

    ``get_scopes`` is called with the request and must return the scopes
    granted to the current principal (typically read from
    ``request.ctx.user``). If any of ``required_scopes`` is missing, the
    request is rejected with :class:`~sanic.exceptions.Forbidden`
    (HTTP 403).

    This decorator does not authenticate; pair it with :func:`protected`
    (placed *outside* / above it) so a principal is resolved first.

    Example::

        @app.get("/admin")
        @protected(verify)
        @scoped("admin", get_scopes=lambda r: r.ctx.user["scopes"])
        async def admin(request):
            return text("ok")

    Args:
        required_scopes (Union[str, Iterable[str]]): A single scope or an
            iterable of scopes that must all be present.
        get_scopes (Callable[[Request], Iterable[str]]): Callable returning
            the scopes granted to the current principal.

    Returns:
        Callable: A decorator that wraps a request handler.
    """
    if isinstance(required_scopes, str):
        needed = frozenset({required_scopes})
    else:
        needed = frozenset(required_scopes)

    def decorator(handler: Callable) -> Callable:
        @wraps(handler)
        async def wrapper(request: Request, *args: Any, **kwargs: Any):
            granted = frozenset(get_scopes(request) or ())
            if not needed.issubset(granted):
                raise Forbidden("Insufficient scope")
            return await handler(request, *args, **kwargs)

        return wrapper

    return decorator
