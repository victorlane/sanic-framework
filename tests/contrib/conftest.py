import sys

from importlib import import_module, reload

import pytest


@pytest.fixture(autouse=True)
def mock_sanic_ext():
    """Override the repo-wide autouse fixture that replaces ``sanic_ext``.

    The root ``tests/conftest.py`` installs a ``MagicMock`` in
    ``sys.modules["sanic_ext"]`` for every test. The contrib validation
    tests need the *real* ``sanic-ext`` (it is installed in this venv), so
    here we ensure the genuine module is loaded instead of the mock.
    """
    sys.modules.pop("sanic_ext", None)
    try:
        module = import_module("sanic_ext")
        # If a mock had been imported earlier in the session, force a fresh
        # import of the real package.
        if not getattr(module, "__file__", None):
            module = reload(module)
    except ImportError:
        module = None
    yield module
