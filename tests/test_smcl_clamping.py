import asyncio
import json
import pytest
import os
from pathlib import Path
from mcp_stata.stata_client import StataClient
pytestmark = pytest.mark.requires_stata

@pytest.mark.asyncio
async def test_smcl_perfection_clamp(client: StataClient, tmp_path):
    """
    EXACT output clamping test for SMCL preservation and maintenance cleaning.
    """
    # Create the do-file to match the user's scenario
    do_path = tmp_path / "do.do"
    do_content = (
        "sysuse auto, clear\n"
        "reg price mpg\n"
        "twoway scatter price mpg, name(scatter1, replace)\n"
        "twoway scatter mpg price\n"
    )
    do_path.write_text(do_content)

    # Track chunks
    notified_chunks = []
    async def notify_log(msg: str):
        # We only care about non-JSON chunks (actual output)
        try:
            json.loads(msg)
        except json.JSONDecodeError:
            notified_chunks.append(msg)

    # Run the do-file
    resp = await client.run_do_file_streaming(
        str(do_path),
        notify_log=notify_log,
        echo=True
    )

    # --- VERIFICATION 1: JSON Response Contents ---
    # The final stdout in the response should contain SMCL tags
    assert "{txt}" in resp.stdout
    assert "{com}" in resp.stdout
    assert "{res}" in resp.stdout
    assert "(1978 automobile data)" in resp.stdout
    assert "reg price mpg" in resp.stdout
    
    # --- VERIFICATION 2: log_path File Contents ---
    # The file at log_path should ALSO contain SMCL tags (it's the authoritative clean log)
    assert resp.log_path is not None
    assert os.path.exists(resp.log_path)
    with open(resp.log_path, "r") as f:
        log_content = f.read()
    
    assert "{txt}" in log_content
    assert "{com}" in log_content
    assert "{res}" in log_content
    # The user specifically wanted this cleaned, so check NO MAINTENANCE POLLUTION
    assert "preemptive_cache" not in log_content
    assert "capture noisily {" not in log_content
    assert "_mcp_rc" not in log_content

    # --- VERIFICATION 3: EXACT FORMAT CHECK (VERBATIM CLAMP) ---
    expected_template = Path("tests/fixtures/smcl_perfection_clamp_expected.txt").read_text()
    expected = expected_template.replace("{DO_PATH}", str(do_path))

    assert log_content.rstrip() == expected.rstrip()

    print("SMCL Clamping Success!")

if __name__ == "__main__":
    pytest.main([__file__])