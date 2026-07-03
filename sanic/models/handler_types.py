from asyncio.events import AbstractEventLoop
from collections.abc import Awaitable, Coroutine
from typing import Any, Callable, TypeVar

import sanic

from sanic import request
from sanic.response import BaseHTTPResponse, HTTPResponse


Sanic = TypeVar("Sanic", bound="sanic.Sanic")
Request = TypeVar("Request", bound="request.Request")

MiddlewareResponse = (
    HTTPResponse | None | Coroutine[Any, Any, HTTPResponse | None]
)
RequestMiddlewareType = Callable[[Request], MiddlewareResponse]
ResponseMiddlewareType = Callable[
    [Request, BaseHTTPResponse], MiddlewareResponse
]
ErrorMiddlewareType = Callable[
    [Request, BaseException], Coroutine[Any, Any, None] | None
]
MiddlewareType = RequestMiddlewareType | ResponseMiddlewareType
ListenerType = (
    Callable[[Sanic], Coroutine[Any, Any, None] | None]
    | Callable[[Sanic, AbstractEventLoop], Coroutine[Any, Any, None] | None]
)
# Route handlers may be sync or async, and may return a response object or
# ``None`` (e.g. when responding early via ``request.respond()``).
RouteHandler = Callable[
    ..., HTTPResponse | None | Awaitable[HTTPResponse | None]
]
SignalHandler = Callable[..., Coroutine[Any, Any, None]]
