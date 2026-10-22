"""Starting coroutines from Qt slots (qasync runs asyncio on Qt's event loop)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine

log = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()


def spawn(coro: Coroutine[Any, Any, Any], on_error: Callable[[BaseException], None] | None = None,
          on_done: Callable[[Any], None] | None = None) -> asyncio.Task:
    """Run `coro` in the background - the equivalent of a fire-and-forget promise with
    .then / .catch. A reference is kept until it finishes (asyncio only keeps weak ones).
    Without on_error, a failure is logged rather than lost."""
    task = asyncio.ensure_future(coro)
    _tasks.add(task)

    def done(t: asyncio.Task) -> None:
        _tasks.discard(t)
        if t.cancelled():
            return
        err = t.exception()
        if err is not None:
            if on_error is not None:
                on_error(err)
            else:
                log.error("background task failed", exc_info=err)
        elif on_done is not None:
            on_done(t.result())

    task.add_done_callback(done)
    return task


async def cancel_all() -> None:
    """Cancel every other spawn()ed task and wait for them to finish - done before the app
    quits, while the loop still runs (asyncio's own cleanup after Qt has quit would crash).
    The transports' own tasks are stopped by their close()."""
    me = asyncio.current_task()
    others = [t for t in _tasks if t is not me]
    for t in others:
        t.cancel()
    await asyncio.gather(*others, return_exceptions=True)
