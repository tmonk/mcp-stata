from __future__ import annotations
import os
import uuid
import logging
import asyncio
import atexit
import multiprocessing
from typing import Any, Dict, List, Optional, Callable, Awaitable
from multiprocessing.connection import Connection
from datetime import datetime, timezone

from mcp_stata.models import SessionInfo, CommandResponse

logger = logging.getLogger("mcp_stata.sessions")

# Use 'spawn' for process creation to ensure thread-safety and Stata/Rust compatibility.
# Re-exposed at module level so tests can patch these references.
_ctx = multiprocessing.get_context("spawn")
Process = _ctx.Process
Pipe = _ctx.Pipe

class StataSession:
    def __init__(self, session_id: str):
        self.id = session_id
        self.status = "starting"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.pid: Optional[int] = None
        
        self._parent_conn, self._child_conn = Pipe()
        self._process = Process(target=self._run_worker, args=(self._child_conn,))
        self._process.daemon = True
        self._process.start()
        
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._log_listeners: Dict[str, List[Callable[[str], Awaitable[None]]]] = {}
        self._progress_listeners: Dict[str, List[Callable[[float, Optional[float], Optional[str]], Awaitable[None]]]] = {}
        
        self._listener_running = True
        self._listener_task = asyncio.create_task(self._listen_to_worker())

    def _run_worker(self, conn: Connection):
        from mcp_stata.worker import main
        main(conn)

    async def _listen_to_worker(self):
        loop = asyncio.get_running_loop()
        try:
            while self._listener_running:
                # Use poll with timeout to allow checking self._listener_running and asyncio cancellation
                if await loop.run_in_executor(None, self._parent_conn.poll, 0.2):
                    try:
                        msg = await loop.run_in_executor(None, self._parent_conn.recv)
                        await self._handle_worker_msg(msg)
                    except (EOFError, ConnectionResetError, BrokenPipeError):
                        logger.info(f"Session {self.id} worker connection closed.")
                        break
                else:
                    # Give the event loop a chance to process other tasks and check cancellation
                    await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            self._listener_running = False
            raise
        except Exception as e:
            logger.error(f"Error in session {self.id} listener: {e}")
            self.status = "error"
        finally:
            self._listener_running = False
            if self.status != "error":
                self.status = "stopped"

    async def _handle_worker_msg(self, msg: Dict[str, Any]):
        event = msg.get("event")
        msg_id = msg.get("id")
        
        if event == "ready":
            self.pid = msg.get("pid")
            self.status = "running"
            logger.info(f"Session {self.id} ready (PID: {self.pid})")
        
        elif event == "log":
            if msg_id in self._log_listeners:
                for cb in self._log_listeners[msg_id]:
                    await cb(msg.get("text"))
        
        elif event == "progress":
            if msg_id in self._progress_listeners:
                for cb in self._progress_listeners[msg_id]:
                    await cb(msg.get("progress"), msg.get("total"), msg.get("message"))
        
        elif event == "result":
            if msg_id in self._pending_requests:
                if not self._pending_requests[msg_id].done():
                    self._pending_requests[msg_id].set_result(msg.get("result"))
                self._cleanup_listeners(msg_id)
        
        elif event == "error":
            if msg_id in self._pending_requests:
                if not self._pending_requests[msg_id].done():
                    self._pending_requests[msg_id].set_exception(RuntimeError(msg.get("message")))
                self._cleanup_listeners(msg_id)
            else:
                logger.error(f"Global worker error in session {self.id}: {msg.get('message')}")
                # Don't update status if already stopped or error
                if self.status not in ("stopped", "error"):
                    self.status = "error"

    def _cleanup_listeners(self, msg_id: str):
        self._log_listeners.pop(msg_id, None)
        self._progress_listeners.pop(msg_id, None)
        self._pending_requests.pop(msg_id, None)

    async def _ensure_listener(self):
        current_loop = asyncio.get_running_loop()
        if self._listener_task is None or self._listener_task.done() or (hasattr(self._listener_task, "get_loop") and self._listener_task.get_loop() != current_loop):
            if self._listener_task and not self._listener_task.done():
                self._listener_task.cancel()
            self._listener_running = True
            self._listener_task = current_loop.create_task(self._listen_to_worker())

    async def call(self, method: str, args: Dict[str, Any], 
                   notify_log: Optional[Callable[[str], Awaitable[None]]] = None,
                   notify_progress: Optional[Callable[[float, Optional[float], Optional[str]], Awaitable[None]]] = None) -> Any:
        
        await self._ensure_listener()
        msg_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self._pending_requests[msg_id] = future
        
        if notify_log:
            self._log_listeners.setdefault(msg_id, []).append(notify_log)
        if notify_progress:
            self._progress_listeners.setdefault(msg_id, []).append(notify_progress)
            
        try:
            self._parent_conn.send({
                "type": method,
                "id": msg_id,
                "args": args
            })
        except (AttributeError, BrokenPipeError, ConnectionResetError) as e:
             self._cleanup_listeners(msg_id)
             raise RuntimeError(f"Failed to send command to worker: {e}")
        
        return await future

    async def stop(self, timeout: float = 5.0):
        self._listener_running = False
        if self.status != "stopped":
            try:
                self._parent_conn.send({"type": "stop"})
            except Exception:
                pass
            
            if self._process and self._process.is_alive():
                self._process.terminate()
                
                # Use executor to join with timeout without blocking the event loop
                loop = asyncio.get_running_loop()
                try:
                    await loop.run_in_executor(None, self._process.join, timeout)
                except Exception:
                    pass
                
                if self._process.is_alive():
                    logger.warning(f"Session {self.id} worker (PID {self._process.pid}) did not exit after {timeout}s; killing.")
                    try:
                        self._process.kill()
                        await loop.run_in_executor(None, self._process.join)
                    except Exception as e:
                        logger.error(f"Failed to kill session {self.id} worker: {e}")
            
            self.status = "stopped"
            if self._listener_task:
                self._listener_task.cancel()
                try:
                    await self._listener_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

    def get_info(self) -> SessionInfo:
        return SessionInfo(
            id=self.id,
            status=self.status,
            created_at=self.created_at,
            pid=self.pid
        )

# Use class-level list to track all managers for cleanup
_all_managers: List[SessionManager] = []
_atexit_registered = False

def _global_shutdown():
    """Final emergency cleanup for all SessionManagers."""
    for manager in _all_managers:
        manager._shutdown()

class SessionManager:
    def __init__(self):
        self._sessions: Dict[str, StataSession] = {}
        self._default_session_id = "default"
        _all_managers.append(self)
        global _atexit_registered
        if not _atexit_registered:
            atexit.register(_global_shutdown)
            _atexit_registered = True

    def _shutdown(self) -> None:
        """Emergency cleanup for atexit."""
        for session in list(self._sessions.values()):
            try:
                if session._process and session._process.is_alive():
                    # Be very aggressive in atexit, we don't have much time
                    session._process.kill()
                    session._process.join(timeout=0.1)
            except Exception:
                pass
            try:
                session._parent_conn.close()
            except Exception:
                pass
        self._sessions.clear()

    async def start(self):
        # Start default session
        await self.get_or_create_session(self._default_session_id)

    async def get_or_create_session(self, session_id: str) -> StataSession:
        if session_id not in self._sessions:
            logger.info(f"Creating new Stata session: {session_id}")
            session = StataSession(session_id)
            self._sessions[session_id] = session
            # Give it more time to start up on CI (especially Stata's first init)
            # but don't wait if the process dies or status changes.
            timeout = 30.0
            start_time = asyncio.get_running_loop().time()
            while session.status == "starting" and asyncio.get_running_loop().time() - start_time < timeout:
                if not session._process.is_alive():
                    # Process died before reaching ready
                    session.status = "error"
                    break
                await asyncio.sleep(0.1)
                
        return self._sessions[session_id]

    def get_session(self, session_id: str) -> StataSession:
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found.")
        return self._sessions[session_id]

    def list_sessions(self) -> List[SessionInfo]:
        return [s.get_info() for s in self._sessions.values()]

    async def stop_session(self, session_id: str):
        if session_id in self._sessions:
            await self._sessions[session_id].stop()
            del self._sessions[session_id]

    async def stop_all(self):
        tasks = [s.stop() for s in self._sessions.values()]
        if tasks:
            await asyncio.gather(*tasks)
        self._sessions.clear()
