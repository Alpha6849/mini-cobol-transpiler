#!/usr/bin/env python3
"""Mini COBOL to Python Transpiler CLI Driver."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from src.codegen import CodeGenerator
from src.lexer import Lexer
from src.parser import Parser
from src.tokens import CompilerError


def compile_cobol(
    source_code: str,
    target: str = "standard",
    file_path: str = "<input>",
    output_path: str = "runnable.py",
) -> None:
    """Compile COBOL source code and write generated Python script to output_path."""
    # 1. Lexical Analysis
    lexer = Lexer(source_code, file_path=file_path)
    tokens = lexer.tokenize()

    # 2. Syntax Analysis & Symbol Table Resolution
    parser = Parser(tokens, source=source_code, file_path=file_path)
    ast, symbol_table = parser.parse()

    # 3. Code Generation
    codegen = CodeGenerator(ast, symbol_table, target=target)
    codegen.emit_to_file(output_path)


def main() -> None:
    """CLI Entry point for Mini COBOL Transpiler."""
    parser = argparse.ArgumentParser(
        prog="mini-cobol",
        description="Production COBOL-to-Python Transpiler (Mini COBOL).",
    )
    parser.add_argument(
        "-i", "--input",
        required=True,
        help="Path to the COBOL source file (.cbl, .cob)",
    )
    parser.add_argument(
        "-t", "--target",
        choices=["standard", "vectorized"],
        default="standard",
        help="Code generation backend: 'standard' (pure Python) or 'vectorized' (SIMD NumPy)",
    )
    parser.add_argument(
        "-o", "--output",
        default="runnable.py",
        help="Path for emitted executable Python script (default: runnable.py)",
    )
    parser.add_argument(
        "-r", "--run",
        action="store_true",
        help="Immediately execute the generated script upon successful transpilation",
    )
    parser.add_argument(
        "--data",
        type=str,
        default=None,
        help="Optional data path passed when --run is invoked",
    )

    args = parser.parse_args()

    # Validate input file existence
    if not os.path.exists(args.input):
        sys.stderr.write(f"error: input file '{args.input}' not found.\n")
        sys.exit(1)

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            source_code = f.read()
    except Exception as e:
        sys.stderr.write(f"error: failed to read file '{args.input}': {e}\n")
        sys.exit(1)

    # Transpilation pipeline
    try:
        compile_cobol(
            source_code=source_code,
            target=args.target,
            file_path=args.input,
            output_path=args.output,
        )
        print(f"Transpilation successful -> '{args.output}' (target: {args.target})", flush=True)
    except CompilerError as err:
        sys.stderr.write(f"\n{err.format_diagnostic()}\n\n")
        sys.exit(1)
    except Exception as err:
        sys.stderr.write(f"internal compiler error: {err}\n")
        sys.exit(2)

    # Run if requested
    if args.run:
        cmd = [sys.executable, args.output]
        if args.data:
            cmd.extend(["--data", args.data])
        res = subprocess.run(cmd)
        sys.exit(res.returncode)


if __name__ == "__main__":
    main()
