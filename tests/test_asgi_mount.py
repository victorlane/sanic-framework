import pytest

from sanic import Sanic


def make_echo_asgi(seen):
    """Build a tiny ASGI app that echoes method + path + body.

    It records the scope it saw into ``seen`` (a dict) so tests can assert on
    ``root_path`` and the stripped ``path``. It sets a custom header and a
    non-200 status to prove those pass through unchanged.
    """

    async def echo_asgi(scope, receive, send):
        assert scope["type"] == "http"
        seen["scope"] = scope

        body = b""
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                break
            body += message.get("body", b"")
            more_body = message.get("more_body", False)
        seen["body"] = body

        payload = b"%s %s %s" % (
            scope["method"].encode(),
            scope["path"].encode(),
            body,
        )
        await send(
            {
                "type": "http.response.start",
                "status": 201,
                "headers": [
                    (b"content-type", b"text/plain"),
                    (b"x-sub-app", b"custom-value"),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": payload,
                "more_body": False,
            }
        )

    return echo_asgi


@pytest.fixture
def mount_app():
    return Sanic("MountApp")


def test_mount_get_passthrough(mount_app):
    seen = {}
    mount_app.mount("/sub", make_echo_asgi(seen))

    _, response = mount_app.test_client.get("/sub/whatever")

    assert response.status == 201
    assert response.body == b"GET /whatever "
    assert response.headers["x-sub-app"] == "custom-value"
    assert response.headers["content-type"] == "text/plain"

    assert seen["scope"]["root_path"] == "/sub"
    assert seen["scope"]["path"] == "/whatever"


def test_mount_post_with_body(mount_app):
    seen = {}
    mount_app.mount("/sub", make_echo_asgi(seen))

    _, response = mount_app.test_client.post(
        "/sub/items", data="hello-body"
    )

    assert response.status == 201
    assert response.body == b"POST /items hello-body"
    assert seen["body"] == b"hello-body"
    assert seen["scope"]["root_path"] == "/sub"
    assert seen["scope"]["path"] == "/items"


def test_mount_empty_body(mount_app):
    seen = {}
    mount_app.mount("/sub", make_echo_asgi(seen))

    _, response = mount_app.test_client.get("/sub/thing")

    assert response.status == 201
    assert seen["body"] == b""


def test_mount_bare_prefix(mount_app):
    seen = {}
    mount_app.mount("/sub", make_echo_asgi(seen))

    _, response = mount_app.test_client.get("/sub")

    assert response.status == 201
    # The bare prefix maps to a root sub-path.
    assert seen["scope"]["path"] == "/"
    assert seen["scope"]["root_path"] == "/sub"


def test_mount_trailing_slash_prefix_normalized(mount_app):
    seen = {}
    # A trailing slash on the prefix should be stripped.
    mount_app.mount("/sub/", make_echo_asgi(seen))

    _, response = mount_app.test_client.get("/sub/deep/path")

    assert response.status == 201
    assert seen["scope"]["root_path"] == "/sub"
    assert seen["scope"]["path"] == "/deep/path"


def test_mount_at_root(mount_app):
    seen = {}
    mount_app.mount("/", make_echo_asgi(seen))

    _, response = mount_app.test_client.get("/anything/here")

    assert response.status == 201
    assert seen["scope"]["root_path"] == ""
    assert seen["scope"]["path"] == "/anything/here"


def test_mount_query_string_forwarded(mount_app):
    seen = {}
    mount_app.mount("/sub", make_echo_asgi(seen))

    _, response = mount_app.test_client.get("/sub/thing?a=1&b=2")

    assert response.status == 201
    assert seen["scope"]["query_string"] == b"a=1&b=2"
    # The path must not include the query string.
    assert seen["scope"]["path"] == "/thing"


def test_mount_headers_forwarded(mount_app):
    seen = {}
    mount_app.mount("/sub", make_echo_asgi(seen))

    _, response = mount_app.test_client.get(
        "/sub/thing", headers={"X-Custom-In": "inbound"}
    )

    assert response.status == 201
    header_dict = {
        name.decode(): value.decode()
        for name, value in seen["scope"]["headers"]
    }
    assert header_dict.get("x-custom-in") == "inbound"


def test_mount_non_200_status_passthrough(mount_app):
    async def status_asgi(scope, receive, send):
        await receive()
        await send(
            {
                "type": "http.response.start",
                "status": 404,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"not found",
            }
        )

    mount_app.mount("/api", status_asgi)

    _, response = mount_app.test_client.get("/api/missing")

    assert response.status == 404
    assert response.body == b"not found"


@pytest.mark.asyncio
async def test_mount_works_in_asgi_mode(mount_app):
    seen = {}
    mount_app.mount("/sub", make_echo_asgi(seen))

    _, response = await mount_app.asgi_client.get("/sub/whatever")

    assert response.status == 201
    assert response.text == "GET /whatever "
    assert response.headers["x-sub-app"] == "custom-value"
    assert seen["scope"]["root_path"] == "/sub"
    assert seen["scope"]["path"] == "/whatever"


@pytest.mark.asyncio
async def test_mount_asgi_mode_post_body(mount_app):
    seen = {}
    mount_app.mount("/sub", make_echo_asgi(seen))

    _, response = await mount_app.asgi_client.post(
        "/sub/items", data="payload"
    )

    assert response.status == 201
    assert seen["body"] == b"payload"
    assert response.text == "POST /items payload"
