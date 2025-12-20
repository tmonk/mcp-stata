import stata_setup
stata_setup.config("/Applications/StataNow/", "mp")
from pystata import stata
import time, statistics as stats

def bench(cmd='quietly di ""', n=300):    # warm-up
    stata.run(cmd)

    # create the full set of n in a single run first
    cmd_full = "\n".join([cmd]*n)
    t0 = time.perf_counter()
    stata.run(cmd_full)
    full_time = time.perf_counter() - t0
    print(f"Full run time for {n} commands: {full_time:.3f} s ({1000*full_time/n:.3f} ms per command)")
    # now time each individually
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        stata.run(cmd)
        times.append(time.perf_counter() - t0)
    return {
        'full_ms': 1000 * full_time / n,
        "mean_ms": 1000 * stats.mean(times),
        "median_ms": 1000 * stats.median(times),
        "p95_ms": 1000 * sorted(times)[int(0.95*len(times))-1],
    }

if __name__ == "__main__":
    import json
    results = bench()
    print(json.dumps(results, indent=2))
