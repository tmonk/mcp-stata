import time
import sys
import os
from unittest.mock import MagicMock

# Mock sfi and stata_setup if not available, just to load the module for inspection
# But for real testing we need them. 
# We will assume this script is run in an environment where mcp_stata is importable.

try:
    import stata_setup
    stata_setup.config("/Applications/StataNow/", "mp")
except ImportError:
    print("stata_setup not found. Ensure it is installed.")
except Exception as e:
    print(f"Failed to configure Stata: {e}")

try:
    from mcp_stata.stata_client import StataClient
except ImportError:
    # Try adding src to path
    sys.path.insert(0, os.path.abspath("src"))
    from mcp_stata.stata_client import StataClient

def benchmark_polars_stream():
    print("Initializing StataClient...")
    client = StataClient()
    
    # We can't easily mock the internal SFI calls without extensive mocking.
    # This script assumes it's being run in an environment with Stata access.
    # If not, it will fail gracefully.
    
    try:
        from sfi import Data
    except ImportError:
        print("sfi module not found. This script must be run within a Stata python environment or with pystata configured.")
        print("Mocking for dry-run verification of import logic...")
        # Mock sfi for structural verification
        sys.modules["sfi"] = MagicMock()
        sys.modules["pystata"] = MagicMock()
        return

    print("Generating large dataset in Stata...")
    try:
        client.run_command_structured("clear")
        client.run_command_structured("set obs 1000")
        # Create 3000 variables
        # This might be slow to generate in Stata loop, so we generate a few and expand?
        # Or just use a smaller number for quick test, but large enough to see column-wise benefit.
        # 1000 vars is minimal.
        
        # Faster generation: matrix
        client.run_command_structured("mkmat price mpg rep78 headroom trunk weight length turn displacement gear_ratio foreign, matrix(X)")
        # Actually simplest is just:
        client.run_command_structured("set obs 1000")
        client.run_command_structured("forvalues i=1/3000 { \n generate v`i' = runiform() \n }")
    except Exception as e:
        print(f"Failed to generate data: {e}")
        return

    vars = [f"v{i}" for i in range(1, 3001)]
    
    print(f"Benchmarking get_arrow_stream with {len(vars)} variables and 1000 observations...")
    
    start = time.time()
    arrow_bytes = client.get_arrow_stream(offset=0, limit=1000, vars=vars, include_obs_no=True)
    end = time.time()
    
    print(f"Time taken (Polars): {end - start:.4f} seconds")
    print(f"Bytes received (Polars): {len(arrow_bytes)}")
    return end - start

def benchmark_pandas_stream():
    """
    Simulates the old Pandas-based implementation for comparison.
    """
    print("\nBenchmarking Pandas-based implementation...")
    import pandas as pd
    import pyarrow as pa
    from pystata import stata
    
    # Re-initialize client to be safe (ensure connected)
    client = StataClient()
    
    # We need to access the internal pystata object or mimicking the old helper
    
    vars = [f"v{i}" for i in range(1, 3001)]
    obs_list = list(range(1000)) # 0-based index for 1000 rows
    
    print(f"Fetching {len(vars)} variables and 1000 observations (Pandas)...")
    start = time.time()
    
    # Logic from old get_arrow_stream
    df = stata.pdataframe_from_data(var=vars, obs=obs_list, missingval=None)
    
    # Add _n
    obs_nums = [i + 1 for i in obs_list]
    df.insert(0, "_n", obs_nums)

    table = pa.Table.from_pandas(df, preserve_index=False)
    
    sink = pa.BufferOutputStream()
    with pa.RecordBatchStreamWriter(sink, table.schema) as writer:
        writer.write_table(table)
    
    arrow_bytes = sink.getvalue().to_pybytes()
    
    end = time.time()
    print(f"Time taken (Pandas): {end - start:.4f} seconds")
    print(f"Bytes received (Pandas): {len(arrow_bytes)}")
    return end - start

def benchmark_sfi_bulk_stream():
    """
    Simulates single SFI bulk get call + Polars.
    """
    print("\nBenchmarking SFI Bulk + Polars...")
    import polars as pl
    import pyarrow as pa
    from sfi import Data
    
    vars = [f"v{i}" for i in range(1, 3001)]
    obs_list = list(range(1000))
    
    print(f"Fetching {len(vars)} variables and 1000 observations (SFI Bulk)...")
    start = time.time()
    
    # Single call to get list of lists
    raw_data = Data.get(var=vars, obs=obs_list, valuelabel=False)
    
    # Logic: Data.get returns [[row1], [row2], ...]
    # Polars can ingest this
    df = pl.DataFrame(raw_data, schema=vars, orient="row")
    
    # VERIFICATION: logic for specific variable selection
    # `Data.get(var=vars, ...)` ensures only requested vars are fetched from Stata.
    # No "select * from dataset" happens here.
    assert df.shape[1] == 3000, "Should have fetched exactly 3000 variables"
    
    if True: # include_obs_no
        obs_nums = [i + 1 for i in obs_list]
        df = df.with_columns(pl.Series("_n", obs_nums).alias("_n"))
        # Move to front? Polars doesn't strictly need column order for Arrow schema unless required
        df = df.select(["_n"] + vars)
        
    table = df.to_arrow()
    
    sink = pa.BufferOutputStream()
    with pa.RecordBatchStreamWriter(sink, table.schema) as writer:
        writer.write_table(table)
    
    arrow_bytes = sink.getvalue().to_pybytes()
    
    end = time.time()
    print(f"Time taken (SFI Bulk): {end - start:.4f} seconds")
    print(f"Bytes received (SFI Bulk): {len(arrow_bytes)}")
    return end - start

def benchmark_numpy_polars_stream():
    """
    Simulates stata.nparray_from_data + Polars.
    """
    print("\nBenchmarking Numpy + Polars...")
    import polars as pl
    import pyarrow as pa
    from pystata import stata
    
    vars = [f"v{i}" for i in range(1, 3001)]
    obs_list = list(range(1000))
    
    print(f"Fetching {len(vars)} variables and 1000 observations (Numpy)...")
    start = time.time()
    
    # Get numpy array
    arr = stata.nparray_from_data(var=vars, obs=obs_list)
    
    # Convert to Polars
    # Use schema to set names
    df = pl.DataFrame(arr, schema=vars)
    
    if True: # include_obs_no
        obs_nums = [i + 1 for i in obs_list]
        df = df.with_columns(pl.Series("_n", obs_nums).alias("_n"))
        df = df.select(["_n"] + vars)

    table = df.to_arrow()
    
    sink = pa.BufferOutputStream()
    with pa.RecordBatchStreamWriter(sink, table.schema) as writer:
        writer.write_table(table)
    
    arrow_bytes = sink.getvalue().to_pybytes()
    
    end = time.time()
    if t_csv:    print(f"Polars (CSV):      {t_csv:.4f}s")


def benchmark_strings_stream():
    """
    Benchmarks performance with String data.
    """
    print("\nBenchmarking String Data (SFI Bulk)...")
    import polars as pl
    import pyarrow as pa
    from sfi import Data
    from mcp_stata.stata_client import StataClient

    client = StataClient()
    try:
        # Create dataset with string variables
        client.run_command_structured("clear")
        client.run_command_structured("set obs 1000")
        # Generate 1000 string variables
        # Using a loop to generate string data
        client.run_command_structured('forvalues i=1/1000 { \n generate str10 s`i\' = "StringVal" \n }') 
    except Exception as e:
        print(f"String generation failed: {e}")
        return None

    vars = [f"s{i}" for i in range(1, 1001)] # 1000 string vars
    obs_list = list(range(1000))
    
    print(f"Fetching {len(vars)} string variables and 1000 observations...")
    start = time.time()
    
    # Bulk get strings
    raw_data = Data.get(var=vars, obs=obs_list, valuelabel=False)
    
    # Convert to Polars
    # Schema must handle strings? Polars infers Utf8
    df = pl.DataFrame(raw_data, schema=vars, orient="row")
    
    table = df.to_arrow()
    
    sink = pa.BufferOutputStream()
    with pa.RecordBatchStreamWriter(sink, table.schema) as writer:
        writer.write_table(table)
    
    arrow_bytes = sink.getvalue().to_pybytes()
    
    end = time.time()
    print(f"Time taken (Strings): {end - start:.4f} seconds")
    print(f"Bytes received (Strings): {len(arrow_bytes)}")
    return end - start

def benchmark_metadata():
    """
    Benchmarks list_variables_rich performance.
    """
    print("\nBenchmarking Metadata (list_variables_rich)...")
    from mcp_stata.stata_client import StataClient
    from sfi import Data

    client = StataClient()
    
    # Ensure variables exist (using existing session or creating new)
    # The previous tests might have left state.
    # Let's ensure we have 3000 vars.
    try:
        client.run_command_structured("clear")
        client.run_command_structured("set obs 1") 
        # Create 3000 vars efficiently?
        # A loop is fine for setup.
        # client.run_command_structured("forvalues i=1/3000 { \n generate v`i' = 1 \n label variable v`i' \"Label `i'\" \n }")
        # Generating 3000 vars in loop takes time, but we only measure the FETCHING.
        print("Generating 3000 variables for metadata test...")
        client.run_command_structured("set obs 1")
        client.run_command_structured("forvalues i=1/3000 { \n generate v`i' = 1 \n label variable v`i' \"Label `i'\" \n }")
    except Exception as e:
         print(f"Metadata setup failed: {e}")
         return None

    print("Fetching metadata for 3000 variables...")
    start = time.time()
    
    # Logic copied from StataClient.list_variables_rich
    vars_info = []
    n_vars = Data.getVarCount()
    for i in range(n_vars):
        name = str(Data.getVarName(i))
        label = None
        fmt = None
        vtype = None
        value_label = None
        # In actual code there are 3 Try-Except blocks!
        try:
            label = Data.getVarLabel(i)
        except Exception:
            label = None
        try:
            fmt = Data.getVarFormat(i)
        except Exception:
            fmt = None
        try:
            vtype = Data.getVarType(i)
        except Exception:
            vtype = None
            
        vars_info.append({
            "name": name,
            "type": vtype,
            "label": label,
            "format": fmt
        })
        
    end = time.time()
    print(f"Time taken (Metadata 3000): {end - start:.4f} seconds")
    return end - start


if __name__ == "__main__":
    t_polars_loop = benchmark_polars_stream()
    
    try:
        t_pandas = benchmark_pandas_stream()
    except Exception as e:
        print(f"Pandas fail: {e}")
        t_pandas = None
        
    try:
        t_sfi = benchmark_sfi_bulk_stream()
    except Exception as e:
         print(f"SFI Bulk fail: {e}")
         t_sfi = None
         
    try:
        t_numpy = benchmark_numpy_polars_stream()
    except Exception as e:
        print(f"Numpy fail: {e}")
        t_numpy = None
        
    try:
        t_csv = benchmark_csv_strategy()
    except Exception as e:
        print(f"CSV fail: {e}")
        t_csv = None

    t_strings = benchmark_strings_stream()

    print("\n=== Summary ===")
    if t_polars_loop: print(f"Polars (Loop SFI): {t_polars_loop:.4f}s")
    if t_pandas: print(f"Pandas (Native):   {t_pandas:.4f}s")
    if t_sfi:    print(f"Polars (Bulk SFI): {t_sfi:.4f}s")
    if t_numpy:  print(f"Polars (Numpy):    {t_numpy:.4f}s")
    if t_csv:    print(f"Polars (CSV):      {t_csv:.4f}s")
    if t_strings:print(f"Polars (Strings, 1000 vars): {t_strings:.4f}s")
    
    t_meta = benchmark_metadata()
    if t_meta: print(f"Metadata (3000 vars):  {t_meta:.4f}s")
