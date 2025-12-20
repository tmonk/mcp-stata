import queue
import threading
import time
from typing import Any, Awaitable, Callable, Optional

import anyio


_SENTINEL = object()


class StreamBuffer:
    def __init__(
        self,
        *,
        max_total_chars: int = 2_000_000,
        truncation_marker: str = "\n... (output truncated)\n",
    ):
        self._lock = threading.Lock()
        self._parts: list[str] = []
        self._total_chars = 0
        self._max_total_chars = max_total_chars
        self._truncation_marker = truncation_marker
        self._truncated = False

    def write(self, data: Any) -> int:
        text = self._normalize(data)
        if not text:
            return 0

        with self._lock:
            if self._truncated:
                return len(text)

            remaining = self._max_total_chars - self._total_chars
            if remaining <= 0:
                self._parts.append(self._truncation_marker)
                self._total_chars += len(self._truncation_marker)
                self._truncated = True
                return len(text)

            if len(text) <= remaining:
                self._parts.append(text)
                self._total_chars += len(text)
                return len(text)

            self._parts.append(text[:remaining])
            self._parts.append(self._truncation_marker)
            self._total_chars += remaining + len(self._truncation_marker)
            self._truncated = True
            return len(text)

    def get_value(self) -> str:
        with self._lock:
            return "".join(self._parts)

    @staticmethod
    def _normalize(data: Any) -> str:
        if data is None:
            return ""
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return str(data)


class StreamingTeeIO:
    def __init__(
        self,
        buffer: StreamBuffer,
        q: queue.Queue,
        *,
        max_fragment_chars: int = 4000,
        on_chunk_callback=None,
    ):
        self._buffer = buffer
        self._queue = q
        self._max_fragment_chars = max_fragment_chars
        self._closed = False
        self._lock = threading.Lock()
        self._on_chunk_callback = on_chunk_callback

    def write(self, data: Any) -> int:
        text = StreamBuffer._normalize(data)
        if not text:
            return 0

        n = self._buffer.write(text)

        # Call chunk callback for graph detection
        if self._on_chunk_callback:
            try:
                self._on_chunk_callback(text)
            except Exception:
                # Don't let callback errors break streaming
                pass

        with self._lock:
            if self._closed:
                return n
            if len(text) <= self._max_fragment_chars:
                self._queue.put_nowait(text)
            else:
                for i in range(0, len(text), self._max_fragment_chars):
                    self._queue.put_nowait(text[i : i + self._max_fragment_chars])
        return n

    def flush(self) -> None:
        return

    def isatty(self) -> bool:
        return False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._queue.put_nowait(_SENTINEL)


class TailBuffer:
    def __init__(self, *, max_chars: int = 8000):
        self._lock = threading.Lock()
        self._parts: list[str] = []
        self._total = 0
        self._max_chars = max_chars

    def append(self, data: Any) -> None:
        text = StreamBuffer._normalize(data)
        if not text:
            return

        with self._lock:
            self._parts.append(text)
            self._total += len(text)

            if self._total <= self._max_chars:
                return

            # Trim from the left until we are within budget.
            over = self._total - self._max_chars
            while over > 0 and self._parts:
                head = self._parts[0]
                if len(head) <= over:
                    self._parts.pop(0)
                    self._total -= len(head)
                    over = self._total - self._max_chars
                    continue

                self._parts[0] = head[over:]
                self._total -= over
                over = 0

    def get_value(self) -> str:
        with self._lock:
            return "".join(self._parts)


class FileTeeIO:
    def __init__(self, file_obj, tail: TailBuffer):
        self._file = file_obj
        self._tail = tail
        self._lock = threading.Lock()
        self._closed = False

    def write(self, data: Any) -> int:
        text = StreamBuffer._normalize(data)
        if not text:
            return 0

        with self._lock:
            if self._closed:
                return len(text)

            self._tail.append(text)
            self._file.write(text)

            if "\n" in text:
                try:
                    self._file.flush()
                except Exception:
                    pass
            return len(text)

    def flush(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._file.flush()
            except Exception:
                return

    def isatty(self) -> bool:
        return False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._file.flush()
            except Exception:
                pass
            try:
                self._file.close()
            except Exception:
                pass


async def drain_queue_and_notify(
    q: queue.Queue,
    notify_log: Callable[[str], Awaitable[None]],
    *,
    min_interval_ms: int = 200,
    max_chunk_chars: int = 4000,
    on_chunk: Optional[Callable[[str], Awaitable[None]]] = None,
) -> None:
    buf: list[str] = []
    buf_len = 0
    last_send = time.monotonic()

    async def flush() -> None:
        nonlocal buf, buf_len, last_send
        if not buf:
            return
        chunk = "".join(buf)
        buf = []
        buf_len = 0
        if on_chunk is not None:
            await on_chunk(chunk)
        await notify_log(chunk)
        last_send = time.monotonic()

    while True:
        item = None
        try:
            item = q.get_nowait()
        except queue.Empty:
            now = time.monotonic()
            if buf and (now - last_send) * 1000 >= min_interval_ms:
                await flush()
            await anyio.sleep(min_interval_ms / 1000)
            continue

        if item is _SENTINEL:
            break

        text = StreamBuffer._normalize(item)
        if not text:
            continue

        buf.append(text)
        buf_len += len(text)

        now = time.monotonic()
        if buf_len >= max_chunk_chars or (now - last_send) * 1000 >= min_interval_ms:
            await flush()

    await flush()
