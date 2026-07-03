from sanic.response import text
from sanic.security import install_security_headers
from sanic.security.headers import security_headers_middleware


def test_default_headers_applied(app):
    install_security_headers(app)

    @app.get("/")
    async def handler(request):
        return text("ok")

    _, response = app.test_client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert (
        response.headers["Referrer-Policy"]
        == "strict-origin-when-cross-origin"
    )
    # No CSP by default
    assert "Content-Security-Policy" not in response.headers
    # HSTS off by default (and this is plain http anyway)
    assert "Strict-Transport-Security" not in response.headers


def test_setdefault_does_not_overwrite(app):
    install_security_headers(app)

    @app.get("/")
    async def handler(request):
        resp = text("ok")
        resp.headers["X-Frame-Options"] = "SAMEORIGIN"
        return resp

    _, response = app.test_client.get("/")
    # Handler value preserved, not overwritten by middleware
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    # Other headers still applied
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_config_disables_individual_headers(app):
    app.config.SECURITY_HEADERS_CONTENT_TYPE_OPTIONS = False
    app.config.SECURITY_HEADERS_FRAME_OPTIONS = None
    app.config.SECURITY_HEADERS_REFERRER_POLICY = None
    install_security_headers(app)

    @app.get("/")
    async def handler(request):
        return text("ok")

    _, response = app.test_client.get("/")
    assert "X-Content-Type-Options" not in response.headers
    assert "X-Frame-Options" not in response.headers
    assert "Referrer-Policy" not in response.headers


def test_csp_applied_when_configured(app):
    app.config.SECURITY_HEADERS_CONTENT_SECURITY_POLICY = "default-src 'self'"
    install_security_headers(app)

    @app.get("/")
    async def handler(request):
        return text("ok")

    _, response = app.test_client.get("/")
    assert (
        response.headers["Content-Security-Policy"] == "default-src 'self'"
    )


def test_hsts_only_on_https_and_when_enabled(app):
    app.config.SECURITY_HEADERS_HSTS = True
    app.config.PROXIES_COUNT = 1
    install_security_headers(app)

    @app.get("/")
    async def handler(request):
        return text("ok")

    # http -> no HSTS even though enabled
    _, response = app.test_client.get("/")
    assert "Strict-Transport-Security" not in response.headers

    # https (via proxy header) -> HSTS present
    _, response = app.test_client.get(
        "/",
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "1.2.3.4"},
    )
    hsts = response.headers["Strict-Transport-Security"]
    assert "max-age=31536000" in hsts
    assert "includeSubDomains" in hsts
    assert "preload" not in hsts


def test_hsts_not_sent_on_https_when_disabled(app):
    app.config.SECURITY_HEADERS_HSTS = False
    app.config.PROXIES_COUNT = 1
    install_security_headers(app)

    @app.get("/")
    async def handler(request):
        return text("ok")

    _, response = app.test_client.get(
        "/",
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "1.2.3.4"},
    )
    assert "Strict-Transport-Security" not in response.headers


def test_hsts_options_in_value(app):
    app.config.SECURITY_HEADERS_HSTS = True
    app.config.SECURITY_HEADERS_HSTS_MAX_AGE = 100
    app.config.SECURITY_HEADERS_HSTS_INCLUDE_SUBDOMAINS = False
    app.config.SECURITY_HEADERS_HSTS_PRELOAD = True
    app.config.PROXIES_COUNT = 1
    install_security_headers(app)

    @app.get("/")
    async def handler(request):
        return text("ok")

    _, response = app.test_client.get(
        "/",
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "1.2.3.4"},
    )
    hsts = response.headers["Strict-Transport-Security"]
    assert hsts == "max-age=100; preload"


def test_middleware_factory_returns_callable(app):
    mw = security_headers_middleware(app.config)
    assert callable(mw)
