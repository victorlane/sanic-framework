import asyncio
import logging
import sys

from asyncio.tasks import Task
from contextlib import suppress
from unittest.mock import Mock, call

import pytest

from sanic.app import Sanic
from sanic.application.state import ApplicationServerInfo, ServerStage
from sanic.response import empty


try:
    from unittest.mock import AsyncMock
except ImportError:
    from tests.asyncmock import AsyncMock  # type: ignore

pytestmark = pytest.mark.asyncio


async def dummy(n=0):
    for _ in range(n):
        await asyncio.sleep(1)
    return True


@pytest.fixture(autouse=True)
def mark_app_running(app: Sanic):
    app.state.server_info.append(
        ApplicationServerInfo(
            stage=ServerStage.SERVING, settings={}, server=AsyncMock()
        )
    )


async def test_add_task_returns_task(app: Sanic):
    task = app.add_task(dummy())

    assert isinstance(task, Task)
    assert len(app._task_registry) == 0


async def test_add_task_with_name(app: Sanic):
    task = app.add_task(dummy(), name="dummy")

    assert isinstance(task, Task)
    assert len(app._task_registry) == 1
    assert task is app.get_task("dummy")

    for task in app.tasks:
        assert task in app._task_registry.values()


async def test_cancel_task(app: Sanic):
    task = app.add_task(dummy(3), name="dummy")

    assert task
    assert not task.done()
    assert not task.cancelled()

    await asyncio.sleep(0.1)

    assert not task.done()
    assert not task.cancelled()

    await app.cancel_task("dummy")

    assert task.cancelled()


async def test_purge_tasks(app: Sanic):
    app.add_task(dummy(3), name="dummy")

    await app.cancel_task("dummy")

    assert len(app._task_registry) == 1

    app.purge_tasks()

    assert len(app._task_registry) == 0


async def test_purge_tasks_with_create_task(app: Sanic):
    app.add_task(asyncio.create_task(dummy(3)), name="dummy")

    await app.cancel_task("dummy")

    assert len(app._task_registry) == 1

    app.purge_tasks()

    assert len(app._task_registry) == 0


def test_shutdown_tasks_on_app_stop():
    class TestSanic(Sanic):
        shutdown_tasks = Mock()

    app = TestSanic("Test")

    @app.route("/")
    async def handler(_):
        return empty()

    app.test_client.get("/")

    app.shutdown_tasks.call_args == [
        call(timeout=0),
        call(15.0),
    ]


async def test_shutdown_tasks_allows_cancelled_task_cleanup(app: Sanic):
    cleanup_done = False

    async def with_cleanup():
        nonlocal cleanup_done
        try:
            await asyncio.sleep(10)
        finally:
            await asyncio.sleep(0.2)
            cleanup_done = True

    app.add_task(with_cleanup(), name="cleanup_task")
    await asyncio.sleep(0.05)

    loop = asyncio.get_running_loop()
    start = loop.time()
    shutdown = app.shutdown_tasks(timeout=5)

    assert shutdown is not None
    await shutdown

    assert cleanup_done is True
    assert loop.time() - start < 5
    assert len(app._task_registry) == 0


async def test_shutdown_tasks_warns_about_uncompleted_tasks(
    app: Sanic, caplog
):
    allow_cancel = False

    async def stubborn():
        while True:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                if allow_cancel:
                    raise

    task = app.add_task(stubborn(), name="stubborn_task")
    await asyncio.sleep(0.05)

    loop = asyncio.get_running_loop()
    start = loop.time()
    with caplog.at_level(logging.WARNING, logger="sanic.error"):
        shutdown = app.shutdown_tasks(timeout=0.3)
        assert shutdown is not None
        await shutdown

    assert loop.time() - start < 5
    assert any(
        record.levelno == logging.WARNING
        and "stubborn_task" in record.getMessage()
        for record in caplog.records
    )

    # Let the task actually terminate to avoid dangling task warnings
    allow_cancel = True
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="Task.cancelling() requires Python 3.11+",
)
async def test_shutdown_tasks_twice_does_not_interrupt_cleanup(app: Sanic):
    # Mimics the server shutdown path, where app.stop() calls
    # shutdown_tasks(timeout=0) and the server cleanup later calls
    # shutdown_tasks() again with the graceful timeout. The second
    # call must not re-cancel tasks that are running their cleanup.
    cleanup_done = False

    async def with_cleanup():
        nonlocal cleanup_done
        try:
            await asyncio.sleep(10)
        finally:
            await asyncio.sleep(0.2)
            cleanup_done = True

    app.add_task(with_cleanup(), name="cleanup_task")
    await asyncio.sleep(0.05)

    first = app.shutdown_tasks(timeout=0)
    assert first is not None
    await first
    # Give the cancelled task a chance to enter its cleanup
    await asyncio.sleep(0.05)

    second = app.shutdown_tasks(timeout=5)
    assert second is not None
    await second

    assert cleanup_done is True
    assert len(app._task_registry) == 0


def test_shutdown_tasks_no_running_loop(app: Sanic):
    cleanup_done = False

    async def with_cleanup():
        nonlocal cleanup_done
        try:
            await asyncio.sleep(10)
        finally:
            await asyncio.sleep(0.1)
            cleanup_done = True

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        task = loop.create_task(with_cleanup(), name="cleanup_task")
        app._task_registry["cleanup_task"] = task
        loop.run_until_complete(asyncio.sleep(0.05))

        ret = app.shutdown_tasks(timeout=5)

        assert ret is None
        assert cleanup_done is True
        assert len(app._task_registry) == 0
    finally:
        asyncio.set_event_loop(None)
        loop.close()


async def test_task_result_is_preserved(app: Sanic):
    async def return_value(x):
        await asyncio.sleep(0)
        return x

    task = app.add_task(return_value(42), name="return_42")

    result = await task

    assert result == 42
    assert task.result() == 42


async def test_task_result_with_callable(app: Sanic):
    async def coro_with_app(app):
        await asyncio.sleep(0)
        return app.name

    task = app.add_task(coro_with_app, name="return_app_name")

    result = await task

    assert result == app.name
    assert task.result() == app.name
