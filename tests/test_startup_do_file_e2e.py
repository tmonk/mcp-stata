
import os
import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path
from mcp_stata.sessions import SessionManager

@pytest.mark.skipif(os.getenv("STATA_BIN") is None and shutil.which("stata") is None, reason="Stata not found")
@pytest.mark.requires_stata
@pytest.mark.asyncio
async def test_startup_do_file_e2e():
    """Verify that a startup .do file is executed when a session starts."""
    
    # Create a temporary .do file
    with tempfile.NamedTemporaryFile(suffix=".do", mode="w", delete=False) as tf:
        tf.write('global STARTUP_TEST "LOADED SUCCESS"\n')
        tf.write('scalar startup_val = 999\n')
        startup_file_path = tf.name

    # Set the environment variable for the server process (SessionManager spawns worker processes)
    # SessionManager doesn't take env vars easily but it inherits from current process
    os.environ["MCP_STATA_STARTUP_DO_FILE"] = startup_file_path
    
    manager = SessionManager()
    try:
        await manager.start() # Starts default session
        session = manager.get_session("default")
        
        # Verify global macro
        res_macro = await session.call("run_command", {"code": "display \"$STARTUP_TEST\"", "options": {"echo": False}})
        assert "LOADED SUCCESS" in res_macro.get("smcl_output", "")
        
        # Verify scalar
        res_scalar = await session.call("run_command", {"code": "display startup_val", "options": {"echo": False}})
        assert "999" in res_scalar.get("smcl_output", "")
        
    finally:
        await manager.stop_all()
        if os.path.exists(startup_file_path):
            os.unlink(startup_file_path)
        if "MCP_STATA_STARTUP_DO_FILE" in os.environ:
            del os.environ["MCP_STATA_STARTUP_DO_FILE"]

@pytest.mark.skipif(os.getenv("STATA_BIN") is None and shutil.which("stata") is None, reason="Stata not found")
@pytest.mark.requires_stata
@pytest.mark.asyncio
async def test_startup_do_file_error_resilience():
    """Verify that a broken startup .do file doesn't prevent session from starting."""
    
    # Create a broken .do file
    with tempfile.NamedTemporaryFile(suffix=".do", mode="w", delete=False) as tf:
        tf.write('this is not a stata command\n')
        startup_file_path = tf.name

    os.environ["MCP_STATA_STARTUP_DO_FILE"] = startup_file_path
    
    manager = SessionManager()
    try:
        await manager.start()
        session = manager.get_session("default")
        
        # Session should still be usable
        res = await session.call("run_command", {"code": "display 2+2", "options": {"echo": False}})
        assert "4" in res.get("smcl_output", "")
        
    finally:
        await manager.stop_all()
        if os.path.exists(startup_file_path):
            os.unlink(startup_file_path)
        if "MCP_STATA_STARTUP_DO_FILE" in os.environ:
            del os.environ["MCP_STATA_STARTUP_DO_FILE"]


@pytest.mark.skipif(os.getenv("STATA_BIN") is None and shutil.which("stata") is None, reason="Stata not found")
@pytest.mark.requires_stata
@pytest.mark.asyncio
async def test_startup_do_file_multiple_paths_deduped_e2e():
    """Verify multiple startup .do files load once each, in order."""

    with tempfile.NamedTemporaryFile(suffix=".do", mode="w", delete=False) as tf1:
        tf1.write('global STARTUP_SEQ "A"\n')
        tf1_path = tf1.name

    with tempfile.NamedTemporaryFile(suffix=".do", mode="w", delete=False) as tf2:
        tf2.write('global STARTUP_SEQ "B"\n')
        tf2_path = tf2.name

    os.environ["MCP_STATA_STARTUP_DO_FILE"] = f"{tf1_path}{os.pathsep}{tf1_path}{os.pathsep}{tf2_path}"

    manager = SessionManager()
    try:
        await manager.start()
        session = manager.get_session("default")

        res_macro = await session.call("run_command", {"code": "display \"$STARTUP_SEQ\"", "options": {"echo": False}})
        assert "B" in res_macro.get("smcl_output", "")
    finally:
        await manager.stop_all()
        for path in (tf1_path, tf2_path):
            if os.path.exists(path):
                os.unlink(path)
        if "MCP_STATA_STARTUP_DO_FILE" in os.environ:
            del os.environ["MCP_STATA_STARTUP_DO_FILE"]


@pytest.mark.skipif(os.getenv("STATA_BIN") is None and shutil.which("stata") is None, reason="Stata not found")
@pytest.mark.requires_stata
@pytest.mark.asyncio
async def test_startup_do_file_duplicate_only_runs_once_e2e():
    """Verify duplicate startup .do files only execute once."""

    with tempfile.NamedTemporaryFile(suffix=".do", mode="w", delete=False) as tf:
        tf.write('capture confirm global STARTUP_COUNT\n')
        tf.write('if _rc != 0 global STARTUP_COUNT 0\n')
        tf.write('global STARTUP_COUNT = $STARTUP_COUNT + 1\n')
        tf_path = tf.name

    os.environ["MCP_STATA_STARTUP_DO_FILE"] = f"{tf_path}{os.pathsep}{tf_path}"

    manager = SessionManager()
    try:
        await manager.start()
        session = manager.get_session("default")

        res_macro = await session.call("run_command", {"code": "display \"$STARTUP_COUNT\"", "options": {"echo": False}})
        assert "1" in res_macro.get("smcl_output", "")
    finally:
        await manager.stop_all()
        if os.path.exists(tf_path):
            os.unlink(tf_path)
        if "MCP_STATA_STARTUP_DO_FILE" in os.environ:
            del os.environ["MCP_STATA_STARTUP_DO_FILE"]


@pytest.mark.requires_stata
@pytest.mark.asyncio
async def test_clear_all_restores_startup_programs_e2e():
    """Program defined in startup .do file survives ``clear all``.

    Scenario
    --------
    1. A startup .do file defines program ``_test_add_numbers``.
    2. After session start the program is callable.
    3. ``clear all`` is executed inside the session.
    4. The sentinel mechanism detects the loss and re-runs startup files.
    5. The program is callable again.

    This exercises the full SessionManager → worker → StataClient path.
    """
    with tempfile.NamedTemporaryFile(suffix=".do", mode="w", delete=False) as tf:
        tf.write(
            "capture program drop _test_add_numbers\n"
            "program define _test_add_numbers, rclass\n"
            "    args num1 num2\n"
            "    local sum = `num1' + `num2'\n"
            "    display `sum'\n"
            "    return scalar sum = `sum'\n"
            "end\n"
        )
        startup_file_path = tf.name

    os.environ["MCP_STATA_STARTUP_DO_FILE"] = startup_file_path

    manager = SessionManager()
    try:
        await manager.start()
        session = manager.get_session("default")

        # 1) Program should be available after startup.
        res1 = await session.call(
            "run_command",
            {"code": "_test_add_numbers 3 4", "options": {"echo": False}},
        )
        assert "7" in res1.get("smcl_output", ""), (
            f"Program not loaded at startup: {res1}"
        )

        # 2) Run ``clear all`` — this wipes all user programs.
        await session.call(
            "run_command",
            {"code": "clear all", "options": {"echo": False}},
        )

        # 3) Program should still be callable because the sentinel
        #    mechanism re-loaded the startup .do file.
        res2 = await session.call(
            "run_command",
            {"code": "_test_add_numbers 10 20", "options": {"echo": False}},
        )
        assert "30" in res2.get("smcl_output", ""), (
            f"Program NOT restored after clear all: {res2}"
        )
    finally:
        await manager.stop_all()
        if os.path.exists(startup_file_path):
            os.unlink(startup_file_path)
        if "MCP_STATA_STARTUP_DO_FILE" in os.environ:
            del os.environ["MCP_STATA_STARTUP_DO_FILE"]


@pytest.mark.requires_stata
@pytest.mark.asyncio
async def test_clear_programs_restores_startup_programs_e2e():
    """Program defined in startup .do file survives ``clear programs``."""
    with tempfile.NamedTemporaryFile(suffix=".do", mode="w", delete=False) as tf:
        tf.write(
            "capture program drop _test_myprog\n"
            "program define _test_myprog\n"
            "    display \"myprog_ok\"\n"
            "end\n"
        )
        startup_file_path = tf.name

    os.environ["MCP_STATA_STARTUP_DO_FILE"] = startup_file_path

    manager = SessionManager()
    try:
        await manager.start()
        session = manager.get_session("default")

        # Available after startup.
        res1 = await session.call(
            "run_command",
            {"code": "_test_myprog", "options": {"echo": False}},
        )
        assert "myprog_ok" in res1.get("smcl_output", ""), (
            f"Program not loaded at startup: {res1}"
        )

        # ``clear programs`` wipes programs.
        await session.call(
            "run_command",
            {"code": "clear programs", "options": {"echo": False}},
        )

        # Should be restored.
        res2 = await session.call(
            "run_command",
            {"code": "_test_myprog", "options": {"echo": False}},
        )
        assert "myprog_ok" in res2.get("smcl_output", ""), (
            f"Program NOT restored after clear programs: {res2}"
        )
    finally:
        await manager.stop_all()
        if os.path.exists(startup_file_path):
            os.unlink(startup_file_path)
        if "MCP_STATA_STARTUP_DO_FILE" in os.environ:
            del os.environ["MCP_STATA_STARTUP_DO_FILE"]


@pytest.mark.requires_stata
@pytest.mark.asyncio
async def test_clear_all_does_not_restore_when_no_reload_e2e():
    """Program is NOT restored after ``clear all`` when reload is disabled."""
    with tempfile.NamedTemporaryFile(suffix=".do", mode="w", delete=False) as tf:
        tf.write(
            "capture program drop _test_no_reload\n"
            "program define _test_no_reload\n"
            "    display \"noreload_ok\"\n"
            "end\n"
        )
        startup_file_path = tf.name

    os.environ["MCP_STATA_STARTUP_DO_FILE"] = startup_file_path
    os.environ["MCP_STATA_NO_RELOAD_ON_CLEAR"] = "1"

    manager = SessionManager()
    try:
        await manager.start()
        session = manager.get_session("default")

        res1 = await session.call(
            "run_command",
            {"code": "_test_no_reload", "options": {"echo": False}},
        )
        assert "noreload_ok" in res1.get("smcl_output", ""), (
            f"Program not loaded at startup: {res1}"
        )

        await session.call(
            "run_command",
            {"code": "clear all", "options": {"echo": False}},
        )

        res2 = await session.call(
            "run_command",
            {"code": "_test_no_reload", "options": {"echo": False}},
        )
        rc = res2.get("rc")
        if rc is not None:
            assert rc != 0, f"Program unexpectedly restored (rc={rc}): {res2}"
        else:
            assert "not found" in res2.get("smcl_output", "").lower(), (
                f"Program unexpectedly restored: {res2}"
            )
    finally:
        await manager.stop_all()
        if os.path.exists(startup_file_path):
            os.unlink(startup_file_path)
        if "MCP_STATA_STARTUP_DO_FILE" in os.environ:
            del os.environ["MCP_STATA_STARTUP_DO_FILE"]
        if "MCP_STATA_NO_RELOAD_ON_CLEAR" in os.environ:
            del os.environ["MCP_STATA_NO_RELOAD_ON_CLEAR"]


@pytest.mark.skipif(os.getenv("STATA_BIN") is None and shutil.which("stata") is None, reason="Stata not found")
@pytest.mark.requires_stata
@pytest.mark.asyncio
async def test_startup_do_file_profile_deduped_against_env_e2e():
    """Verify profile.do is not executed twice when listed in env var."""

    with tempfile.TemporaryDirectory() as tmpdir:
        profile_path = os.path.join(tmpdir, "profile.do")
        with open(profile_path, "w", encoding="utf-8") as f:
            f.write('capture confirm global STARTUP_PROFILE_COUNT\n')
            f.write('if _rc != 0 global STARTUP_PROFILE_COUNT 0\n')
            f.write('global STARTUP_PROFILE_COUNT = $STARTUP_PROFILE_COUNT + 1\n')

        os.environ["MCP_STATA_STARTUP_DO_FILE"] = profile_path

        manager = SessionManager()
        try:
            await manager.start()
            session = manager.get_session("default")

            res_macro = await session.call("run_command", {"code": "display \"$STARTUP_PROFILE_COUNT\"", "options": {"echo": False}})
            assert "1" in res_macro.get("smcl_output", "")
        finally:
            await manager.stop_all()
            if "MCP_STATA_STARTUP_DO_FILE" in os.environ:
                del os.environ["MCP_STATA_STARTUP_DO_FILE"]
