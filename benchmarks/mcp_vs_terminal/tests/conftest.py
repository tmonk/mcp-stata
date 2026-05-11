import pytest
import os
import shutil
import sys

# Add the src directory to sys.path so we can import mcp_stata
src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../src"))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

try:
    from benchmark.results import RunRecord
except Exception:  # pragma: no cover
    RunRecord = None  # type: ignore[assignment]

try:
    from mcp_stata.discovery import find_stata_candidates
except ImportError:
    find_stata_candidates = None

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "requires_stata: mark test as requiring a local Stata installation"
    )

@pytest.fixture
def temp_work_dir(tmp_path):
    """Provides a temporary directory for tests."""
    return str(tmp_path)

@pytest.fixture
def has_stata():
    """Checks if Stata is available using mcp_stata.discovery."""
    if find_stata_candidates:
        try:
            candidates = find_stata_candidates()
            return len(candidates) > 0
        except Exception:
            return False
    
    # Fallback to manual check if discovery is not available
    stata_path = os.environ.get("STATA_PATH")
    if stata_path and os.path.isfile(stata_path):
        return True
    return shutil.which("stata-se") is not None or shutil.which("stata") is not None


@pytest.fixture
def sample_run_records():
    """
    6 hardcoded RunRecord instances covering:
    - 2 versions (0.1.0, 0.2.0)
    - both approaches (mcp, terminal)
    - tasks T1.1 and T2.1
    """
    if RunRecord is None:
        raise RuntimeError("benchmark.results.RunRecord could not be imported")

    def cost(input_tokens: int, output_tokens: int) -> float:
        # input/1M*0.50 + output/1M*3.00
        return (input_tokens / 1_000_000.0) * 0.50 + (output_tokens / 1_000_000.0) * 3.00

    # Version A (0.1.0)
    v1_mcp_t11 = RunRecord(
        run_id="11111111-1111-4111-8111-111111111111",
        timestamp="2026-05-10T10:00:00Z",
        mcp_stata_version="0.1.0",
        gemini_model="gemini-3-flash-preview",
        git_commit="untracked",
        approach="mcp",
        task_id="T1.1",
        input_tokens=800,
        output_tokens=200,
        total_tokens=1000,
        turns=5,
        cost_usd=cost(800, 200),
        resolution_correct=True,
    )
    v1_term_t11 = RunRecord(
        run_id="22222222-2222-4222-8222-222222222222",
        timestamp="2026-05-10T10:01:00Z",
        mcp_stata_version="0.1.0",
        gemini_model="gemini-3-flash-preview",
        git_commit="untracked",
        approach="terminal",
        task_id="T1.1",
        input_tokens=900,
        output_tokens=300,
        total_tokens=1200,
        turns=6,
        cost_usd=cost(900, 300),
        resolution_correct=True,
    )
    v1_mcp_t21 = RunRecord(
        run_id="33333333-3333-4333-8333-333333333333",
        timestamp="2026-05-10T10:02:00Z",
        mcp_stata_version="0.1.0",
        gemini_model="gemini-3-flash-preview",
        git_commit="untracked",
        approach="mcp",
        task_id="T2.1",
        input_tokens=700,
        output_tokens=300,
        total_tokens=1000,
        turns=7,
        cost_usd=cost(700, 300),
        resolution_correct=True,
        error_detected=True,
        turns_to_detect=3,
        tokens_to_detect=450,
    )

    # Version B (0.2.0) with a planted regression for mcp T1.1: +20% tokens (1200 vs 1000)
    v2_mcp_t11 = RunRecord(
        run_id="44444444-4444-4444-8444-444444444444",
        timestamp="2026-05-11T10:00:00Z",
        mcp_stata_version="0.2.0",
        gemini_model="gemini-3-flash-preview",
        git_commit="untracked",
        approach="mcp",
        task_id="T1.1",
        input_tokens=900,
        output_tokens=300,
        total_tokens=1200,
        turns=5,
        cost_usd=cost(900, 300),
        resolution_correct=True,
    )
    v2_term_t11 = RunRecord(
        run_id="55555555-5555-4555-8555-555555555555",
        timestamp="2026-05-11T10:01:00Z",
        mcp_stata_version="0.2.0",
        gemini_model="gemini-3-flash-preview",
        git_commit="untracked",
        approach="terminal",
        task_id="T1.1",
        input_tokens=950,
        output_tokens=350,
        total_tokens=1300,
        turns=6,
        cost_usd=cost(950, 350),
        resolution_correct=True,
    )
    v2_term_t21 = RunRecord(
        run_id="66666666-6666-4666-8666-666666666666",
        timestamp="2026-05-11T10:02:00Z",
        mcp_stata_version="0.2.0",
        gemini_model="gemini-3-flash-preview",
        git_commit="untracked",
        approach="terminal",
        task_id="T2.1",
        input_tokens=750,
        output_tokens=350,
        total_tokens=1100,
        turns=7,
        cost_usd=cost(750, 350),
        resolution_correct=True,
        error_detected=True,
        turns_to_detect=2,
        tokens_to_detect=430,
    )

    return [
        v1_mcp_t11,
        v1_term_t11,
        v1_mcp_t21,
        v2_mcp_t11,
        v2_term_t11,
        v2_term_t21,
    ]
