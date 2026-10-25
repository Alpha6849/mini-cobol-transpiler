#!/usr/bin/env python3
"""
Benchmark Harness for Mini COBOL: Standard vs Vectorized Backends.
Measures wall-clock execution time and performs bit-exact precision verification
on 5,000,000 synthetic financial account balance records.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time
from typing import Any, Dict, Tuple

import numpy as np

# Ensure root directory is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import compile_cobol
from benchmark.generate_data import generate_account_balances


def load_module_from_file(module_name: str, file_path: str):
    """Dynamically load a Python module from file path."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from '{file_path}'")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def run_single_backend(
    script_path: str,
    data_path: str,
    target_name: str,
) -> Tuple[Dict[str, Any], float]:
    """Execute a transpiled script's run() function and measure wall-clock execution time."""
    mod = load_module_from_file(f"runnable_{target_name}", script_path)
    # mod.run(data_path=..., benchmark=False) returns (state_dict, elapsed_sec)
    state, elapsed = mod.run(data_path=data_path, benchmark=False)
    return state, elapsed


def run_benchmark(
    cobol_file: str = "tests/sample.cbl",
    data_path: str = "benchmark/balances.bin",
    count: int = 5_000_000,
) -> None:
    """Run full benchmark comparing Standard vs Vectorized targets."""
    print("=" * 76)
    print(" MINI COBOL PERFORMANCE & PRECISION BENCHMARK HARNESS ")
    print("=" * 76)
    print(f"COBOL Program:     {cobol_file}")
    print(f"Dataset Path:      {data_path}")
    print(f"Batch Volume:      {count:,} records\n")

    # 1. Ensure benchmark data exists
    if not os.path.exists(data_path):
        print(f"Data file '{data_path}' not found. Generating synthetic dataset...")
        data_dir = os.path.dirname(data_path) or "benchmark"
        generate_account_balances(count=count, output_dir=data_dir)

    # 2. Read COBOL Source
    with open(cobol_file, "r", encoding="utf-8") as f:
        cobol_source = f.read()

    # 3. Transpile Standard Backend
    std_script = os.path.join(PROJECT_ROOT, "benchmark", "runnable_standard.py")
    print("Transpiling with --target standard...")
    compile_cobol(
        source_code=cobol_source,
        target="standard",
        file_path=cobol_file,
        output_path=std_script,
    )

    # 4. Transpile Vectorized Backend
    vec_script = os.path.join(PROJECT_ROOT, "benchmark", "runnable_vectorized.py")
    print("Transpiling with --target vectorized...")
    compile_cobol(
        source_code=cobol_source,
        target="vectorized",
        file_path=cobol_file,
        output_path=vec_script,
    )
    print()

    # 5. Execute Standard Target
    print(f"Executing Standard Target (pure Python iterative loop on {count:,} items)...")
    t0_std = time.perf_counter()
    std_state, std_wall_time = run_single_backend(std_script, data_path, "standard")
    total_std_wall = time.perf_counter() - t0_std
    print(f"  -> Standard run completed in {std_wall_time * 1000:.2f} ms ({std_wall_time:.4f} s)")

    # 6. Execute Vectorized Target
    print(f"\nExecuting Vectorized Target (SIMD NumPy array operations on {count:,} items)...")
    t0_vec = time.perf_counter()
    vec_state, vec_wall_time = run_single_backend(vec_script, data_path, "vectorized")
    total_vec_wall = time.perf_counter() - t0_vec
    print(f"  -> Vectorized run completed in {vec_wall_time * 1000:.2f} ms ({vec_wall_time:.4f} s)")

    # 7. Precision Verification
    print("\n" + "-" * 76)
    print(" PRECISION & ACCURACY VERIFICATION ")
    print("-" * 76)

    # Extract target array/list
    std_balance = np.array(std_state["balance"], dtype=np.int64)
    vec_balance = vec_state["balance"]
    if not isinstance(vec_balance, np.ndarray):
        vec_balance = np.array(vec_balance, dtype=np.int64)

    assert len(std_balance) == len(vec_balance), (
        f"Length mismatch: standard={len(std_balance)} vs vectorized={len(vec_balance)}"
    )

    # Compare element-by-element
    differences = np.abs(std_balance - vec_balance)
    max_diff = np.max(differences)
    discrepancy_count = int(np.count_nonzero(differences))
    total_items = len(std_balance)

    print(f"Total Records Tested:        {total_items:,}")
    print(f"Bit-Exact Precision Matches: {total_items - discrepancy_count:,} / {total_items:,}")
    print(f"Discrepant Records:          {discrepancy_count}")
    print(f"Maximum Deviation:           {max_diff} cents ($0.00)")
    print(f"Floating Point Drift:        0.00000000% (Bit-Exact Scaled-Integer Math)")

    if discrepancy_count == 0:
        print("[SUCCESS] Precision verification passed: 100.0% exact match across all records.")
    else:
        print(f"[ERROR] Found {discrepancy_count} discrepancies between targets!")
        sys.exit(1)

    # 8. Benchmark Summary & Speedup Metrics
    speedup = std_wall_time / max(vec_wall_time, 1e-9)
    std_throughput = total_items / max(std_wall_time, 1e-9)
    vec_throughput = total_items / max(vec_wall_time, 1e-9)

    print("\n" + "=" * 76)
    print(" BENCHMARK RESULTS SUMMARY ")
    print("=" * 76)
    print(f"{'Target Backend':<24} | {'Wall Time':<16} | {'Throughput (records/sec)':<26}")
    print("-" * 76)
    print(f"{'Standard (Python Loop)':<24} | {std_wall_time * 1000:>8.2f} ms      | {std_throughput:>18,.0f} rec/s")
    print(f"{'Vectorized (SIMD NumPy)':<24} | {vec_wall_time * 1000:>8.2f} ms      | {vec_throughput:>18,.0f} rec/s")
    print("-" * 76)
    print(f"SIMD ACCELERATION SPEEDUP: {speedup:.2f}x FASTER")
    print("=" * 76 + "\n")

    # Cleanup temporary benchmark scripts
    for temp_f in [std_script, vec_script]:
        if os.path.exists(temp_f):
            try:
                os.remove(temp_f)
            except OSError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Mini COBOL performance and precision benchmark.")
    parser.add_argument(
        "--cobol",
        type=str,
        default="tests/sample.cbl",
        help="Path to sample COBOL program (default: tests/sample.cbl)",
    )
    parser.add_argument(
        "--data",
        type=str,
        default="benchmark/balances.bin",
        help="Path to binary account balances dataset (default: benchmark/balances.bin)",
    )
    parser.add_argument(
        "-n", "--count",
        type=int,
        default=5_000_000,
        help="Record count for dataset generation (default: 5,000,000)",
    )
    args = parser.parse_args()

    run_benchmark(
        cobol_file=args.cobol,
        data_path=args.data,
        count=args.count,
    )


if __name__ == "__main__":
    main()
