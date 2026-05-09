import time
import pandas as pd
import pyarrow as pa
import numpy as np

def benchmark_pandas_to_arrow():
    print("Generating DataFrame (1000 rows, 3000 cols)...")
    # Generate random data
    n = 1011
    k = 2948
    data = np.random.randn(n, k)
    df = pd.DataFrame(data, columns=[f"v{i}" for i in range(k)])
    
    # Add _n column similar to actual code
    df.insert(0, "_n", range(1, n + 1))
    
    print("DataFrame ready. Starting conversion...")
    start = time.time()
    
    # Conversion as in ui_http.py
    table = pa.Table.from_pandas(df, preserve_index=False)
    
    # Serialize
    sink = pa.BufferOutputStream()
    with pa.RecordBatchStreamWriter(sink, table.schema) as writer:
        writer.write_table(table)
    
    arrow_bytes = sink.getvalue().to_pybytes()
    
    end = time.time()
    print(f"Conversion + Serialization took: {end - start:.4f} seconds")
    print(f"Output size: {len(arrow_bytes) / 1024 / 1024:.2f} MB")

if __name__ == "__main__":
    benchmark_pandas_to_arrow()
