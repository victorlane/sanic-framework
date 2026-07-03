import builtins

from dataclasses import dataclass

import pytest

from sanic import Sanic, json
from sanic.contrib import validation


sanic_ext = pytest.importorskip("sanic_ext")


@dataclass
class Person:
    name: str
    age: int


@pytest.fixture
def ext_app():
    app = Sanic("validation-test")
    sanic_ext.Extend(app)
    return app


def test_validate_body_binds_valid_input(ext_app):
    @ext_app.post("/people")
    @validation.validate_body(Person)
    async def create(request, body: Person):
        return json({"name": body.name, "age": body.age})

    _, response = ext_app.test_client.post(
        "/people", json={"name": "alice", "age": 30}
    )
    assert response.status == 200
    assert response.json == {"name": "alice", "age": 30}


def test_validate_body_400_on_bad_input(ext_app):
    @ext_app.post("/people")
    @validation.validate_body(Person)
    async def create(request, body: Person):
        return json({"name": body.name})

    # Missing required "age" field -> validation failure -> 400.
    _, response = ext_app.test_client.post(
        "/people", json={"name": "alice"}
    )
    assert response.status == 400


def test_validate_query_binds_valid_input(ext_app):
    @dataclass
    class Filter:
        q: str

    @ext_app.get("/search")
    @validation.validate_query(Filter)
    async def search(request, query: Filter):
        return json({"q": query.q})

    _, response = ext_app.test_client.get("/search?q=hello")
    assert response.status == 200
    assert response.json == {"q": "hello"}


def test_clear_import_error_when_ext_missing(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sanic_ext" or name.startswith("sanic_ext."):
            raise ImportError("No module named 'sanic_ext'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ImportError) as exc_info:
        validation.validate_body(Person)
    assert "pip install sanic[ext]" in str(exc_info.value)

    with pytest.raises(ImportError) as exc_info:
        validation.validate_query(Person)
    assert "pip install sanic[ext]" in str(exc_info.value)
