import sys
import os
import json
import logging
from typing import Any, List, Optional, Dict
import pandas as pd
from .discovery import find_stata_path

logger = logging.getLogger("stata_mcp")

class StataClient:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(StataClient, cls).__new__(cls)
        return cls._instance

    def init(self):
        """Initializes usage of pystata."""
        if self._initialized:
            return

        try:
            # 1. Setup config
            # 1. Setup config
            import stata_setup
            stata_exec_path, edition = find_stata_path()
            logger.info(f"Discovery found Stata at: {stata_exec_path} ({edition})")
            
            # Helper to try init
            def tries_init(path_to_try):
                try:
                    logger.info(f"Attempting stata_setup.config with: {path_to_try}")
                    stata_setup.config(path_to_try, edition)
                    return True
                except Exception as e:
                    logger.warning(f"Init failed with {path_to_try}: {e}")
                    return False

            success = False
            candidates = []
            
            # 1. Binary Dir: .../Contents/MacOS
            bin_dir = os.path.dirname(stata_exec_path)
            
            # 2. App Bundle: .../StataMP.app
            # Walk up to find .app
            curr = bin_dir
            app_bundle = None
            while len(curr) > 1:
                if curr.endswith(".app"):
                    app_bundle = curr
                    break
                curr = os.path.dirname(curr)
                
            if app_bundle:
                # Priority 1: The installation root (parent of .app)
                candidates.append(os.path.dirname(app_bundle))
                
                # Priority 2: The .app bundle itself
                candidates.append(app_bundle)
            
            # Priority 3: The binary directory
            candidates.append(bin_dir)
            
            for path in candidates:
                if tries_init(path):
                    success = True
                    break
            
            if not success:
                raise RuntimeError(
                    f"stata_setup.config failed. Tried: {candidates}. "
                    f"Derived from binary: {stata_exec_path}"
                )
            
            # 2. Import pystata
            from pystata import stata
            self.stata = stata
            self._initialized = True
            
        except ImportError:
            # Fallback for when stata_setup isn't in PYTHONPATH yet?
            # Usually users must have it installed. We rely on discovery logic.
            raise RuntimeError("Could not import `stata_setup`. Ensure pystata is installed.")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Stata: {e}")

    def run_command(self, code: str, echo: bool = True) -> str:
        """Runs a Stata command and captures output."""
        if not self._initialized:
            self.init()
            
        # Capture stdout
        
        # Using simple redirection as pystata writes to stdout
        from io import StringIO
        backup_stdout = sys.stdout
        capture = StringIO()
        sys.stdout = capture
        
        try:
            self.stata.run(code, echo=echo)
        except Exception as e:
            sys.stdout = backup_stdout
            return f"Error executing Stata code: {e}"
        finally:
            sys.stdout = backup_stdout
            
        return capture.getvalue()

    def get_data(self, start: int = 0, count: int = 50) -> List[Dict[str, Any]]:
        """Returns valid JSON-serializable data."""
        if not self._initialized:
            self.init()
            
        try:
            # Use pystata integration to retrieve data
            df = self.stata.pdataframe_from_data()
            
            # Slice
            sliced = df.iloc[start : start + count]
            
            # Convert to dict
            return sliced.to_dict(orient="records")
        except Exception as e:
            return [{"error": f"Failed to retrieve data: {e}"}]

    def list_variables(self) -> List[Dict[str, str]]:
        """Returns list of variables with labels."""
        if not self._initialized:
            self.init()
            
        # We can use sfi to be efficient
        from sfi import Data
        vars_info = []
        for i in range(Data.getVarCount()):
            var_index = i # 0-based
            name = Data.getVarName(var_index)
            label = Data.getVarLabel(var_index)
            type_str = Data.getVarType(var_index) # Returns int
            
            vars_info.append({
                "name": name,
                "label": label,
                # Simple type map could be added, but name/label is most useful
            })
        return vars_info

    def get_variable_details(self, varname: str) -> str:
        """Returns codebook/summary for a specific variable."""
        return self.run_command(f"codebook {varname}")

    def list_graphs(self) -> List[str]:
        """Returns list of graphs in memory."""
        # 'graph dir' returns list in r(list)
        # We need to ensure we run it quietly so we don't spam.
        self.stata.run("quietly graph dir, memory")
        
        # Accessing r-class results in Python can be tricky via pystata's run command.
        # We stash the result in a global macro that python sfi can easily read.
        from sfi import Macro
        self.stata.run("global mcp_graph_list `r(list)'")
        graph_list_str = Macro.getGlobal("mcp_graph_list")
        if not graph_list_str:
            return []
        
        return graph_list_str.split()

    def export_graph(self, graph_name: str = None, filename: str = None) -> str:
        """Exports graph to a temp file and returns path."""
        import tempfile
        if not filename:
            filename = os.path.join(tempfile.gettempdir(), "stata_mcp_graph.png")
            
        # Ensure fresh start
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except: pass
            
        cmd = "graph export"
        if graph_name:
            cmd += f' "{filename}", name("{graph_name}") replace'
        else:
            cmd += f' "{filename}", replace'
            
        output = self.run_command(cmd)
        
        if os.path.exists(filename):
            return filename
            
        # If file missing, it failed. Check output for details.
        if "not found" in output or "error" in output.lower():
            raise RuntimeError(f"Graph export failed: {output}")
            
        raise FileNotFoundError(f"Graph export failed, file not found. Stata output: {output}")

    def get_help(self, topic: str) -> str:
        """Returns help text."""
        # Try to locate the .sthlp help file
        # We use 'capture' to avoid crashing if not found
        self.stata.run(f"capture findfile {topic}.sthlp")
        
        # Retrieve the found path from r(fn)
        from sfi import Macro
        self.stata.run("global mcp_help_file `r(fn)'")
        fn = Macro.getGlobal("mcp_help_file")
        
        if fn and os.path.exists(fn):
            try:
                with open(fn, 'r', encoding='utf-8', errors='replace') as f:
                    return f.read()
            except Exception as e:
                return f"Error reading help file at {fn}: {e}"

        # Fallback to URL if file not found
        return f"Help file for '{topic}' not found. Please consult: https://www.stata.com/help.cgi?{topic}"

    def get_stored_results(self) -> Dict[str, Any]:
        """Returns e() and r() results."""
        if not self._initialized:
            self.init()
            
        from sfi import Scalar, Macro
        
        results = {"r": {}, "e": {}}
        
        # We parse 'return list' output as there is no direct bulk export of stored results
        raw_r = self.run_command("return list")
        raw_e = self.run_command("ereturn list")
        
        # Simple parser
        def parse_list(text):
            data = {}
            # We don't strictly need to track sections if we check patterns
            for line in text.splitlines():
                line = line.strip()
                if not line: continue
                
                # scalars: r(name) = value
                if "=" in line and ("r(" in line or "e(" in line):
                    try:
                        name_part, val_part = line.split("=", 1)
                        name_part = name_part.strip()  # "r(mean)"
                        val_part = val_part.strip()    # "6165.2..."
                        
                        # Extract just the name inside r(...) if desired, 
                        # or keep full key "r(mean)". 
                        # User likely wants "mean" inside "r" dict.
                        
                        if "(" in name_part and name_part.endswith(")"):
                            # r(mean) -> mean
                            start = name_part.find("(") + 1
                            end = name_part.find(")")
                            key = name_part[start:end]
                            data[key] = val_part
                    except: pass
                    
                # macros: r(name) : "value"
                elif ":" in line and ("r(" in line or "e(" in line):
                     try:
                        name_part, val_part = line.split(":", 1)
                        name_part = name_part.strip()
                        val_part = val_part.strip().strip('"')
                        
                        if "(" in name_part and name_part.endswith(")"):
                            start = name_part.find("(") + 1
                            end = name_part.find(")")
                            key = name_part[start:end]
                            data[key] = val_part
                     except: pass
            return data
            
        results["r"] = parse_list(raw_r)
        results["e"] = parse_list(raw_e)
        
        return results

