import queue
import threading

import anyio

from mcp_stata.streaming_io import StreamBuffer, StreamingTeeIO, drain_queue_and_notify


def test_stream_buffer_truncation():
    buf = StreamBuffer(max_total_chars=10, truncation_marker="<TRUNC>")
    buf.write("12345")
    buf.write("67890")
    buf.write("EXTRA")
    out = buf.get_value()
    assert out.startswith("1234567890")
    assert "<TRUNC>" in out


def test_streaming_tee_writes_to_queue_and_buffer():
    q: queue.Queue = queue.Queue()
    buf = StreamBuffer(max_total_chars=1000)
    tee = StreamingTeeIO(buf, q, max_fragment_chars=1000)

    tee.write("hello")
    tee.close()

    assert "hello" in buf.get_value()
    first = q.get_nowait()
    assert first == "hello"


def test_drain_queue_coalesces_and_notifies():
    q: queue.Queue = queue.Queue()
    buf = StreamBuffer(max_total_chars=1000)
    tee = StreamingTeeIO(buf, q, max_fragment_chars=1000)

    received: list[str] = []

    async def notify_log(chunk: str) -> None:
        received.append(chunk)

    async def main():
        tee.write("a")
        tee.write("b")
        tee.write("c")
        tee.close()
        await drain_queue_and_notify(q, notify_log, min_interval_ms=0, max_chunk_chars=1000)

    anyio.run(main)

    assert "".join(received) == "abc"


def test_thread_safety_concurrent_writes():
    q: queue.Queue = queue.Queue()
    buf = StreamBuffer(max_total_chars=100000)
    tee = StreamingTeeIO(buf, q, max_fragment_chars=1000)

    def worker(prefix: str):
        for i in range(200):
            tee.write(f"{prefix}{i}\n")

    threads = [threading.Thread(target=worker, args=(f"t{n}-",)) for n in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    tee.close()

    received: list[str] = []

    async def notify_log(chunk: str) -> None:
        received.append(chunk)

    async def main():
        await drain_queue_and_notify(q, notify_log, min_interval_ms=0, max_chunk_chars=4000)

    anyio.run(main)

    out = buf.get_value()
    # Basic sanity: some known prefixes should exist
    assert "t0-" in out
    assert "t4-" in out
    assert len(out) > 0
