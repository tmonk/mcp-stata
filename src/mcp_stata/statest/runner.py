from __future__ import annotations
import os
import time
import uuid
import glob
import logging
import asyncio
from pathlib import Path
from typing import List, Optional, Any

from .models import TestResult, AssertionFailure, TestSuiteSummary
from .junit import write_junit_xml

logger = logging.getLogger("mcp_stata.statest.runner")

def discover_tests(path: str) -> List[str]:
    """Find all test_*.do files recursively under path."""
    search_path = os.path.join(path, "**", "test_*.do")
    return sorted(glob.glob(search_path, recursive=True))

async def _fetch_assertion_failure(session: Any, test_path: str, rc: int, log_path: Optional[str]) -> tuple[Optional[int], Optional[AssertionFailure]]:
    """Helper to fetch statest_* scalars after a failure."""
    try:
        # Fetch all scalars to be safe
        scalar_res = await session.call("run_command_structured", {"code": "scalar list", "options": {"echo": False}})
        stdout = scalar_res.get("stdout", "")
        
        data = {}
        for line in stdout.splitlines():
            if "=" in line:
                parts = line.split("=", 1)
                name = parts[0].strip()
                if name.startswith("statest_"):
                    val = parts[1].strip()
                    if val.startswith('"') and val.endswith('"'):
                        val = val[1:-1]
                    data[name] = val
        
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
                    command=data.get("statest_command") or "unknown",
                    variable=data.get("statest_variable") or "",
                    expected=expected,
                    actual=actual,
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
    existing_session_id: Optional[str] = None
) -> TestResult:
    """Run a single test do-file, optionally in an existing session."""
    start_time = time.time()
    session_id = existing_session_id or f"statest-{uuid.uuid4().hex[:8]}"
    
    # If using an existing session, we don't stop it at the end.
    should_stop = existing_session_id is None
    
    setup_rc = 0
    teardown_rc = 0
    rc = 0
    success = False
    log_path = None
    assertion_index = None
    failure = None
    
    try:
        session = await session_manager.get_or_create_session(session_id)
        
        # Ensure statest.mata is loaded
        mata_file = os.path.join(os.path.dirname(__file__), "statest.mata")
        await session.call("run_do_file", {"path": os.path.abspath(mata_file), "options": {"echo": False}})
        
        test_dir = os.path.dirname(os.path.abspath(path))
        
        # 1. Setup
        setup_file = os.path.join(test_dir, "statest_setup.do")
        if os.path.exists(setup_file):
            setup_res = await session.call("run_do_file", {"path": setup_file, "options": {"echo": False}})
            setup_rc = setup_res.get("rc", 0)
            if setup_rc != 0:
                duration = time.time() - start_time
                return TestResult(
                    test_path=path, success=False, rc=setup_rc, setup_rc=setup_rc, 
                    duration_seconds=duration, log_path=setup_res.get("log_path")
                )
            
            # Reset assertion index after setup
            await session.call("run_command", {"code": "scalar statest_assertion_index = 0", "options": {"echo": False}})

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
    
    # Run conftest.do if present
    conftest_file = os.path.join(path, "statest_conftest.do")
    if os.path.exists(conftest_file):
        conftest_session_id = f"statest-conftest-{uuid.uuid4().hex[:8]}"
        try:
            session = await session_manager.get_or_create_session(conftest_session_id)
            # Ensure statest.mata is loaded
            mata_file = os.path.join(os.path.dirname(__file__), "statest.mata")
            await session.call("run_do_file", {"path": os.path.abspath(mata_file), "options": {"echo": False}})
            await session.call("run_do_file", {"path": os.path.abspath(conftest_file), "options": {"echo": False}})
        finally:
            await session_manager.stop_session(conftest_session_id)

    results = []
    
    if parallel and not session_id:
        semaphore = asyncio.Semaphore(max_workers)
        
        async def sem_run_test(f):
            async with semaphore:
                return await run_test(f, session_manager)
        
        results = await asyncio.gather(*(sem_run_test(f) for f in test_files))
    else:
        for f in test_files:
            res = await run_test(f, session_manager, existing_session_id=session_id)
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
