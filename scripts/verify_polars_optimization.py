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
        client.run_command_structured("forvalues i=1/1000 { \n generate v`i' = runiform() \n }")
    except Exception as e:
        print(f"Failed to generate data: {e}")
        return

    vars = [f"v{i}" for i in range(1, 1001)]
    
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
    
    vars = [f"v{i}" for i in range(1, 1001)]
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
    
    vars = [f"v{i}" for i in range(1, 1001)]
    obs_list = list(range(1000))
    
    print(f"Fetching {len(vars)} variables and 1000 observations (SFI Bulk)...")
    start = time.time()
    
    # Single call to get list of lists
    raw_data = Data.get(var=vars, obs=obs_list, valuelabel=False)
    
    # Logic: Data.get returns [[row1], [row2], ...]
    # Polars can ingest this
    df = pl.DataFrame(raw_data, schema=vars, orient="row")
    
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
    
    vars = [f"v{i}" for i in range(1, 1001)]
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
    print(f"Time taken (Numpy): {end - start:.4f} seconds")
    print(f"Bytes received (Numpy): {len(arrow_bytes)}")
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

    print("\n=== Summary ===")
    if t_polars_loop: print(f"Polars (Loop SFI): {t_polars_loop:.4f}s")
    if t_pandas: print(f"Pandas (Native):   {t_pandas:.4f}s")
    if t_sfi:    print(f"Polars (Bulk SFI): {t_sfi:.4f}s")
    if t_numpy:  print(f"Polars (Numpy):    {t_numpy:.4f}s")
