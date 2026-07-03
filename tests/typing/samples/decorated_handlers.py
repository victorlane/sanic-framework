from sanic import Request, Sanic
from sanic.response import HTTPResponse, text


app = Sanic("test")


@app.get("/")
async def get_handler(request: Request) -> HTTPResponse:
    return text("Hello, World!")


reveal_type(get_handler)  # noqa


@app.websocket("/ws")
async def ws_handler(request: Request, ws) -> None:
    await ws.send("Hello, World!")


reveal_type(ws_handler)  # noqa
