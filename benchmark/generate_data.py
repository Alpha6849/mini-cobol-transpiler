#!/usr/bin/env python3
"""
Synthetic Financial Account Data Generator for Mini COBOL Benchmark.
Generates 5,000,000 synthetic account balance rows in binary (int64 scaled cents) and CSV formats.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import numpy as np


def generate_account_balances(
    count: int = 5_000_000,
    output_dir: str = "benchmark",
    generate_csv: bool = True,
    seed: int = 42,
) -> tuple[str, str]:
    """
    Generate synthetic account balances with scaled-integer decimal precision.
    Balance range: $100.00 (10,000 cents) to $500,000.00 (50,000,000 cents).
    """
    os.makedirs(output_dir, exist_ok=True)
    bin_path = os.path.join(output_dir, "balances.bin")
    csv_path = os.path.join(output_dir, "balances.csv")

    print(f"Generating {count:,} synthetic account balance records (Seed={seed})...")
    start_time = time.perf_counter()

    rng = np.random.default_rng(seed)
    # Generate scaled integer cents: between 10,000 ($100.00) and 50,000,000 ($500,000.00)
    # Using int64 to avoid overflow during financial accumulations
    balances_cents = rng.integers(
        low=10_000,
        high=50_000_000,
        size=count,
        dtype=np.int64,
    )

    gen_time = time.perf_counter() - start_time
    print(f"Generated {count:,} records in memory in {gen_time:.3f} s.")

    # 1. Write Binary format (int64 little-endian, 8 bytes per record)
    bin_start = time.perf_counter()
    balances_cents.tofile(bin_path)
    bin_size_mb = os.path.getsize(bin_path) / (1024 * 1024)
    bin_time = time.perf_counter() - bin_start
    print(f"Written binary dataset: '{bin_path}' ({bin_size_mb:.2f} MB) in {bin_time:.3f} s.")

    # 2. Write CSV format (optional or chunked for high speed)
    if generate_csv:
        csv_start = time.perf_counter()
        # To avoid massive memory consumption, write in chunks of 500,000
        chunk_size = 500_000
        with open(csv_path, "w", encoding="utf-8") as f:
            for offset in range(0, count, chunk_size):
                chunk = balances_cents[offset : offset + chunk_size]
                lines = [f"{c}\n" for c in chunk]
                f.writelines(lines)
        csv_size_mb = os.path.getsize(csv_path) / (1024 * 1024)
        csv_time = time.perf_counter() - csv_start
        print(f"Written CSV dataset:    '{csv_path}' ({csv_size_mb:.2f} MB) in {csv_time:.3f} s.")

    total_time = time.perf_counter() - start_time
    print(f"Data generation complete in {total_time:.3f} s.\n")

    return bin_path, csv_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic account balance dataset.")
    parser.add_argument(
        "-n", "--count",
        type=int,
        default=5_000_000,
        help="Number of records to generate (default: 5,000,000)",
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default="benchmark",
        help="Output directory (default: benchmark)",
    )
    parser.add_argument(
        "--no-csv",
        action="store_true",
        help="Skip generating large CSV file (generate only .bin)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible benchmark datasets",
    )
    args = parser.parse_args()

    generate_account_balances(
        count=args.count,
        output_dir=args.output_dir,
        generate_csv=not args.no_csv,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
