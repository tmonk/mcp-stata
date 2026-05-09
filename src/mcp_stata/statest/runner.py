from __future__ import annotations
import os
import time
import uuid
import glob
import logging
import asyncio
from pathlib import Path
from typing import List, Optional, Any, Dict

from .models import TestResult, AssertionFailure, TestSuiteSummary
from .junit import write_junit_xml

logger = logging.getLogger("mcp_stata.statest.runner")

def discover_tests(path: str) -> List[str]:
    """Find all test_*.do files recursively under path."""
    search_path = os.path.join(path, "**", "test_*.do")
    return sorted(glob.glob(search_path, recursive=True))

class StatestSessionPool:
    """Pool of warm Stata sessions for statest."""
    def __init__(self, session_manager: Any, size: int):
        self._manager = session_manager
        self._pool: asyncio.Queue[str] = asyncio.Queue(maxsize=size)
        self._size = size
        self._created_count = 0
        self._lock = asyncio.Lock()
        self._startup_file = str(Path(__file__).parent / "statest.mata")

    async def acquire(self) -> str:
        # Try to get existing warm session
        try:
            return self._pool.get_nowait()
        except asyncio.QueueEmpty:
            pass
            
        async with self._lock:
            if self._created_count < self._size:
                session_id = f"statest-{uuid.uuid4().hex[:8]}"
                await self._manager.get_or_create_session(session_id, startup_do_file=self._startup_file)
                self._created_count += 1
                return session_id
        
        # If we reached the limit, wait for one to be released
        return await self._pool.get()

    async def release(self, session_id: str):
        # Reset state - startup files auto-reload after clear all
        try:
            session = await self._manager.get_or_create_session(session_id)
            await session.call("run_command", {"code": "clear all", "options": {"echo": False}})
            # This should not block because we only ever have 'size' sessions
            await self._pool.put(session_id)
        except Exception as e:
            logger.warning(f"Failed to reset/release session {session_id}: {e}")
            async with self._lock:
                try:
                    await self._manager.stop_session(session_id)
                except:
                    pass
                self._created_count -= 1

    async def drain(self):
        while self._created_count > 0:
            try:
                sid = await asyncio.wait_for(self._pool.get(), timeout=2.0)
                await self._manager.stop_session(sid)
                self._created_count -= 1
            except asyncio.TimeoutError:
                break

async def _fetch_assertion_failure(session: Any, test_path: str, rc: int, log_path: Optional[str]) -> tuple[Optional[int], Optional[AssertionFailure]]:
    """Helper to fetch statest_* results after a failure using structured results."""
    try:
        results = await session.call("get_stored_results", {"force_fresh": True})
        scalars = results.get("scalars", {})
        data = {k: v for k, v in scalars.items() if k.startswith("statest_")}
        
        assertion_index_raw = data.get("statest_assertion_index")
        if assertion_index_raw is not None:
            try:
                idx = int(float(assertion_index_raw))
                actual = data.get("statest_actual_str") or data.get("statest_actual")
                expected = data.get("statest_expected_str") or data.get("statest_expected")
                
                # Fetch log excerpt if possible
                log_excerpt = None
                if log_path and os.path.exists(log_path):
                    with open(log_path, "r") as f:
                        lines = f.readlines()
                        # Get last 20 lines
                        log_excerpt = "".join(lines[-20:])

                failure = AssertionFailure(
                    test=os.path.basename(test_path),
                    assertion_index=idx,
                    command=str(data.get("statest_command") or "unknown"),
                    variable=str(data.get("statest_variable") or ""),
                    expected=str(expected) if expected is not None else None,
                    actual=str(actual) if actual is not None else None,
                    tolerance=float(data.get("statest_tolerance")) if data.get("statest_tolerance") else None,
                    rc=rc,
                    log_excerpt=log_excerpt
                )
                return idx, failure
            except (ValueError, TypeError):
                pass
    except Exception as e:
        logger.warning(f"Failed to fetch statest results for {test_path}: {e}")
    
    return None, None

async def run_test(
    path: str, 
    session_manager: Any, 
    pool: Optional[StatestSessionPool] = None,
    existing_session_id: Optional[str] = None
) -> TestResult:
    """Run a single test do-file, optionally using a pool or existing session."""
    start_time = time.time()
    
    session_id = existing_session_id
    if not session_id and pool:
        session_id = await pool.acquire()
    elif not session_id:
        session_id = f"statest-{uuid.uuid4().hex[:8]}"

    # If using a pool or existing session, we don't stop it at the end.
    should_stop = not pool and existing_session_id is None
    
    setup_rc = 0
    teardown_rc = 0
    rc = 0
    success = False
    log_path = None
    assertion_index = None
    failure = None
    
    try:
        # statest.mata is now loaded via startup_do_file in pool.acquire or here
        startup_file = str(Path(__file__).parent / "statest.mata")
        session = await session_manager.get_or_create_session(session_id, startup_do_file=startup_file)
        
        test_dir = os.path.dirname(os.path.abspath(path))
        
        # 1. Setup
        setup_file = os.path.join(test_dir, "statest_setup.do")
        if os.path.exists(setup_file):
            # We fold the reset into the setup by calling statest_reset first
            setup_res = await session.call("run_command_structured", {
                "code": f"statest_reset\ndo \"{setup_file}\"", 
                "options": {"echo": False}
            })
            setup_rc = setup_res.get("rc", 0)
            if setup_rc != 0:
                duration = time.time() - start_time
                return TestResult(
                    test_path=path, success=False, rc=setup_rc, setup_rc=setup_rc, 
                    duration_seconds=duration, log_path=setup_res.get("log_path")
                )
        else:
            # Still need to reset even if no setup file
            await session.call("run_command", {"code": "statest_reset", "options": {"echo": False}})

        # 2. Test
        test_res = await session.call("run_do_file", {"path": os.path.abspath(path), "options": {"echo": False}})
        rc = test_res.get("rc", 0)
        success = test_res.get("success", False)
        log_path = test_res.get("log_path")
        
        if not success:
            assertion_index, failure = await _fetch_assertion_failure(session, path, rc, log_path)

        # 3. Teardown (always run)
        teardown_file = os.path.join(test_dir, "statest_teardown.do")
        if os.path.exists(teardown_file):
            teardown_res = await session.call("run_do_file", {"path": teardown_file, "options": {"echo": False}})
            teardown_rc = teardown_res.get("rc", 0)

        duration = time.time() - start_time
        return TestResult(
            test_path=path,
            success=success and (teardown_rc == 0),
            rc=rc,
            assertion_index=assertion_index,
            failure=failure,
            log_path=log_path,
            duration_seconds=duration,
            setup_rc=setup_rc,
            teardown_rc=teardown_rc
        )
        
    finally:
        if should_stop:
            await session_manager.stop_session(session_id)
        elif pool:
            await pool.release(session_id)

async def run_tests(
    path: str, 
    session_manager: Any,
    session_id: Optional[str] = None,
    parallel: bool = False,
    max_workers: int = 4,
    junit_xml_path: Optional[str] = None
) -> TestSuiteSummary:
    """Discover and run all tests under path."""
    test_files = discover_tests(path)
    
    # Initialize pool
    pool_size = max_workers if parallel and not session_id else 1
    pool = StatestSessionPool(session_manager, pool_size)
    
    try:
        # Run conftest.do if present - in the first pooled session
        conftest_file = os.path.join(path, "statest_conftest.do")
        if os.path.exists(conftest_file):
            sid = await pool.acquire()
            try:
                session = await session_manager.get_or_create_session(sid)
                await session.call("run_do_file", {"path": os.path.abspath(conftest_file), "options": {"echo": False}})
            finally:
                await pool.release(sid)

        results = []
        
        if parallel and not session_id:
            results = await asyncio.gather(*(run_test(f, session_manager, pool=pool) for f in test_files))
        else:
            for f in test_files:
                res = await run_test(f, session_manager, pool=pool, existing_session_id=session_id)
                results.append(res)
                
        # Sort results by path for deterministic output
        results.sort(key=lambda r: r.test_path)
        
        passed = sum(1 for r in results if r.success)
        failed = len(results) - passed
        
        summary_text = f"Ran {len(results)} tests. {passed} passed, {failed} failed."
        
        summary = TestSuiteSummary(
            path=path,
            total_tests=len(results),
            passed=passed,
            failed=failed,
            results=results,
            summary_text=summary_text,
            junit_xml_path=junit_xml_path
        )
        
        if junit_xml_path:
            write_junit_xml(summary, junit_xml_path)
            
        return summary
    finally:
        await pool.drain()
