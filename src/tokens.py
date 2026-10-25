"""Token definitions and Rust-style error reporting for the Mini COBOL transpiler."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Optional


class TokenType(Enum):
    """Enumeration of Mini COBOL token types."""

    # Keywords - Declarations & Structure
    LEVEL_01 = auto()
    PIC = auto()
    PIC_SPEC = auto()
    IDENTIFICATION = auto()
    DIVISION = auto()
    PROGRAM_ID = auto()
    DATA = auto()
    WORKING_STORAGE = auto()
    SECTION = auto()
    PROCEDURE = auto()
    STOP = auto()
    RUN = auto()

    # Keywords - Statements
    MOVE = auto()
    TO = auto()
    ADD = auto()
    GIVING = auto()
    DISPLAY = auto()
    PERFORM = auto()
    TIMES = auto()
    IN = auto()
    PARALLEL = auto()
    END_PERFORM = auto()

    # Literals & Identifiers
    IDENTIFIER = auto()
    NUMBER_LITERAL = auto()
    STRING_LITERAL = auto()

    # Punctuation & Delimiters
    PERIOD = auto()
    LPAREN = auto()
    RPAREN = auto()

    # Stream Termination
    EOF = auto()


@dataclass(frozen=True)
class Token:
    """Represents a lexical token preserving line and column coordinates."""

    type: TokenType
    value: Any
    line: int
    column: int
    length: int = 1

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r}, L{self.line}:C{self.column})"


class CompilerError(Exception):
    """Base exception for compiler errors with Rust-style formatted diagnostics."""

    def __init__(
        self,
        message: str,
        line: int,
        column: int,
        length: int = 1,
        source_code: str = "",
        file_path: str = "<input>",
        hint: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column
        self.length = max(1, length)
        self.source_code = source_code
        self.file_path = file_path
        self.hint = hint
        self.error_code = error_code

    def format_diagnostic(self) -> str:
        """Render a Rust-style diagnostic error with line, column, and caret pointer."""
        code_prefix = f"[{self.error_code}]" if self.error_code else ""
        header = f"error{code_prefix}: {self.message}"
        location = f"  --> {self.file_path}:{self.line}:{self.column}"

        lines = self.source_code.splitlines() if self.source_code else []
        line_idx = self.line - 1

        if 0 <= line_idx < len(lines):
            src_line = lines[line_idx]
        else:
            src_line = ""

        # Gutter width based on line number
        gutter_width = max(len(str(self.line)), 2)
        pipe_margin = " " * gutter_width + " |"

        # Compute caret underline
        col_offset = max(0, self.column - 1)
        # Pad up to col_offset
        prefix_spaces = " " * col_offset
        # Caret pointer
        caret_span = "^" * self.length
        hint_text = f" {self.hint}" if self.hint else ""
        pointer_line = f"{pipe_margin} {prefix_spaces}{caret_span}{hint_text}"

        line_str = str(self.line).rjust(gutter_width)
        source_display = f"{line_str} | {src_line}"

        diagnostic_blocks = [
            header,
            location,
            pipe_margin,
            source_display,
            pointer_line,
            pipe_margin,
        ]
        return "\n".join(diagnostic_blocks)

    def __str__(self) -> str:
        if self.source_code:
            return self.format_diagnostic()
        return f"Error at {self.file_path}:{self.line}:{self.column}: {self.message}"


class LexerError(CompilerError):
    """Raised when the lexer encounters an illegal character or malformed literal."""


class ParserError(CompilerError):
    """Raised when the parser encounters a syntax violation."""


class SemanticError(CompilerError):
    """Raised when static analysis or symbol resolution fails."""
