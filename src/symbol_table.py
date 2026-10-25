"""Symbol table implementation for Mini COBOL tracking variable attributes and scaling."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from src.tokens import SemanticError


@dataclass
class Symbol:
    """Represents a declared variable in the symbol table."""

    name: str
    pic_spec: str
    digits: int
    decimals: int
    scale_factor: int
    line: int
    column: int

    @property
    def total_digits(self) -> int:
        return self.digits + self.decimals

    @property
    def max_scaled_value(self) -> int:
        """Maximum integer value this picture clause can hold without overflow."""
        return (10**self.total_digits) - 1

    def format_scaled_value(self, scaled_val: int) -> str:
        """Format an internal integer scaled value into standard human-readable decimal representation."""
        if self.decimals == 0:
            return str(scaled_val)
        sign = "-" if scaled_val < 0 else ""
        abs_val = abs(scaled_val)
        int_part = abs_val // self.scale_factor
        frac_part = abs_val % self.scale_factor
        return f"{sign}{int_part}.{frac_part:0{self.decimals}d}"


def parse_pic_clause(
    pic_str: str,
    line: int,
    col: int,
    source_code: str = "",
    file_path: str = "<input>",
) -> tuple[int, int, int]:
    """
    Parse a COBOL PIC clause and return (integer_digits, decimal_digits, scale_factor).
    Supports:
      - 9(digits)V9(decimals)  e.g., 9(7)V9(2)
      - 9(digits)              e.g., 9(5)
      - Repeated 9s            e.g., 99999, 999V99
    """
    clean = pic_str.strip().upper()

    # Case 1: 9(digits)V9(decimals)
    m1 = re.fullmatch(r"9\s*\(\s*(\d+)\s*\)\s*V\s*9\s*\(\s*(\d+)\s*\)", clean)
    if m1:
        digits = int(m1.group(1))
        decimals = int(m1.group(2))
        return digits, decimals, 10**decimals

    # Case 2: 9(digits)V99...
    m2 = re.fullmatch(r"9\s*\(\s*(\d+)\s*\)\s*V\s*(9+)", clean)
    if m2:
        digits = int(m2.group(1))
        decimals = len(m2.group(2))
        return digits, decimals, 10**decimals

    # Case 3: 9(digits) (no decimals)
    m3 = re.fullmatch(r"9\s*\(\s*(\d+)\s*\)", clean)
    if m3:
        digits = int(m3.group(1))
        return digits, 0, 1

    # Case 4: Repeated 9s: 999V99 or 999
    m4 = re.fullmatch(r"(9+)(?:V(9+))?", clean)
    if m4:
        digits = len(m4.group(1))
        decimals = len(m4.group(2)) if m4.group(2) else 0
        return digits, decimals, 10**decimals

    raise SemanticError(
        message=f"unsupported or malformed PIC clause '{pic_str}'",
        line=line,
        column=col,
        length=len(pic_str),
        source_code=source_code,
        file_path=file_path,
        hint="use format 9(digits) or 9(digits)V9(decimals)",
        error_code="E0005",
    )


class SymbolTable:
    """Dictionary-based symbol tracker handling PIC sizes, types, and fixed-point scale factors."""

    def __init__(self) -> None:
        self._symbols: Dict[str, Symbol] = {}

    def define(
        self,
        symbol: Symbol,
        source_code: str = "",
        file_path: str = "<input>",
    ) -> None:
        """Register a new symbol, checking for duplicates."""
        canonical = symbol.name.upper()
        if canonical in self._symbols:
            existing = self._symbols[canonical]
            raise SemanticError(
                message=f"duplicate variable declaration '{symbol.name}' (first declared at line {existing.line})",
                line=symbol.line,
                column=symbol.column,
                length=len(symbol.name),
                source_code=source_code,
                file_path=file_path,
                hint=f"variable '{symbol.name}' is already defined",
                error_code="E0003",
            )
        self._symbols[canonical] = symbol

    def lookup(self, name: str) -> Optional[Symbol]:
        """Look up a symbol by canonical name."""
        return self._symbols.get(name.upper())

    def require(
        self,
        name: str,
        line: int,
        column: int,
        length: int,
        source_code: str = "",
        file_path: str = "<input>",
    ) -> Symbol:
        """Look up a symbol and raise a SemanticError if not declared."""
        sym = self.lookup(name)
        if sym is None:
            raise SemanticError(
                message=f"undeclared variable '{name.upper()}'",
                line=line,
                column=column,
                length=length,
                source_code=source_code,
                file_path=file_path,
                hint=f"declare '01 {name.upper()} PIC ...' before using it",
                error_code="E0004",
            )
        return sym

    def __contains__(self, name: str) -> bool:
        return name.upper() in self._symbols

    def all_symbols(self) -> List[Symbol]:
        """Return list of all registered symbols."""
        return list(self._symbols.values())

    def to_dict(self) -> Dict[str, dict]:
        """Serialize symbol table for inspection or debugging."""
        return {
            name: {
                "pic_spec": s.pic_spec,
                "digits": s.digits,
                "decimals": s.decimals,
                "scale_factor": s.scale_factor,
                "line": s.line,
                "column": s.column,
            }
            for name, s in self._symbols.items()
        }
