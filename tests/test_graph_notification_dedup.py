
import pytest
from unittest.mock import MagicMock, patch
from mcp_stata.graph_detector import GraphCreationDetector

class MockStataClient:
    def __init__(self):
        self._command_idx = 0
        self.stata = MagicMock()
        self._graph_name_aliases = {}

    def _resolve_graph_name_for_stata(self, name):
        return name

@pytest.fixture
def detector():
    client = MockStataClient()
    return GraphCreationDetector(client)

def test_graph_notification_deduplication(detector):
    """
    Test that redundant notifications are suppressed when command index jumps
    but graph metadata timestamps remain the same.
    """
    client = detector._stata_client
    
    # 1. First command: Create 'Graph'
    client._command_idx = 1
    with patch.object(detector, "_get_graph_inventory", return_value=(["Graph"], {"Graph": "20Jan2026_12:00:00"})):
        
        # Should detect the new graph
        new_graphs = detector._detect_graphs_via_pystata()
        assert "Graph" in new_graphs
        
        state1 = detector._last_graph_state["Graph"].copy()
        sig1 = state1["signature"]
        assert state1["timestamp_val"] == "20Jan2026_12:00:00"

    # 2. Second command: Non-graphing command (e.g., 'desc')
    client._command_idx = 2
    with patch.object(detector, "_get_graph_inventory", return_value=(["Graph"], {"Graph": "20Jan2026_12:00:00"})):
        
        # Should NOT detect changes because timestamp is identical
        new_graphs = detector._detect_graphs_via_pystata()
        assert "Graph" not in new_graphs
        
        # Signature must remain stable to avoid triggering downstream notifications
        state2 = detector._last_graph_state["Graph"]
        assert state2["signature"] == sig1
        assert state2["cmd_idx"] == 2

    # 3. Third command: Overwrite 'Graph' (e.g., new 'hist')
    client._command_idx = 3
    with patch.object(detector, "_get_graph_inventory", return_value=(["Graph"], {"Graph": "20Jan2026_12:05:00"})):
        
        # Should detect modification because timestamp changed
        new_graphs = detector._detect_graphs_via_pystata()
        assert "Graph" in new_graphs
        
        state3 = detector._last_graph_state["Graph"]
        assert state3["signature"] != sig1
        assert state3["timestamp_val"] == "20Jan2026_12:05:00"

def test_graph_batch_timestamp_retrieval_failure(detector):
    """
    Ensure system falls back to reporting modification if metadata cannot be retrieved.
    """
    client = detector._stata_client
    
    client._command_idx = 1
    with patch.object(detector, "_get_graph_inventory", return_value=(["Graph"], {})):
        
        detector._detect_graphs_via_pystata()
    
    client._command_idx = 2
    with patch.object(detector, "_get_graph_inventory", return_value=(["Graph"], {})):
        
        # Without metadata, we must assume change on command jump for safety
        new_graphs = detector._detect_graphs_via_pystata()
        assert "Graph" in new_graphs
