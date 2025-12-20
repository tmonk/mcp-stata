"""
Graph creation detection for streaming Stata output.

This module provides functionality to detect when graphs are created
during Stata command execution and automatically cache them.
"""

import asyncio
import re
import threading
import time
from typing import List, Set, Callable, Dict, Any
import logging


# SFI is always available
SFI_AVAILABLE = True

logger = logging.getLogger(__name__)


class GraphCreationDetector:
    """Detects graph creation using SFI-only detection with pystata integration."""
    
    def __init__(self, stata_client=None):
        self._lock = threading.Lock()
        self._detected_graphs: Set[str] = set()
        self._removed_graphs: Set[str] = set()
        self._unnamed_graph_counter = 0  # Track unnamed graphs for identification
        self._stata_client = stata_client
        self._last_graph_state: Dict[str, Any] = {}  # Track graph state changes
    
    def _detect_graphs_via_pystata(self) -> List[str]:
        """Detect newly created graphs using direct pystata state access."""
        if not self._stata_client:
            return []
        
        try:
            # Get current graph state using pystata's sfi interface
            current_graphs = self._get_current_graphs_from_pystata()
            current_state = self._get_graph_state_from_pystata()
            
            # Compare with last known state to detect new graphs
            new_graphs = []
            
            # Check for new graph names
            for graph_name in current_graphs:
                if graph_name not in self._last_graph_state and graph_name not in self._removed_graphs:
                    new_graphs.append(graph_name)
            
            # Check for state changes in existing graphs (modifications)
            for graph_name, state in current_state.items():
                if graph_name in self._last_graph_state:
                    last_state = self._last_graph_state[graph_name]
                    if state != last_state:
                        # Graph was modified, treat as new for caching purposes
                        if graph_name not in self._removed_graphs:
                            new_graphs.append(graph_name)
            
            # Update cached state
            self._last_graph_state = current_state.copy()
            
            return new_graphs
            
        except (ImportError, RuntimeError, ValueError, AttributeError) as e:
            # These are expected exceptions when SFI is not available or Stata state is inaccessible
            logger.debug(f"Failed to detect graphs via pystata (expected): {e}")
            return []
        except Exception as e:
            # Unexpected errors should be logged as errors
            logger.error(f"Unexpected error in pystata graph detection: {e}")
            return []
    
    def _get_current_graphs_from_pystata(self) -> List[str]:
        """Get current list of graphs using pystata's sfi interface."""
        try:
            # Use pystata to get graph list directly
            if self._stata_client and hasattr(self._stata_client, 'list_graphs'):
                return self._stata_client.list_graphs()
            else:
                # Fallback to sfi Macro interface - only if stata is available
                if self._stata_client and hasattr(self._stata_client, 'stata'):
                    try:
                        from sfi import Macro
                        self._stata_client.stata.run("quietly graph dir, memory")
                        self._stata_client.stata.run("global mcp_graph_list `r(list)'")
                        graph_list_str = Macro.getGlobal("mcp_graph_list")
                        return graph_list_str.split() if graph_list_str else []
                    except ImportError:
                        logger.warning("sfi.Macro not available for fallback graph detection")
                        return []
                else:
                    return []
        except Exception as e:
            logger.warning(f"Failed to get current graphs from pystata: {e}")
            return []
    
    def _get_graph_state_from_pystata(self) -> Dict[str, Any]:
        """Get detailed graph state information using pystata's sfi interface."""
        graph_state = {}
        
        try:
            current_graphs = self._get_current_graphs_from_pystata()
            
            for graph_name in current_graphs:
                try:
                    # Get graph metadata using available sfi interface
                    # Since there's no Graph class in sfi, we'll use basic state tracking
                    state_info = {
                        'name': graph_name,
                        'timestamp': time.time(),
                        'exists': True
                    }
                    
                    # Try to get additional graph properties via stata commands if available
                    if self._stata_client and hasattr(self._stata_client, 'stata'):
                        try:
                            # Use stata commands to get graph info
                            self._stata_client.stata.run(f'graph describe {graph_name}', quietly=True)
                            # If successful, the graph exists and is valid
                            state_info['valid'] = True
                        except Exception:
                            state_info['valid'] = False
                    
                    graph_state[graph_name] = state_info
                    
                except Exception as e:
                    logger.warning(f"Failed to get state for graph {graph_name}: {e}")
                    graph_state[graph_name] = {'name': graph_name, 'timestamp': time.time(), 'exists': False}
            
        except Exception as e:
            logger.warning(f"Failed to get graph state from pystata: {e}")
        
        return graph_state
    
        
        
    def detect_graph_modifications(self, text: str = None) -> dict:
        """Detect graph modification/removal using SFI state comparison."""
        modifications = {"dropped": [], "renamed": [], "cleared": False}
        
        if not self._stata_client:
            return modifications
        
        try:
            # Get current graph state via SFI
            current_graphs = set(self._get_current_graphs_from_pystata())
            
            # Compare with last known state to detect modifications
            if self._last_graph_state:
                last_graphs = set(self._last_graph_state.keys())
                
                # Detect dropped graphs (in last state but not current)
                dropped_graphs = last_graphs - current_graphs
                modifications["dropped"].extend(dropped_graphs)
                
                # Detect clear all (no graphs remain when there were some before)
                if last_graphs and not current_graphs:
                    modifications["cleared"] = True
            
            # Update last known state for next comparison
            self._last_graph_state = {graph: {'name': graph, 'timestamp': time.time(), 'exists': True} 
                                     for graph in current_graphs}
            
        except Exception as e:
            logger.debug(f"SFI modification detection failed: {e}")
        
        return modifications
    
        
    def should_cache_graph(self, graph_name: str) -> bool:
        """Determine if a graph should be cached."""
        with self._lock:
            # Don't cache if already detected or removed
            if graph_name in self._detected_graphs or graph_name in self._removed_graphs:
                return False
            
            # Mark as detected
            self._detected_graphs.add(graph_name)
            return True
    
    def mark_graph_removed(self, graph_name: str) -> None:
        """Mark a graph as removed."""
        with self._lock:
            self._removed_graphs.add(graph_name)
            self._detected_graphs.discard(graph_name)
    
    def mark_all_cleared(self) -> None:
        """Mark all graphs as cleared."""
        with self._lock:
            self._detected_graphs.clear()
            self._removed_graphs.clear()
    
    def clear_detection_state(self) -> None:
        """Clear all detection state."""
        with self._lock:
            self._detected_graphs.clear()
            self._removed_graphs.clear()
            self._unnamed_graph_counter = 0
    
    def process_modifications(self, modifications: dict) -> None:
        """Process detected modifications."""
        with self._lock:
            # Handle dropped graphs
            for graph_name in modifications.get("dropped", []):
                self.mark_graph_removed(graph_name)
            
            # Handle renamed graphs
            for old_name, new_name in modifications.get("renamed", []):
                self.mark_graph_removed(old_name)
                self._detected_graphs.discard(new_name)  # Allow re-detection with new name
            
            # Handle clear all
            if modifications.get("cleared", False):
                self.mark_all_cleared()


class StreamingGraphCache:
    """Integrates graph detection with caching during streaming."""
    
    def __init__(self, stata_client, auto_cache: bool = False):
        self.stata_client = stata_client
        self.auto_cache = auto_cache
        self.detector = GraphCreationDetector(stata_client)
        self._lock = threading.Lock()
        self._cache_callbacks: List[Callable[[str, bool], None]] = []
        self._graphs_to_cache: List[str] = []
        self._cached_graphs: Set[str] = set()
        self._removed_graphs = set()  # Track removed graphs directly
    
    def add_cache_callback(self, callback: Callable[[str, bool], None]) -> None:
        """Add callback for graph cache events."""
        with self._lock:
            self._cache_callbacks.append(callback)
    
    def process_streaming_chunk(self, chunk: str, current_graph_list: List[str] = None) -> None:
        """Process a chunk of streaming output using SFI-only graph detection.
        
        Args:
            chunk: Stata output text (ignored - SFI provides authoritative state)
            current_graph_list: Current list of graphs from Stata (ignored - SFI provides this)
        """
        if not self.auto_cache:
            return
        
        if not self.stata_client:
            return
        
        detected_graphs = []
        
        # SFI-only detection - no text parsing fallbacks
        try:
            # Use pystata-integrated detection as the only method
            sfi_detected = self.detector._detect_graphs_via_pystata()
            detected_graphs.extend(sfi_detected)
            
        except Exception as e:
            logger.debug(f"SFI detection failed during streaming: {e}")
            return
        
        # Detect modifications using SFI
        modifications = self.detector.detect_graph_modifications()
        if modifications.get("dropped") or modifications.get("cleared"):
            self.detector.process_modifications(modifications)
            
            # Handle cache invalidation for dropped graphs
            for graph_name in modifications.get("dropped", []):
                self._removed_graphs.add(graph_name)
                try:
                    self.stata_client.invalidate_graph_cache(graph_name)
                except Exception:
                    pass
            
            if modifications.get("cleared", False):
                self._removed_graphs.clear()
                try:
                    self.stata_client.invalidate_graph_cache()
                except Exception:
                    pass
        
        # Add detected graphs to cache queue
        for graph_name in detected_graphs:
            if graph_name not in self._removed_graphs:
                try:
                    self._graphs_to_cache.append(graph_name)
                except Exception:
                    pass
    
    async def cache_detected_graphs_with_pystata(self) -> List[str]:
        """Enhanced caching method that uses pystata for real-time graph detection."""
        if not self.auto_cache:
            return []
        
        cached_names = []
        
        # First, try to get any newly detected graphs via pystata state
        if self.stata_client:
            try:
                # Get current state and check for new graphs

                pystata_detected = self.detector._detect_graphs_via_pystata()
                
                # Add any newly detected graphs to cache queue
                for graph_name in pystata_detected:
                    if graph_name not in self._cached_graphs and graph_name not in self._removed_graphs:
                        self._graphs_to_cache.append(graph_name)
                        
            except Exception as e:
                logger.warning(f"Failed to get pystata graph updates: {e}")
        
        # Process the cache queue
        with self._lock:
            graphs_to_process = self._graphs_to_cache.copy()
            self._graphs_to_cache.clear()
        
        # Get current graph list for verification
        try:
            current_graphs = self.stata_client.list_graphs()
        except Exception as e:
            logger.warning(f"Failed to get current graph list: {e}")
            return cached_names
        
        for graph_name in graphs_to_process:
            if graph_name in current_graphs and graph_name not in self._cached_graphs:
                try:
                    success = await asyncio.to_thread(self.stata_client.cache_graph_on_creation, graph_name)
                    if success:
                        cached_names.append(graph_name)
                        with self._lock:
                            self._cached_graphs.add(graph_name)
                    
                    # Notify callbacks
                    for callback in self._cache_callbacks:
                        try:
                            callback(graph_name, success)
                        except Exception as e:
                            logger.warning(f"Cache callback failed for {graph_name}: {e}")
                
                except Exception as e:
                    logger.warning(f"Failed to cache graph {graph_name}: {e}")
                    # Still notify callbacks of failure
                    for callback in self._cache_callbacks:
                        try:
                            callback(graph_name, False)
                        except Exception:
                            pass
        
        return cached_names
    
    async def cache_detected_graphs(self) -> List[str]:
        """Cache all detected graphs."""
        if not self.auto_cache:
            return []
        
        cached_names = []
        
        with self._lock:
            graphs_to_process = self._graphs_to_cache.copy()
            self._graphs_to_cache.clear()
        
        # Get current graph list for verification
        try:
            current_graphs = self.stata_client.list_graphs()
        except Exception as e:
            logger.warning(f"Failed to get current graph list: {e}")
            return cached_names
        
        for graph_name in graphs_to_process:
            if graph_name in current_graphs and graph_name not in self._cached_graphs:
                try:
                    success = await asyncio.to_thread(self.stata_client.cache_graph_on_creation, graph_name)
                    if success:
                        cached_names.append(graph_name)
                        with self._lock:
                            self._cached_graphs.add(graph_name)
                    
                    # Notify callbacks
                    for callback in self._cache_callbacks:
                        try:
                            callback(graph_name, success)
                        except Exception as e:
                            logger.warning(f"Cache callback failed for {graph_name}: {e}")
                
                except Exception as e:
                    logger.warning(f"Failed to cache graph {graph_name}: {e}")
                    # Still notify callbacks of failure
                    for callback in self._cache_callbacks:
                        try:
                            callback(graph_name, False)
                        except Exception:
                            pass
        
        return cached_names
    
    def get_cache_stats(self) -> dict:
        """Get caching statistics."""
        with self._lock:
            return {
                "auto_cache_enabled": self.auto_cache,
                "pending_cache_count": len(self._graphs_to_cache),
                "cached_graphs_count": len(self._cached_graphs),
                "detected_graphs_count": len(self.detector._detected_graphs),
                "removed_graphs_count": len(self.detector._removed_graphs),
            }
    
    def reset(self) -> None:
        """Reset the cache state."""
        with self._lock:
            self._graphs_to_cache.clear()
            self._cached_graphs.clear()
        self.detector.clear_detection_state()
