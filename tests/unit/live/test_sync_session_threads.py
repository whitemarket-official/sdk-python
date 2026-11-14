"""The threaded `LiveSession`: `close()` wakes a blocked consumer, and no thread outlives it."""

import gc
import threading
import time
from collections.abc import Callable

from whitemarket._runtime.secret import Secret
from whitemarket.live.events import LiveEvent
from whitemarket.live.options import LiveOptions, LiveTransport
from whitemarket.live.session import LiveSession

THREAD_NAME = "whitemarket-live"


class _Tokens:
    def access_token(self) -> Secret:
        return Secret("synthetic.token.value")

    def refresh(self) -> Secret:
        return self.access_token()


def _session() -> LiveSession:
    # Nothing listens on the discard port: every attempt fails fast and the session backs off.
    session = LiveSession(
        tokens=_Tokens(),
        transport=LiveTransport.SSE,
        ws_url="",
        sse_url="http://localhost:9/sse",
        user_agent="test-agent/1",
        options=LiveOptions(connect_timeout=1),
    )
    session.on_error(lambda error: None)
    return session


def _live_threads() -> list[str]:
    return [t.name for t in threading.enumerate() if t.name == THREAD_NAME]


def _wait_until(condition: Callable[[], bool], seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_close_from_another_thread_wakes_a_consumer_blocked_in_a_backoff() -> None:
    session = _session()
    result: list[LiveEvent | BaseException | None] = []

    def consumer() -> None:
        try:
            result.append(session.poll(None))
        except BaseException as error:
            result.append(error)

    thread = threading.Thread(target=consumer, daemon=True)
    thread.start()
    time.sleep(1.5)  # a few failed attempts: the consumer waits in a backoff
    assert thread.is_alive()
    session.close()
    thread.join(10)
    assert not thread.is_alive()
    assert result == [None]
    assert _live_threads() == []


def test_a_session_dropped_without_close_leaves_no_thread() -> None:
    session = _session()
    assert session.poll(0.1) is None
    assert _live_threads() == [THREAD_NAME]
    del session
    gc.collect()
    assert _wait_until(lambda: _live_threads() == [])
