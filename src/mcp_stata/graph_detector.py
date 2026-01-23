from __future__ import annotations
"""
Graph creation detection for streaming Stata output.

This module provides functionality to detect when graphs are created
during Stata command execution and automatically cache them.
"""

import asyncio
import contextlib
import inspect
import re
import threading
import time
from typing import List, Set, Callable, Dict, Any
import logging
import uuid
import shlex


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
        self._inventory_cache: Dict[str, Any] = {
            "timestamp": 0.0,
            "graphs": [],
            "timestamps": {},
        }
        self._inventory_cache_ttl = 0.5
        self._inventory_cache_enabled = False

    def _describe_graph_signature(self, graph_name: str) -> str:
        """Return a stable signature for a graph.

        We use name-based tracking tied to the Stata command execution 
        context, enriched with timestamps where available.
        """
        if not self._stata_client:
            return ""
        
        # Try to find timestamp in client's cache first for cross-command stability
        cache = getattr(self._stata_client, "_list_graphs_cache", None)
        if cache:
            for g in cache:
                # Cache might contain GraphInfo objects
                name = getattr(g, "name", g if isinstance(g, str) else None)
                created = getattr(g, "created", None)
                if name == graph_name and created:
                    return f"{graph_name}_{created}"

        # Fallback to command_idx
        cmd_idx = getattr(self._stata_client, "_command_idx", 0)
        return f"{graph_name}_{cmd_idx}"

    def _get_graph_inventory(self, *, need_timestamps: bool = True) -> tuple[List[str], Dict[str, str]]:
        """Get both the list of graphs and their timestamps in a single Stata call."""
        if not self._stata_client or not hasattr(self._stata_client, "stata"):
            return [], {}
        if self._inventory_cache_enabled:
            now = time.monotonic()
            cached = self._inventory_cache
            if cached["graphs"] and (now - cached["timestamp"]) < self._inventory_cache_ttl:
                if need_timestamps:
                    if cached["timestamps"]:
                        return list(cached["graphs"]), dict(cached["timestamps"])
                else:
                    return list(cached["graphs"]), {}
            
        try:
            # Use the lock from client to prevent concurrency issues with pystata
            exec_lock = getattr(self._stata_client, "_exec_lock", None)
            ctx = exec_lock if exec_lock else contextlib.nullcontext()
            
            with ctx:
                hold_name = f"_mcp_detector_inv_{int(time.time() * 1000 % 1000000)}"
                from sfi import Macro
                
                # Bundle to get everything in one round trip
                # 1. Hold results
                # 2. Get list of graphs in memory
                # 3. Store list in global
                # 4. Loop over list to get timestamps
                # 5. Restore results
                bundle = [
                    f"capture _return hold {hold_name}",
                    "quietly graph dir, memory",
                    "local list `r(list)'",
                    "macro define mcpinvlist \"`r(list)'\"",
                    "local i = 0",
                ]

                if need_timestamps:
                    bundle.extend([
                        "foreach g of local list {",
                        "  capture quietly graph describe `g'",
                        "  macro define mcpinvts`i' \"`r(command_date)'_`r(command_time)'\"",
                        "  local i = `i' + 1",
                        "}",
                    ])

                bundle.extend([
                    "macro define mcpinvcount \"`i'\"",
                    f"capture _return restore {hold_name}",
                ])
                
                self._stata_client.stata.run("\n".join(bundle), echo=False)
                
                # Fetch result list
                raw_list_str = Macro.getGlobal("mcpinvlist")
                count_str = Macro.getGlobal("mcpinvcount")
                
                if not raw_list_str:
                    return [], {}
                    
                # Handle quoted names if any (spaces in names)
                try:
                    graph_names = shlex.split(raw_list_str)
                except Exception:
                    graph_names = raw_list_str.split()
                
                # Map internal names back to user-facing names if aliases exist
                reverse = getattr(self._stata_client, "_graph_name_reverse", {})
                user_names = [reverse.get(n, n) for n in graph_names]
                
                # Fetch timestamps and map them to user names
                count = int(float(count_str)) if count_str else 0
                
                timestamps = {}
                if need_timestamps:
                    for i in range(count):
                        ts = Macro.getGlobal(f"mcpinvts{i}")
                        if ts and i < len(user_names):
                            # Use user_names to match what the rest of the system expects
                            timestamps[user_names[i]] = ts

                self._inventory_cache = {
                    "timestamp": time.monotonic(),
                    "graphs": list(user_names),
                    "timestamps": dict(timestamps),
                }
                        
                return user_names, timestamps
        except Exception as e:
            logger.debug(f"Inventory fetch failed: {e}")
            return [], {}
        except Exception as e:
            logger.debug(f"Inventory fetch failed: {e}")
            return [], {}

    def _get_graph_timestamp(self, graph_name: str) -> str:
        """Get the creation/modification timestamp of a graph using graph describe.
        
        The result is cached per command to optimize performance during streaming.
        """
        results = self._get_graph_timestamps([graph_name])
        return results.get(graph_name, "")

    def _get_graph_timestamps(self, graph_names: List[str]) -> Dict[str, str]:
        """Get timestamps for multiple graphs in a single Stata call to minimize overhead."""
        if not graph_names or not self._stata_client or not hasattr(self._stata_client, "stata"):
            return {}
        
        try:
            # Use the lock from client to prevent concurrency issues with pystata
            exec_lock = getattr(self._stata_client, "_exec_lock", None)
            ctx = exec_lock if exec_lock else contextlib.nullcontext()
            
            with ctx:
                hold_name = f"_mcp_detector_thold_{int(time.time() * 1000 % 1000000)}"
                self._stata_client.stata.run(f"capture _return hold {hold_name}", echo=False)
                try:
                    # Build a single Stata command to fetch all timestamps
                    stata_cmd = ""
                    for i, name in enumerate(graph_names):
                        resolved = self._stata_client._resolve_graph_name_for_stata(name)
                        stata_cmd += f"quietly graph describe {resolved}\n"
                        stata_cmd += f"macro define mcp_ts_{i} \"`r(command_date)'_`r(command_time)'\"\n"
                    
                    self._stata_client.stata.run(stata_cmd, echo=False)
                    
                    from sfi import Macro
                    results = {}
                    for i, name in enumerate(graph_names):
                        ts = Macro.getGlobal(f"mcp_ts_{i}")
                        if ts:
                            results[name] = ts
                    return results
                finally:
                    self._stata_client.stata.run(f"capture _return restore {hold_name}", echo=False)
        except Exception as e:
            logger.debug(f"Failed to get timestamps: {e}")
            return {}
    
    def _detect_graphs_via_pystata(self) -> List[str]:
        """Detect newly created graphs using direct pystata state access."""
        if not self._stata_client:
            return []
        
        with self._lock:
            try:
                # Get current graph state - this now uses a single bundle (1 round trip)
                current_state = self._get_graph_state_from_pystata()
                current_graphs = list(current_state.keys())
                
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
                        # Compare stable signature.
                        if state.get("signature") != last_state.get("signature"):
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
                graphs = self._stata_client.list_graphs(force_refresh=True)
                if graphs:
                    return graphs
                # Fallback to inventory if list_graphs is empty
                try:
                    inventory, _timestamps = self._get_graph_inventory(need_timestamps=False)
                    if inventory:
                        return inventory
                except Exception:
                    return []
                # Brief retry to allow graph registration to settle
                time.sleep(0.05)
                graphs = self._stata_client.list_graphs(force_refresh=True)
                if graphs:
                    return graphs
                try:
                    inventory, _timestamps = self._get_graph_inventory(need_timestamps=False)
                    return inventory
                except Exception:
                    return []
            else:
                # Fallback to sfi Macro interface - only if stata is available
                if self._stata_client and hasattr(self._stata_client, 'stata'):
                    # Access the lock from client to prevent concurrency issues with pystata
                    exec_lock = getattr(self._stata_client, "_exec_lock", None)
                    ctx = exec_lock if exec_lock else contextlib.nullcontext()
                    
                    with ctx:
                        try:
                            from sfi import Macro
                            hold_name = f"_mcp_det_{int(time.time() * 1000 % 1000000)}"
                            self._stata_client.stata.run(f"capture _return hold {hold_name}", echo=False)
                            try:
                                # Run graph dir quietly
                                self._stata_client.stata.run("quietly graph dir, memory", echo=False)
                                # Get r(list) DIRECTLY via SFI Macro interface to avoid parsing issues 
                                # and syntax errors with empty results.
                                self._stata_client.stata.run("macro define mcp_detector_list `r(list)'", echo=False)
                                graph_list_str = Macro.getGlobal("mcp_detector_list")
                            finally:
                                self._stata_client.stata.run(f"capture _return restore {hold_name}", echo=False)
                            
                            if not graph_list_str:
                                return []
                            
                            # Handle quoted names from r(list) - Stata quotes names with spaces
                            import shlex
                            try:
                                return shlex.split(graph_list_str)
                            except Exception:
                                return graph_list_str.split()
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
            # Combined fetch for both list and timestamps (1 round trip)
            current_graphs, timestamps = self._get_graph_inventory()
            cmd_idx = getattr(self._stata_client, "_command_idx", 0)
            
            for graph_name in current_graphs:
                try:
                    # Signature logic:
                    # Prefer stable timestamps across commands to avoid duplicate notifications.
                    fast_sig = self._describe_graph_signature(graph_name)

                    prev = self._last_graph_state.get(graph_name)
                    timestamp = timestamps.get(graph_name)

                    if prev and prev.get("cmd_idx") == cmd_idx:
                        # Already processed in this command context.
                        sig = prev.get("signature")
                    elif timestamp:
                        # Use timestamp-stable signature across commands when available.
                        sig = f"{graph_name}_{timestamp}"
                    else:
                        # Fallback to command-index-based signature.
                        sig = fast_sig
                    
                    state_info = {
                        "name": graph_name,
                        "exists": True,
                        "valid": bool(sig),
                        "signature": sig,
                        "cmd_idx": cmd_idx,
                        "timestamp_val": timestamp,
                    }

                    # Only update visual timestamps when the signature changes.
                    if prev is None or prev.get("signature") != sig:
                        state_info["timestamp"] = time.time()
                    else:
                        state_info["timestamp"] = prev.get("timestamp", time.time())
                    
                    graph_state[graph_name] = state_info
                    
                except Exception as e:
                    logger.warning(f"Failed to get state for graph {graph_name}: {e}")
                    graph_state[graph_name] = {"name": graph_name, "timestamp": time.time(), "exists": False, "signature": "", "cmd_idx": cmd_idx}
            
        except Exception as e:
            logger.warning(f"Failed to get graph state from pystata: {e}")
        
        return graph_state
    
        
        
    def detect_graph_modifications(self, text: str = None) -> dict:
        """Detect graph modification/removal using SFI state comparison."""
        modifications = {"dropped": [], "renamed": [], "cleared": False}
        
        if not self._stata_client:
            return modifications
        
        try:
            # Use the more sophisticated state retrieval that handles timestamp verification
            new_state = self._get_graph_state_from_pystata()
            current_graphs = set(new_state.keys())
            
            # Compare with last known state to detect modifications
            if self._last_graph_state:
                last_graphs = set(self._last_graph_state.keys())
                
                # Detect dropped graphs (in last state but not current)
                dropped_graphs = last_graphs - current_graphs
                modifications["dropped"].extend(dropped_graphs)
                
                # Detect clear all (no graphs remain when there were some before)
                if last_graphs and not current_graphs:
                    modifications["cleared"] = True
            
            # Update last known state
            self._last_graph_state = new_state
            
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
        # Use persistent detector from client if available, else create local one
        if hasattr(stata_client, "_graph_detector"):
            self.detector = stata_client._graph_detector
        else:
            self.detector = GraphCreationDetector(stata_client)
        self._lock = threading.Lock()
        self._cache_callbacks: List[Callable[[str, bool], None]] = []
        self._graphs_to_cache: List[str] = []
        self._cached_graphs: Set[str] = set()
        self._removed_graphs = set()  # Track removed graphs directly
        self._initial_graphs: Set[str] = set()  # Captured before execution starts
    
    def add_cache_callback(self, callback: Callable[[str, bool], None]) -> None:
        """Add callback for graph cache events."""
        with self._lock:
            self._cache_callbacks.append(callback)

    async def _notify_cache_callbacks(self, graph_name: str, success: bool) -> None:
        for callback in self._cache_callbacks:
            try:
                result = callback(graph_name, success)
                if inspect.isawaitable(result):
                    await result
            except Exception as e:
                logger.warning(f"Cache callback failed for {graph_name}: {e}")

    
    async def cache_detected_graphs_with_pystata(self) -> List[str]:
        """Enhanced caching method that uses pystata for real-time graph detection."""
        if not self.auto_cache:
            return []
        
        cached_names = []
        
        # First, try to get any newly detected graphs via pystata state
        if self.stata_client:
            try:
                # Get current state and check for new graphs
                # _detect_graphs_via_pystata is sync and uses _exec_lock, must run in thread
                import anyio
                self.detector._inventory_cache_enabled = True
                try:
                    pystata_detected = await anyio.to_thread.run_sync(self.detector._detect_graphs_via_pystata)
                finally:
                    self.detector._inventory_cache_enabled = False
                
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

        if not graphs_to_process:
            return cached_names
        
        # Get current graph list for verification
        try:
            # list_graphs is sync and uses _exec_lock, must run in thread
            import anyio
            current_graphs = await anyio.to_thread.run_sync(self.stata_client.list_graphs)
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
                    await self._notify_cache_callbacks(graph_name, success)
                
                except Exception as e:
                    logger.warning(f"Failed to cache graph {graph_name}: {e}")
                    # Still notify callbacks of failure
                    await self._notify_cache_callbacks(graph_name, False)
        
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
            # list_graphs is sync and uses _exec_lock, must run in thread
            import anyio
            current_graphs = await anyio.to_thread.run_sync(self.stata_client.list_graphs)
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
                    await self._notify_cache_callbacks(graph_name, success)
                
                except Exception as e:
                    logger.warning(f"Failed to cache graph {graph_name}: {e}")
                    # Still notify callbacks of failure
                    await self._notify_cache_callbacks(graph_name, False)
        
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
