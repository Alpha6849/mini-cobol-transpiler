"""Abstract Syntax Tree (AST) node definitions for Mini COBOL."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Union


@dataclass
class ASTNode:
    """Base class for all AST nodes with source coordinates."""

    line: int = 1
    col: int = 1


@dataclass
class NumberLiteralNode(ASTNode):
    """Numeric literal (integer or fixed-point decimal)."""

    raw: str = "0"
    is_decimal: bool = False
    scale_factor: int = 1
    scaled_value: int = 0  # Fixed-point integer representation (e.g. cents)

    def __post_init__(self) -> None:
        if "." in self.raw:
            self.is_decimal = True
            parts = self.raw.split(".")
            decimals_count = len(parts[1])
            self.scale_factor = 10**decimals_count
            # Compute exact scaled integer representation
            sign = -1 if self.raw.startswith("-") else 1
            clean_str = self.raw.lstrip("-")
            int_part, frac_part = clean_str.split(".")
            self.scaled_value = sign * (int(int_part) * self.scale_factor + int(frac_part))
        else:
            self.is_decimal = False
            self.scale_factor = 1
            self.scaled_value = int(self.raw)


@dataclass
class StringLiteralNode(ASTNode):
    """String literal (e.g. 'TOTAL: ')."""

    value: str = ""


@dataclass
class IdentifierNode(ASTNode):
    """Identifier reference (e.g. BALANCE)."""

    name: str = ""


# Expression types
ExprNode = Union[NumberLiteralNode, StringLiteralNode, IdentifierNode]


@dataclass
class VarDeclNode(ASTNode):
    """Variable declaration node (01 IDENTIFIER PIC 9(d)[V9(d)].)."""

    name: str = ""
    pic_spec: str = ""
    digits: int = 0
    decimals: int = 0
    scale_factor: int = 1


@dataclass
class StatementNode(ASTNode):
    """Base class for statement nodes."""


@dataclass
class MoveStmtNode(StatementNode):
    """MOVE <literal|id> TO <id>."""

    source: ExprNode = field(default_factory=lambda: IdentifierNode())
    target: IdentifierNode = field(default_factory=lambda: IdentifierNode())


@dataclass
class AddStmtNode(StatementNode):
    """
    ADD <literal|id> TO <literal|id> GIVING <id>.
    or
    ADD <literal|id> TO <id>.
    """

    operand1: ExprNode = field(default_factory=lambda: IdentifierNode())
    operand2: Optional[ExprNode] = None
    target: IdentifierNode = field(default_factory=lambda: IdentifierNode())

    @property
    def has_giving(self) -> bool:
        return self.operand2 is not None


@dataclass
class DisplayStmtNode(StatementNode):
    """DISPLAY <id|string|literal>+."""

    items: List[ExprNode] = field(default_factory=list)


@dataclass
class ParallelPerformStmtNode(StatementNode):
    """
    PERFORM <N> TIMES IN PARALLEL
        <operations...>
    END-PERFORM.
    """

    count: ExprNode = field(default_factory=lambda: NumberLiteralNode())
    body: List[StatementNode] = field(default_factory=list)


@dataclass
class ProgramNode(ASTNode):
    """Root program node containing declarations and executable statements."""

    declarations: List[VarDeclNode] = field(default_factory=list)
    statements: List[StatementNode] = field(default_factory=list)
