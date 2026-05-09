from __future__ import annotations
from typing import Optional, List, Union
from pydantic import BaseModel, Field

class AssertionFailure(BaseModel):
    test: str
    assertion_index: int
    command: str
    variable: str
    expected: Optional[Union[float, str]] = None
    actual: Optional[Union[float, str]] = None
    tolerance: Optional[float] = None
    rc: int
    log_excerpt: Optional[str] = None

class TestResult(BaseModel):
    test_path: str
    success: bool
    rc: int
    assertion_index: Optional[int] = None
    failure: Optional[AssertionFailure] = None
    log_path: Optional[str] = None
    duration_seconds: float

class TestSuiteSummary(BaseModel):
    path: str
    total_tests: int
    passed: int
    failed: int
    results: List[TestResult]
    summary_text: str
