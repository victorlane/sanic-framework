"""Optional, ext-dependent conveniences for Sanic.

This package collects thin, well-documented helpers that make common
application patterns turnkey. Everything here is *optional*: the core
framework never imports this package, and importing it never requires
`sanic-ext` to be installed. Helpers that genuinely need `sanic-ext`
import it lazily and raise a clear, actionable error if it is missing.

Two kinds of helpers live here:

- :mod:`sanic.contrib.auth` — pure-core auth primitives (token
  retrieval and ``@protected`` / ``@scoped`` decorators) that only
  depend on :class:`~sanic.request.Request`, ``request.ctx`` and the
  existing exceptions. External JWT/session plugins plug into this seam.
- :mod:`sanic.contrib.validation` — a thin shim over ``sanic-ext``'s
  validation so it is discoverable from core with a clean error message
  when the extra is not installed.

Dependency injection (DI), briefly
----------------------------------
Dependency injection means a request handler *declares* the typed values
it needs as parameters, and the framework *supplies* them per request —
you do not construct or look them up yourself. This keeps handlers
focused on behaviour and makes the wiring testable and swappable.

Sanic's full DI system is provided by ``sanic-ext``. Register a provider
with ``app.ext.add_dependency(...)`` and then simply annotate the handler
parameter with that type; ``sanic-ext`` resolves and passes it in::

    from sanic import Sanic, text
    from sanic_ext import Extend

    app = Sanic("di-example")
    Extend(app)

    class Db:  # your real dependency
        ...

    app.ext.add_dependency(Db)  # framework will construct/supply it

    @app.get("/")
    async def handler(request, db: Db):  # declared need, supplied per request
        return text(type(db).__name__)

See the ``sanic-ext`` documentation for constructor injection, factory
functions and request-scoped dependencies.
"""

__all__ = ["auth", "validation"]
