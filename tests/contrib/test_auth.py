import pytest

from sanic import Sanic, json, text
from sanic.contrib.auth import get_token, protected, scoped


@pytest.fixture
def auth_app():
    app = Sanic("auth-test")
    return app


def test_get_token_from_header(auth_app):
    captured = {}

    @auth_app.get("/")
    async def handler(request):
        captured["token"] = get_token(request)
        return text("ok")

    auth_app.test_client.get(
        "/", headers={"Authorization": "Bearer abc123"}
    )
    assert captured["token"] == "abc123"


def test_get_token_header_scheme_mismatch_is_ignored(auth_app):
    captured = {}

    @auth_app.get("/")
    async def handler(request):
        captured["token"] = get_token(request)
        return text("ok")

    # Anchored scheme match: "NotBearer" must not be treated as Bearer.
    auth_app.test_client.get(
        "/", headers={"Authorization": "NotBearer abc123"}
    )
    assert captured["token"] is None


def test_get_token_custom_scheme(auth_app):
    captured = {}

    @auth_app.get("/")
    async def handler(request):
        captured["token"] = get_token(request, scheme="Token")
        return text("ok")

    auth_app.test_client.get(
        "/", headers={"Authorization": "Token xyz"}
    )
    assert captured["token"] == "xyz"


def test_get_token_from_cookie(auth_app):
    captured = {}

    @auth_app.get("/")
    async def handler(request):
        captured["token"] = get_token(request, cookie="session")
        return text("ok")

    auth_app.test_client.get("/", cookies={"session": "cookieval"})
    assert captured["token"] == "cookieval"


def test_get_token_from_query(auth_app):
    captured = {}

    @auth_app.get("/")
    async def handler(request):
        captured["token"] = get_token(request, query="access_token")
        return text("ok")

    auth_app.test_client.get("/?access_token=queryval")
    assert captured["token"] == "queryval"


def test_get_token_none_when_absent(auth_app):
    captured = {}

    @auth_app.get("/")
    async def handler(request):
        captured["token"] = get_token(
            request, cookie="session", query="access_token"
        )
        return text("ok")

    auth_app.test_client.get("/")
    assert captured["token"] is None


def test_protected_allows_with_valid_verify_and_sets_user(auth_app):
    async def verify(request):
        return {"id": 7, "name": "alice"}

    @auth_app.get("/me")
    @protected(verify)
    async def me(request):
        return json({"user": request.ctx.user})

    _, response = auth_app.test_client.get("/me")
    assert response.status == 200
    assert response.json["user"] == {"id": 7, "name": "alice"}


def test_protected_401_on_falsy(auth_app):
    async def verify(request):
        return None

    @auth_app.get("/me")
    @protected(verify)
    async def me(request):
        return text("secret")

    _, response = auth_app.test_client.get("/me")
    assert response.status == 401


def test_protected_401_on_raise(auth_app):
    async def verify(request):
        raise ValueError("boom")

    @auth_app.get("/me")
    @protected(verify)
    async def me(request):
        return text("secret")

    _, response = auth_app.test_client.get("/me")
    assert response.status == 401


def test_scoped_allows_when_present(auth_app):
    async def verify(request):
        return {"scopes": ["read", "admin"]}

    @auth_app.get("/admin")
    @protected(verify)
    @scoped("admin", get_scopes=lambda r: r.ctx.user["scopes"])
    async def admin(request):
        return text("ok")

    _, response = auth_app.test_client.get("/admin")
    assert response.status == 200
    assert response.text == "ok"


def test_scoped_403_when_missing(auth_app):
    async def verify(request):
        return {"scopes": ["read"]}

    @auth_app.get("/admin")
    @protected(verify)
    @scoped("admin", get_scopes=lambda r: r.ctx.user["scopes"])
    async def admin(request):
        return text("ok")

    _, response = auth_app.test_client.get("/admin")
    assert response.status == 403


def test_scoped_multiple_required(auth_app):
    async def verify(request):
        return {"scopes": ["read"]}

    @auth_app.get("/multi")
    @protected(verify)
    @scoped(
        ["read", "write"], get_scopes=lambda r: r.ctx.user["scopes"]
    )
    async def multi(request):
        return text("ok")

    _, response = auth_app.test_client.get("/multi")
    assert response.status == 403
