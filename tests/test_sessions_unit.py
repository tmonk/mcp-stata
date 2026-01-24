import pytest
import asyncio
from unittest.mock import MagicMock, patch, ANY
from mcp_stata.sessions import SessionManager, StataSession

@pytest.mark.asyncio
async def test_session_manager_init():
    with patch('mcp_stata.sessions.Process'), patch('mcp_stata.sessions.Pipe') as mock_pipe:
        parent_conn = MagicMock()
        child_conn = MagicMock()
        mock_pipe.return_value = (parent_conn, child_conn)
        
        # Mock immediate ready response from worker
        parent_conn.poll.side_effect = [True] + [False] * 100
        parent_conn.recv.return_value = {"event": "ready", "pid": 1234}
        
        manager = SessionManager()
        await manager.start()
        
        assert "default" in manager._sessions
        assert manager._sessions["default"].pid == 1234
        assert manager._sessions["default"].status == "running"
        
        await manager.stop_all()

@pytest.mark.asyncio
async def test_create_multiple_sessions():
    with patch('mcp_stata.sessions.Process'), patch('mcp_stata.sessions.Pipe') as mock_pipe:
        parent_conn = MagicMock()
        child_conn = MagicMock()
        mock_pipe.return_value = (parent_conn, child_conn)
        
        # Mock ready responses
        parent_conn.poll.side_effect = [True, False, True] + [False] * 100
        parent_conn.recv.side_effect = [
            {"event": "ready", "pid": 1001},
            {"event": "ready", "pid": 1002}
        ]
        
        manager = SessionManager()
        await manager.start() # creates default
        await manager.get_or_create_session("s2")
        
        sessions = manager.list_sessions()
        assert len(sessions) == 2
        ids = [s.id for s in sessions]
        assert "default" in ids
        assert "s2" in ids
        
        await manager.stop_all()

@pytest.mark.asyncio
async def test_session_call_and_result():
    with patch('mcp_stata.sessions.Process'), patch('mcp_stata.sessions.Pipe') as mock_pipe:
        parent_conn = MagicMock()
        child_conn = MagicMock()
        mock_pipe.return_value = (parent_conn, child_conn)
        
        # Mock ready then result
        parent_conn.poll.side_effect = [True] + [False] * 100
        
        manager = SessionManager()
        await manager.start()
        session = manager.get_session("default")
        
        # Mock the worker sending back a result
        msg_id_container = []
        def mock_send(msg):
            if msg.get("type") == "run_command":
                msg_id_container.append(msg.get("id"))
        parent_conn.send.side_effect = mock_send
        
        # We need to trigger the receiver manually since it's a loop
        # Instead, let's just test that call sends the right message and waits for future
        
        call_task = asyncio.create_task(session.call("run_command", {"code": "display 1"}))
        
        # Give it a tiny bit to send
        await asyncio.sleep(0.1)
        assert parent_conn.send.called
        msg_id = msg_id_container[0]
        
        # Send back result
        await session._handle_worker_msg({"event": "result", "id": msg_id, "result": {"stdout": "1"}})
        
        result = await call_task
        assert result == {"stdout": "1"}
        
        await manager.stop_all()

@pytest.mark.asyncio
async def test_session_error_handling():
    with patch('mcp_stata.sessions.Process'), patch('mcp_stata.sessions.Pipe') as mock_pipe:
        parent_conn = MagicMock()
        child_conn = MagicMock()
        mock_pipe.return_value = (parent_conn, child_conn)
        
        parent_conn.poll.return_value = False
        
        manager = SessionManager()
        await manager.start()
        session = manager.get_session("default")
        
        msg_id_container = []
        parent_conn.send.side_effect = lambda msg: msg_id_container.append(msg.get("id"))
        
        call_task = asyncio.create_task(session.call("run_command", {"code": "bad command"}))
        await asyncio.sleep(0.1)
        
        msg_id = msg_id_container[0]
        await session._handle_worker_msg({"event": "error", "id": msg_id, "message": "Command failed"})
        
        with pytest.raises(RuntimeError, match="Command failed"):
            await call_task
            
        await manager.stop_all()
