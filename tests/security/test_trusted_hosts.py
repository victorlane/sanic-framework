import pytest

from sanic.response import text
from sanic.security import install_trusted_hosts
from sanic.security.trusted_hosts import host_matches, is_trusted_host


@pytest.mark.parametrize(
    "hostname,pattern,expected",
    [
        ("example.com", "example.com", True),
        ("Example.COM", "example.com", True),
        ("example.com", "other.com", False),
        ("a.example.com", "*.example.com", True),
        ("a.b.example.com", "*.example.com", True),
        ("example.com", "*.example.com", False),
        ("notexample.com", "*.example.com", False),
        ("evilexample.com", "*.example.com", False),
    ],
)
def test_host_matches(hostname, pattern, expected):
    assert host_matches(hostname, pattern) is expected


def test_is_trusted_host_ignores_port():
    assert is_trusted_host("example.com:8000", ["example.com"]) is True
    assert is_trusted_host("a.example.com:443", ["*.example.com"]) is True
    assert is_trusted_host("evil.com:80", ["example.com"]) is False


def test_is_trusted_host_empty_hostname():
    assert is_trusted_host("", ["example.com"]) is False


def test_disabled_by_default(app):
    install_trusted_hosts(app)

    @app.get("/")
    async def handler(request):
        return text("ok")

    # No TRUSTED_HOSTS configured -> everything allowed
    _, response = app.test_client.get("/", headers={"Host": "anything.com"})
    assert response.status == 200


def test_allow_exact(app):
    app.config.TRUSTED_HOSTS = ["example.com"]
    install_trusted_hosts(app)

    @app.get("/")
    async def handler(request):
        return text("ok")

    _, response = app.test_client.get("/", headers={"Host": "example.com"})
    assert response.status == 200


def test_reject_untrusted(app):
    app.config.TRUSTED_HOSTS = ["example.com"]
    install_trusted_hosts(app)

    @app.get("/")
    async def handler(request):
        return text("ok")

    _, response = app.test_client.get("/", headers={"Host": "evil.com"})
    assert response.status == 400


def test_wildcard_allow(app):
    app.config.TRUSTED_HOSTS = ["*.example.com"]
    install_trusted_hosts(app)

    @app.get("/")
    async def handler(request):
        return text("ok")

    _, response = app.test_client.get(
        "/", headers={"Host": "api.example.com"}
    )
    assert response.status == 200

    _, response = app.test_client.get(
        "/", headers={"Host": "example.com"}
    )
    assert response.status == 400
