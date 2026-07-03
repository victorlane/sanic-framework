"""Ergonomic, discoverable shims over ``sanic-ext``'s validation.

``sanic-ext`` already provides full request validation (dataclasses,
``pydantic`` models, ...) plus OpenAPI generation via its ``validate``
decorator. This module does *not* reimplement any of that. It only
exposes two intent-revealing decorators — :func:`validate_body` and
:func:`validate_query` — that lazily delegate to ``sanic-ext`` and raise
a clear, actionable error when the ``ext`` extra is not installed::

    ImportError: sanic-ext is required for validation; pip install sanic[ext]

Install with ``pip install sanic[ext]`` to enable them.
"""

from __future__ import annotations

from typing import Callable


__all__ = ["validate_body", "validate_query"]

_MISSING_MESSAGE = (
    "sanic-ext is required for validation; pip install sanic[ext]"
)


def _get_validate() -> Callable:
    """Import ``sanic_ext.validate`` lazily with a clear error."""
    try:
        from sanic_ext import validate
    except ImportError as e:  # pragma: no cover - exercised via monkeypatch
        raise ImportError(_MISSING_MESSAGE) from e
    return validate


def validate_body(model: type) -> Callable[[Callable], Callable]:
    """Validate the request body against ``model``.

    A thin shim over ``sanic-ext``'s ``validate`` decorator: it validates
    the incoming JSON (or form) body against ``model`` and injects the
    parsed instance into the handler as the ``body`` argument. See the
    ``sanic-ext`` documentation for the full behaviour and OpenAPI
    integration.

    Args:
        model (type): A dataclass or ``pydantic`` model describing the
            expected body.

    Returns:
        Callable: A decorator that wraps a request handler.

    Raises:
        ImportError: If ``sanic-ext`` is not installed.
    """
    validate = _get_validate()
    return validate(json=model)


def validate_query(model: type) -> Callable[[Callable], Callable]:
    """Validate the query string against ``model``.

    A thin shim over ``sanic-ext``'s ``validate`` decorator: it validates
    the request query string against ``model`` and injects the parsed
    instance into the handler as the ``query`` argument.

    Args:
        model (type): A dataclass or ``pydantic`` model describing the
            expected query parameters.

    Returns:
        Callable: A decorator that wraps a request handler.

    Raises:
        ImportError: If ``sanic-ext`` is not installed.
    """
    validate = _get_validate()
    return validate(query=model)
