import time
import concurrent.futures
import pytest
from unittest.mock import MagicMock

from mcp_stata.ui_http import UIChannelManager
from mcp_stata.stata_client import StataClient

class SlowMockStataClient(StataClient):
    def __new__(cls, *args, **kwargs):
        # StataClient uses __new__ with no args, so we must intercept it
        return super(StataClient, cls).__new__(cls)
        
    def __init__(self, *args, session_id: str = "default", **kwargs):
        self.session_id = session_id
        
    def get_dataset_state(self):
        time.sleep(0.5) # Simulate slow request
        return {
            "frame": "default",
            "n": 100,
            "k": 5,
            "changed": False,
            "sortlist": ""
        }

def test_ui_http_server_concurrency():
    """Test that the ThreadPoolHTTPServer handles requests concurrently."""
    mock_client = SlowMockStataClient(session_id="default")
    
    manager = UIChannelManager(
        client=mock_client,
        host="127.0.0.1",
        port=0,
    )
    # Inject the slow mock client so it builds the proxy with it
    manager._client = mock_client
    
    channel = manager.get_channel()
    
    import urllib.request
    
    req = urllib.request.Request(
        f"{channel.base_url}/v1/dataset",
        headers={"Authorization": f"Bearer {channel.token}"}
    )
    
    # Fire 5 concurrent requests
    start_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(urllib.request.urlopen, req) for _ in range(5)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
    duration = time.time() - start_time
    
    assert len(results) == 5
    for r in results:
        assert r.status == 200
        
    # If the server processes serially, 5 requests * 0.5s = 2.5s
    # If concurrent, it should be just slightly over 0.5s total.
    assert duration < 1.5, f"Requests took {duration:.2f}s, indicating they were processed serially!"
