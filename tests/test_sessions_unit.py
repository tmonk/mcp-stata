import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, ANY
from mcp_stata.sessions import SessionManager, StataSession, _SessionSnapshot

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
        session._record_post_command_snapshot = AsyncMock(return_value=None)
        
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
        
        # Ensure startup reaches ready immediately; avoids 30s startup timeout path.
        parent_conn.poll.side_effect = [True] + [False] * 100
        parent_conn.recv.return_value = {"event": "ready", "pid": 2222}
        
        manager = SessionManager()
        await manager.start()
        session = manager.get_session("default")
        session._record_post_command_snapshot = AsyncMock(return_value=None)
        
        msg_id_container = []
        parent_conn.send.side_effect = lambda msg: msg_id_container.append(msg.get("id"))
        
        call_task = asyncio.create_task(session.call("run_command", {"code": "bad command"}))
        await asyncio.sleep(0.1)
        
        msg_id = msg_id_container[0]
        await session._handle_worker_msg({"event": "error", "id": msg_id, "message": "Command failed"})
        
        with pytest.raises(RuntimeError, match="Command failed"):
            await call_task
            
        await manager.stop_all()

@pytest.mark.asyncio
async def test_session_profile_init():
    """Test that session profile stores code and calls worker."""
    def mock_create_task(coro):
        coro.close()
        return MagicMock()
        
    with patch('mcp_stata.sessions.Process'), \
         patch('mcp_stata.sessions.Pipe') as mock_pipe, \
         patch('asyncio.create_task', side_effect=mock_create_task):
    
        mock_pipe.return_value = (MagicMock(), MagicMock())
        session = StataSession("test_id")
        # Mock call to avoid real worker communication
        mock_call = MagicMock()
        future = asyncio.Future()
        future.set_result(None)
        mock_call.return_value = future
        session.call = mock_call
        
        await session.set_profile("display 1")
        assert session.profile_code == "display 1"
        session.call.assert_called_with("set_profile", {"code": "display 1"})


@pytest.mark.asyncio
async def test_get_session_diff_since_last_checkpoint():
    def mock_create_task(coro):
        coro.close()
        return MagicMock()

    with patch('mcp_stata.sessions.Process'), patch('mcp_stata.sessions.Pipe') as mock_pipe, patch('asyncio.create_task', side_effect=mock_create_task):
        mock_pipe.return_value = (MagicMock(), MagicMock())
        session = StataSession("test_id")

        snapshots = [
            # Baseline
            {
                "variables": {"price", "mpg"},
                "macros": {"r(N)": 74},
                "n_obs": 74,
                "n_vars": 2,
            },
            # Updated state
            {
                "variables": {"price", "weight"},
                "macros": {"r(N)": 10, "e(cmd)": "regress"},
                "n_obs": 10,
                "n_vars": 2,
            },
        ]
        session._collect_snapshot = AsyncMock(return_value=_SessionSnapshot(command_count=2, variables=snapshots[1]["variables"], macros=snapshots[1]["macros"], n_obs=snapshots[1]["n_obs"], n_vars=snapshots[1]["n_vars"], captured_at="t1"))

        session._history = [
            _SessionSnapshot(command_count=1, variables=snapshots[0]["variables"], macros=snapshots[0]["macros"], n_obs=snapshots[0]["n_obs"], n_vars=snapshots[0]["n_vars"], captured_at="t0")
        ]
        session._last_diff_snapshot = session._history[0]
        session.command_count = 2

        diff = await session.get_session_diff()
        assert diff["new_variables"] == ["weight"]
        assert diff["removed_variables"] == ["mpg"]
        assert diff["modified_macros"]["r(N)"] == 10
        assert diff["modified_macros"]["e(cmd)"] == "regress"
        assert diff["removed_macros"] == []


@pytest.mark.asyncio
async def test_get_session_diff_since_command_with_pruned_history_raises():
    def mock_create_task(coro):
        coro.close()
        return MagicMock()

    with patch('mcp_stata.sessions.Process'), patch('mcp_stata.sessions.Pipe') as mock_pipe, patch('asyncio.create_task', side_effect=mock_create_task):
        mock_pipe.return_value = (MagicMock(), MagicMock())
        session = StataSession("test_id")

        session._history = [
            _SessionSnapshot(command_count=5, variables={"a"}, macros={}, n_obs=1, n_vars=1, captured_at="t5"),
            _SessionSnapshot(command_count=6, variables={"a", "b"}, macros={}, n_obs=1, n_vars=2, captured_at="t6"),
        ]
        session.command_count = 6
        session._collect_snapshot = AsyncMock(return_value=session._history[-1])

        with pytest.raises(ValueError, match="Earliest retained command is 5"):
            await session.get_session_diff(since_command=2)


@pytest.mark.asyncio
async def test_collect_snapshot_uses_single_worker_state_call():
    def mock_create_task(coro):
        coro.close()
        return MagicMock()

    with patch('mcp_stata.sessions.Process'), patch('mcp_stata.sessions.Pipe') as mock_pipe, patch('asyncio.create_task', side_effect=mock_create_task):
        mock_pipe.return_value = (MagicMock(), MagicMock())
        session = StataSession("test_id")
        session._call_raw = AsyncMock(return_value={
            "variables": {"variables": [{"name": "price"}, {"name": "mpg"}]},
            "stored_results": {"r": {"N": 74}, "e": {}, "s": {}},
            "dataset_state": {"n": 74, "k": 2},
        })

        snapshot = await session._collect_snapshot(command_count=3)
        assert snapshot.command_count == 3
        assert snapshot.variables == {"price", "mpg"}
        assert snapshot.macros["r.N"] == 74
        assert snapshot.n_obs == 74
        assert snapshot.n_vars == 2
        session._call_raw.assert_awaited_once_with(
            "get_session_state",
            {},
            timeout_seconds=session._snapshot_timeout_seconds,
        )


@pytest.mark.asyncio
async def test_history_stats_reflects_retained_window():
    def mock_create_task(coro):
        coro.close()
        return MagicMock()

    with patch('mcp_stata.sessions.Process'), patch('mcp_stata.sessions.Pipe') as mock_pipe, patch('asyncio.create_task', side_effect=mock_create_task):
        mock_pipe.return_value = (MagicMock(), MagicMock())
        session = StataSession("test_id")
        session.command_count = 10
        session._history = [
            _SessionSnapshot(command_count=4, variables={"a"}, macros={}, n_obs=1, n_vars=1, captured_at="t4"),
            _SessionSnapshot(command_count=8, variables={"a", "b"}, macros={}, n_obs=1, n_vars=2, captured_at="t8"),
            _SessionSnapshot(command_count=10, variables={"a", "b", "c"}, macros={}, n_obs=1, n_vars=3, captured_at="t10"),
        ]

        stats = session.get_history_stats()
        assert stats["command_count"] == 10
        assert stats["history_size"] == 3
        assert stats["earliest_command"] == 4
        assert stats["latest_command"] == 10


@pytest.mark.asyncio
async def test_prune_history_keeps_baseline_and_recent_entries():
    def mock_create_task(coro):
        coro.close()
        return MagicMock()

    with patch('mcp_stata.sessions.Process'), patch('mcp_stata.sessions.Pipe') as mock_pipe, patch('asyncio.create_task', side_effect=mock_create_task):
        mock_pipe.return_value = (MagicMock(), MagicMock())
        session = StataSession("test_id")
        session._max_history_entries = 3
        session._history = [
            _SessionSnapshot(command_count=0, variables=set(), macros={}, n_obs=0, n_vars=0, captured_at="t0"),
            _SessionSnapshot(command_count=1, variables={"a"}, macros={}, n_obs=1, n_vars=1, captured_at="t1"),
            _SessionSnapshot(command_count=2, variables={"a", "b"}, macros={}, n_obs=1, n_vars=2, captured_at="t2"),
            _SessionSnapshot(command_count=3, variables={"a", "b", "c"}, macros={}, n_obs=1, n_vars=3, captured_at="t3"),
            _SessionSnapshot(command_count=4, variables={"a", "b", "c", "d"}, macros={}, n_obs=1, n_vars=4, captured_at="t4"),
        ]

        session._prune_history()
        kept = [s.command_count for s in session._history]
        assert kept == [0, 3, 4]
