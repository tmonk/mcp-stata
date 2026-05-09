from __future__ import annotations
import os
import time
import uuid
import glob
import logging
from pathlib import Path
from typing import List, Optional, Any

from .models import TestResult, AssertionFailure, TestSuiteSummary

logger = logging.getLogger("mcp_stata.statest.runner")

def discover_tests(path: str) -> List[str]:
    """Find all test_*.do files recursively under path."""
    search_path = os.path.join(path, "**", "test_*.do")
    return sorted(glob.glob(search_path, recursive=True))

async def run_test(
    path: str, 
    session_manager: Any, 
    existing_session_id: Optional[str] = None
) -> TestResult:
    """Run a single test do-file, optionally in an existing session."""
    start_time = time.time()
    session_id = existing_session_id or f"statest-{uuid.uuid4().hex[:8]}"
    
    # If using an existing session, we don't stop it at the end.
    # If creating a new one, we do.
    should_stop = existing_session_id is None
    
    try:
        session = await session_manager.get_or_create_session(session_id)
        
        # Execute the do-file
        # We use run_do_file_structured to get the log path and rc
        res_dict = await session.call(
            "run_do_file", 
            {"path": os.path.abspath(path), "options": {"echo": False}}
        )
        
        success = res_dict.get("success", False)
        rc = res_dict.get("rc", 0)
        log_path = res_dict.get("log_path")
        
        failure = None
        assertion_index = None
        
        if not success:
            # Try to fetch statest results
            try:
                # We use get_stored_results but we only care about scalars
                # Actually, we can just run 'display statest_...' and capture output,
                # but better to use the structured results tool.
                results = await session.call(
                    "get_stored_results", 
                    {"include_matrices": True}
                )
                
                # Scalars are in results['r'] or similar?
                # Actually, our statest.mata uses st_numscalar which creates Stata scalars (r-class or global).
                # My implementation uses st_numscalar("statest_assertion_index") which is a Stata scalar.
                # Stata scalars are accessed via 'scalar(name)'.
                
                # Fetch scalars via 'scalar list'
                fetch_cmd = "scalar list statest_assertion_index statest_command statest_variable statest_actual statest_actual_str statest_expected statest_expected_str statest_tolerance"
                scalar_res = await session.call("run_command_structured", {"code": fetch_cmd, "options": {"echo": False}})
                stdout = scalar_res.get("stdout", "")
                
                data = {}
                for line in stdout.splitlines():
                    if "=" in line:
                        parts = line.split("=", 1)
                        name = parts[0].strip()
                        val = parts[1].strip()
                        if val.startswith('"') and val.endswith('"'):
                            val = val[1:-1]
                        data[name] = val
                
                assertion_index = data.get("statest_assertion_index")
                if assertion_index is not None:
                    try:
                        idx = int(float(assertion_index))
                        actual = data.get("statest_actual_str") or data.get("statest_actual")
                        expected = data.get("statest_expected_str") or data.get("statest_expected")
                        
                        failure = AssertionFailure(
                            test=os.path.basename(path),
                            assertion_index=idx,
                            command=data.get("statest_command") or "unknown",
                            variable=data.get("statest_variable") or "",
                            expected=expected,
                            actual=actual,
                            tolerance=float(data.get("statest_tolerance")) if data.get("statest_tolerance") else None,
                            rc=rc,
                            log_excerpt=None
                        )
                    except (ValueError, TypeError):
                        pass

            except Exception as e:
                logger.warning(f"Failed to fetch statest results for {path}: {e}")
        
        duration = time.time() - start_time
        return TestResult(


            test_path=path,
            success=success,
            rc=rc,
            assertion_index=assertion_index,
            failure=failure,
            log_path=log_path,
            duration_seconds=duration
        )
        
    finally:
        if should_stop:
            await session_manager.stop_session(session_id)

async def run_tests(
    path: str, 
    session_manager: Any,
    session_id: Optional[str] = None
) -> TestSuiteSummary:
    """Discover and run all tests under path."""
    test_files = discover_tests(path)
    results = []
    
    for f in test_files:
        res = await run_test(f, session_manager, existing_session_id=session_id)
        results.append(res)
        
    passed = sum(1 for r in results if r.success)
    failed = len(results) - passed
    
    summary_text = f"Ran {len(results)} tests. {passed} passed, {failed} failed."
    
    return TestSuiteSummary(
        path=path,
        total_tests=len(results),
        passed=passed,
        failed=failed,
        results=results,
        summary_text=summary_text
    )
