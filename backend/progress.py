"""
Per-run progress reporting for the pipeline.

The SSE endpoint used to swap the process-global sys.stdout to capture print()s,
which also captured every other thread's output, including other users' requests
(BUG-12). Pipeline code now calls report(); a run that wants the messages installs
a sink with progress_sink() in its own thread/context. Without a sink, report()
falls back to print() (CLI use, logs).
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Optional

_sink: ContextVar[Optional[Callable[[str], None]]] = ContextVar("progress_sink", default=None)


def report(msg="") -> None:
    sink = _sink.get()
    if sink is None:
        print(msg)
        return
    for line in str(msg).splitlines():
        if line.strip():
            sink(line.strip())


@contextmanager
def progress_sink(fn: Callable[[str], None]):
    token = _sink.set(fn)
    try:
        yield
    finally:
        _sink.reset(token)
