from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable, MutableMapping


if TYPE_CHECKING:
    from sanic.request import Request


ASGIScope = MutableMapping[str, Any]
ASGIMessage = MutableMapping[str, Any]
ASGIReceiveCallable = Callable[[], Awaitable[Any]]
ASGISendCallable = Callable[[Any], Awaitable[None]]
ASGIApp = Callable[
    [ASGIScope, ASGIReceiveCallable, ASGISendCallable],
    Awaitable[None],
]


def _normalize_prefix(prefix: str) -> str:
    """Normalize a mount prefix.

    A mounted prefix is always stored with a leading slash and without a
    trailing slash. Mounting at the root (``"/"``) is represented as an empty
    string so that stripping it from an incoming path is a no-op.
    """
    if not prefix.startswith("/"):
        prefix = "/" + prefix
    # Collapse the root mount to an empty root_path per the ASGI spec.
    prefix = prefix.rstrip("/")
    return prefix


def _build_scope(request: Request, prefix: str, sub_path: str) -> ASGIScope:
    """Build a minimal ASGI HTTP connection scope from a Sanic request.

    Only the HTTP portion of the ASGI spec is implemented (Phase 1). The
    header re-encoding mirrors how Sanic decodes headers (latin-1 for names,
    surrogateescape for values), keeping the round-trip lossless.
    """
    # Re-encode headers back into the (name, value) byte tuples an ASGI app
    # expects. ``request.headers`` is a case-insensitive multidict, so
    # ``.items()`` preserves duplicate header lines.
    headers: list[tuple[bytes, bytes]] = [
        (
            name.lower().encode("latin-1"),
            value.encode("latin-1", "surrogateescape"),
        )
        for name, value in request.headers.items()
    ]

    query_string = request.query_string.encode("latin-1", "surrogateescape")

    # ``sub_path`` is the request path with the mount prefix removed. It must
    # always start with a slash so the sub-app sees a well-formed path.
    if not sub_path.startswith("/"):
        sub_path = "/" + sub_path

    scope: ASGIScope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": request.version,
        "method": request.method,
        "scheme": request.scheme,
        "path": sub_path,
        "raw_path": sub_path.encode("latin-1", "surrogateescape"),
        "query_string": query_string,
        "root_path": prefix,
        "headers": headers,
    }

    conn_info = request.conn_info
    if conn_info is not None:
        if conn_info.server and conn_info.server_port:
            scope["server"] = (conn_info.server, conn_info.server_port)
        if conn_info.client_ip:
            scope["client"] = (conn_info.client_ip, conn_info.client_port)

    return scope


def create_asgi_mount_handler(
    asgi_app: ASGIApp, prefix: str
) -> Callable[..., Awaitable[Any]]:
    """Create a Sanic route handler that bridges to a mounted ASGI app.

    The returned handler builds a minimal ASGI HTTP scope from the incoming
    Sanic :class:`~sanic.request.Request`, drives ``asgi_app`` with
    ``receive``/``send`` callables, and streams the sub-app's response back
    out through :meth:`Request.respond`.

    Phase 1 limitations:

    * The request body is read in full and delivered in a single
      ``http.request`` event (streaming request bodies is a follow-up).
    * No websocket support and no lifespan forwarding.
    """

    async def asgi_mount_handler(request: Request, path: str = "") -> Any:
        # ``request.path`` is the full (unprefixed-stripped) path. Strip the
        # mount prefix to obtain the sub-application path.
        full_path = request.path
        if prefix and full_path.startswith(prefix):
            sub_path = full_path[len(prefix) :]
        else:
            sub_path = full_path
        if not sub_path.startswith("/"):
            sub_path = "/" + sub_path

        scope = _build_scope(request, prefix, sub_path)

        # Phase 1: read the entire request body up front and deliver it in a
        # single event. Streaming request bodies is a follow-up.
        await request.receive_body()
        body = request.body or b""

        request_sent = False
        disconnected = False

        async def receive() -> ASGIMessage:
            nonlocal request_sent, disconnected
            if not request_sent:
                request_sent = True
                return {
                    "type": "http.request",
                    "body": body,
                    "more_body": False,
                }
            # The body has been fully delivered; any subsequent poll means the
            # sub-app is waiting for more input. Signal disconnect minimally.
            disconnected = True
            return {"type": "http.disconnect"}

        response = None
        response_started = False

        async def send(message: ASGIMessage) -> None:
            nonlocal response, response_started
            message_type = message["type"]
            if message_type == "http.response.start":
                headers = message.get("headers", []) or []
                sanic_headers: dict[str, str] = {}
                # Preserve every header line, including duplicates, decoding
                # them the same way Sanic decodes inbound headers.
                header_pairs = [
                    (
                        name.decode("latin-1"),
                        value.decode("latin-1", "surrogateescape"),
                    )
                    for name, value in headers
                ]
                for name, value in header_pairs:
                    if name in sanic_headers:
                        sanic_headers[name] = f"{sanic_headers[name]},{value}"
                    else:
                        sanic_headers[name] = value
                response = await request.respond(
                    status=message["status"],
                    headers=sanic_headers,
                )
                response_started = True
            elif message_type == "http.response.body":
                if not response_started or response is None:
                    raise RuntimeError(
                        "ASGI sub-application sent a response body before "
                        "the response start event."
                    )
                more_body = message.get("more_body", False)
                await response.send(
                    message.get("body", b""),
                    end_stream=not more_body,
                )

        await asgi_app(scope, receive, send)

        # If the sub-app finished without explicitly ending the stream, make
        # sure the response is closed out.
        if response is not None:
            await response.eof()

        return response

    return asgi_mount_handler
