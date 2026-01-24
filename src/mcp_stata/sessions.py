from __future__ import annotations
import os
import uuid
import logging
import asyncio
import atexit
from typing import Any, Dict, List, Optional, Callable, Awaitable
from multiprocessing import Process, Pipe
from multiprocessing.connection import Connection
from datetime import datetime, timezone

from mcp_stata.models import SessionInfo, CommandResponse

logger = logging.getLogger("mcp_stata.sessions")

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
        
        self._listener_task = asyncio.create_task(self._listen_to_worker())

    def _run_worker(self, conn: Connection):
        from mcp_stata.worker import main
        main(conn)

    async def _listen_to_worker(self):
        loop = asyncio.get_running_loop()
        try:
            while True:
                # We need to run poll in a thread to avoid blocking the event loop
                if await loop.run_in_executor(None, self._parent_conn.poll, 0.1):
                    msg = self._parent_conn.recv()
                    await self._handle_worker_msg(msg)
                else:
                    await asyncio.sleep(0.01)
        except EOFError:
            logger.info(f"Session {self.id} worker connection closed.")
            self.status = "stopped"
        except Exception as e:
            logger.error(f"Error in session {self.id} listener: {e}")
            self.status = "error"

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
                self._pending_requests[msg_id].set_result(msg.get("result"))
                self._cleanup_listeners(msg_id)
        
        elif event == "error":
            if msg_id in self._pending_requests:
                self._pending_requests[msg_id].set_exception(RuntimeError(msg.get("message")))
                self._cleanup_listeners(msg_id)
            else:
                logger.error(f"Global worker error in session {self.id}: {msg.get('message')}")
                self.status = "error"

    def _cleanup_listeners(self, msg_id: str):
        self._log_listeners.pop(msg_id, None)
        self._progress_listeners.pop(msg_id, None)
        self._pending_requests.pop(msg_id, None)

    async def _ensure_listener(self):
        current_loop = asyncio.get_running_loop()
        if self._listener_task is None or self._listener_task.done() or self._listener_task.get_loop() != current_loop:
            if self._listener_task and not self._listener_task.done():
                self._listener_task.cancel()
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
            
        self._parent_conn.send({
            "type": method,
            "id": msg_id,
            "args": args
        })
        
        return await future

    async def stop(self):
        if self.status != "stopped":
            try:
                self._parent_conn.send({"type": "stop"})
            except:
                pass
            self._process.terminate()
            self._process.join()
            self.status = "stopped"
            if self._listener_task:
                self._listener_task.cancel()

    def get_info(self) -> SessionInfo:
        return SessionInfo(
            id=self.id,
            status=self.status,
            created_at=self.created_at,
            pid=self.pid
        )

class SessionManager:
    def __init__(self):
        self._sessions: Dict[str, StataSession] = {}
        self._default_session_id = "default"
        atexit.register(self._shutdown)

    def _shutdown(self) -> None:
        for session in list(self._sessions.values()):
            try:
                if session._process.is_alive():
                    session._process.terminate()
                    session._process.join(timeout=2)
            except Exception:
                pass
            try:
                session._parent_conn.close()
            except Exception:
                pass
            try:
                session._child_conn.close()
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
            # Give it a tiny bit to start up and reach "running" if possible
            # but we won't block indefinitely
            timeout = 10.0
            start_time = asyncio.get_running_loop().time()
            while session.status == "starting" and asyncio.get_running_loop().time() - start_time < timeout:
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
