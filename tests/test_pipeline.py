"""
Comprehensive Test Suite for Mini COBOL Transpiler.
Verifies Lexer tokens, Parser edge cases, Symbol Table scale factors,
Rust-style static diagnostics, and Standard & Vectorized execution correctness.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from src.ast_nodes import (
    AddStmtNode,
    DisplayStmtNode,
    IdentifierNode,
    MoveStmtNode,
    NumberLiteralNode,
    ParallelPerformStmtNode,
    ProgramNode,
    StringLiteralNode,
    VarDeclNode,
)
from src.codegen import CodeGenerator
from src.lexer import Lexer
from src.parser import Parser
from src.symbol_table import SymbolTable, parse_pic_clause
from src.tokens import (
    CompilerError,
    LexerError,
    ParserError,
    SemanticError,
    Token,
    TokenType,
)
from main import compile_cobol


# ==============================================================================
# 1. Lexer Tests
# ==============================================================================

class TestLexer:
    """Tests for lexical analysis, coordinate tracking, and normalization."""

    def test_basic_token_stream(self) -> None:
        source = "01 BALANCE PIC 9(7)V9(2)."
        lexer = Lexer(source)
        tokens = lexer.tokenize()

        expected_types = [
            TokenType.LEVEL_01,
            TokenType.IDENTIFIER,
            TokenType.PIC,
            TokenType.PIC_SPEC,
            TokenType.PERIOD,
            TokenType.EOF,
        ]
        assert [t.type for t in tokens] == expected_types
        assert tokens[0].value == "01"
        assert tokens[1].value == "BALANCE"
        assert tokens[3].value == "9(7)V9(2)"

    def test_line_column_coordinates(self) -> None:
        source = "01 VARA PIC 9(5).\n01 VARB PIC 9(3)."
        lexer = Lexer(source)
        tokens = lexer.tokenize()

        # VARA on Line 1, Col 4
        assert tokens[1].line == 1
        assert tokens[1].column == 4
        assert tokens[1].length == 4

        # Tokens for line 1: 01 (0), VARA (1), PIC (2), 9(5) (3), . (4)
        # Line 2 starts at index 5: 01 (5), VARB (6), PIC (7), 9(3) (8), . (9)
        lvl_line2 = tokens[5]
        assert lvl_line2.type == TokenType.LEVEL_01
        assert lvl_line2.line == 2
        assert lvl_line2.column == 1

        varb_tok = tokens[6]
        assert varb_tok.value == "VARB"
        assert varb_tok.line == 2
        assert varb_tok.column == 4

    def test_case_insensitivity_normalization(self) -> None:
        source = "move 100 to balance."
        tokens = Lexer(source).tokenize()
        assert tokens[0].type == TokenType.MOVE
        assert tokens[1].type == TokenType.NUMBER_LITERAL
        assert tokens[2].type == TokenType.TO
        assert tokens[3].type == TokenType.IDENTIFIER
        assert tokens[3].value == "BALANCE"

    def test_decimal_vs_terminating_period(self) -> None:
        # 100.50 is a decimal literal; followed by '.' as statement period
        source = "MOVE 100.50 TO BALANCE."
        tokens = Lexer(source).tokenize()
        num_tok = tokens[1]
        assert num_tok.type == TokenType.NUMBER_LITERAL
        assert num_tok.value == "100.50"
        period_tok = tokens[4]
        assert period_tok.type == TokenType.PERIOD

    def test_comment_skipping(self) -> None:
        source = """
        * Full line comment
        01 BALANCE PIC 9(5).
        *> Modern inline comment
        MOVE 50 TO BALANCE.
        """
        tokens = Lexer(source).tokenize()
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert types == [
            TokenType.LEVEL_01,
            TokenType.IDENTIFIER,
            TokenType.PIC,
            TokenType.PIC_SPEC,
            TokenType.PERIOD,
            TokenType.MOVE,
            TokenType.NUMBER_LITERAL,
            TokenType.TO,
            TokenType.IDENTIFIER,
            TokenType.PERIOD,
        ]

    def test_unterminated_string_error(self) -> None:
        source = 'DISPLAY "UNCLOSED STRING.'
        with pytest.raises(LexerError) as exc_info:
            Lexer(source).tokenize()
        assert "unterminated string literal" in exc_info.value.message
        assert exc_info.value.line == 1

    def test_unexpected_character_error(self) -> None:
        source = "MOVE 100 @ BALANCE."
        with pytest.raises(LexerError) as exc_info:
            Lexer(source).tokenize()
        assert "unexpected character '@'" in exc_info.value.message


# ==============================================================================
# 2. Symbol Table & PIC Clause Tests
# ==============================================================================

class TestSymbolTable:
    """Tests for PIC specification parsing, scale factor calculation, and symbols."""

    def test_parse_pic_standard_decimal(self) -> None:
        digits, decimals, scale = parse_pic_clause("9(7)V9(2)", line=1, col=1)
        assert digits == 7
        assert decimals == 2
        assert scale == 100

    def test_parse_pic_integer_only(self) -> None:
        digits, decimals, scale = parse_pic_clause("9(5)", line=1, col=1)
        assert digits == 5
        assert decimals == 0
        assert scale == 1

    def test_parse_pic_repeated_nines(self) -> None:
        digits, decimals, scale = parse_pic_clause("999V99", line=1, col=1)
        assert digits == 3
        assert decimals == 2
        assert scale == 100

    def test_symbol_table_duplicate_declaration(self) -> None:
        from src.symbol_table import Symbol
        table = SymbolTable()
        s1 = Symbol("BAL", "9(5)", 5, 0, 1, line=1, column=4)
        table.define(s1)

        s2 = Symbol("BAL", "9(5)", 5, 0, 1, line=2, column=4)
        with pytest.raises(SemanticError) as exc_info:
            table.define(s2)
        assert "duplicate variable declaration 'BAL'" in exc_info.value.message

    def test_symbol_table_undeclared_lookup(self) -> None:
        table = SymbolTable()
        with pytest.raises(SemanticError) as exc_info:
            table.require("UNKNOWN", line=5, column=10, length=7)
        assert "undeclared variable 'UNKNOWN'" in exc_info.value.message


# ==============================================================================
# 3. Parser & AST Tests
# ==============================================================================

class TestParser:
    """Tests for grammar parsing and AST construction."""

    def test_variable_declaration_ast(self) -> None:
        source = "01 BALANCE PIC 9(7)V9(2)."
        tokens = Lexer(source).tokenize()
        ast, sym = Parser(tokens, source).parse()

        assert len(ast.declarations) == 1
        decl = ast.declarations[0]
        assert decl.name == "BALANCE"
        assert decl.digits == 7
        assert decl.decimals == 2
        assert decl.scale_factor == 100

    def test_move_statement_ast(self) -> None:
        source = "01 BAL PIC 9(5).\nMOVE 250 TO BAL."
        tokens = Lexer(source).tokenize()
        ast, sym = Parser(tokens, source).parse()

        assert len(ast.statements) == 1
        stmt = ast.statements[0]
        assert isinstance(stmt, MoveStmtNode)
        assert isinstance(stmt.source, NumberLiteralNode)
        assert stmt.source.raw == "250"
        assert stmt.target.name == "BAL"

    def test_add_statement_two_operand(self) -> None:
        source = "01 BAL PIC 9(5).\nADD 50 TO BAL."
        tokens = Lexer(source).tokenize()
        ast, sym = Parser(tokens, source).parse()

        assert len(ast.statements) == 1
        stmt = ast.statements[0]
        assert isinstance(stmt, AddStmtNode)
        assert stmt.has_giving is False
        assert stmt.target.name == "BAL"

    def test_add_statement_with_giving(self) -> None:
        source = """
        01 A PIC 9(5).
        01 B PIC 9(5).
        01 C PIC 9(5).
        ADD A TO B GIVING C.
        """
        tokens = Lexer(source).tokenize()
        ast, sym = Parser(tokens, source).parse()

        assert len(ast.statements) == 1
        stmt = ast.statements[0]
        assert isinstance(stmt, AddStmtNode)
        assert stmt.has_giving is True
        assert isinstance(stmt.operand1, IdentifierNode)
        assert stmt.operand1.name == "A"
        assert isinstance(stmt.operand2, IdentifierNode)
        assert stmt.operand2.name == "B"
        assert stmt.target.name == "C"

    def test_display_statement_multiple_items(self) -> None:
        source = '01 TOTAL PIC 9(5).\nDISPLAY "SUM: " TOTAL.'
        tokens = Lexer(source).tokenize()
        ast, sym = Parser(tokens, source).parse()

        assert len(ast.statements) == 1
        stmt = ast.statements[0]
        assert isinstance(stmt, DisplayStmtNode)
        assert len(stmt.items) == 2
        assert isinstance(stmt.items[0], StringLiteralNode)
        assert stmt.items[0].value == "SUM: "
        assert isinstance(stmt.items[1], IdentifierNode)
        assert stmt.items[1].name == "TOTAL"

    def test_parallel_perform_ast(self) -> None:
        source = """
        01 BAL PIC 9(5).
        01 INC PIC 9(3).
        PERFORM 1000 TIMES IN PARALLEL
            ADD INC TO BAL.
        END-PERFORM.
        """
        tokens = Lexer(source).tokenize()
        ast, sym = Parser(tokens, source).parse()

        assert len(ast.statements) == 1
        stmt = ast.statements[0]
        assert isinstance(stmt, ParallelPerformStmtNode)
        assert isinstance(stmt.count, NumberLiteralNode)
        assert stmt.count.raw == "1000"
        assert len(stmt.body) == 1
        assert isinstance(stmt.body[0], AddStmtNode)


# ==============================================================================
# 4. Rust-Style Error Reporting Tests
# ==============================================================================

class TestRustStyleDiagnostics:
    """Verifies that missing periods and static errors render exact Rust-style carets."""

    def test_missing_period_on_declaration(self) -> None:
        source = "01 BALANCE PIC 9(7)V9(2)\n01 TOTAL PIC 9(9)."
        tokens = Lexer(source, "test.cbl").tokenize()
        with pytest.raises(ParserError) as exc_info:
            Parser(tokens, source, "test.cbl").parse()

        diag = exc_info.value.format_diagnostic()
        assert "error[E0006]: missing terminating '.' after variable declaration" in diag
        assert "--> test.cbl:1:" in diag
        assert "^ expected '.' here" in diag

    def test_missing_period_on_move(self) -> None:
        source = "01 BALANCE PIC 9(7).\nMOVE 100 TO BALANCE\nDISPLAY BALANCE."
        tokens = Lexer(source, "test.cbl").tokenize()
        with pytest.raises(ParserError) as exc_info:
            Parser(tokens, source, "test.cbl").parse()

        diag = exc_info.value.format_diagnostic()
        assert "error[E0006]: missing terminating '.' after MOVE statement" in diag
        assert "--> test.cbl:2:" in diag
        assert "^ expected '.' here to terminate MOVE statement" in diag

    def test_missing_period_on_add(self) -> None:
        source = "01 BAL PIC 9(5).\nADD 50 TO BAL\nDISPLAY BAL."
        tokens = Lexer(source, "test.cbl").tokenize()
        with pytest.raises(ParserError) as exc_info:
            Parser(tokens, source, "test.cbl").parse()

        diag = exc_info.value.format_diagnostic()
        assert "missing terminating '.' after ADD statement" in diag

    def test_missing_period_on_end_perform(self) -> None:
        source = """
        01 BAL PIC 9(5).
        PERFORM 10 TIMES IN PARALLEL
            ADD 1 TO BAL.
        END-PERFORM
        """
        tokens = Lexer(source, "test.cbl").tokenize()
        with pytest.raises(ParserError) as exc_info:
            Parser(tokens, source, "test.cbl").parse()

        diag = exc_info.value.format_diagnostic()
        assert "missing terminating '.' after END-PERFORM" in diag

    def test_undeclared_variable_diagnostic(self) -> None:
        source = "01 BAL PIC 9(5).\nMOVE 100 TO NONEXISTENT."
        tokens = Lexer(source, "test.cbl").tokenize()
        with pytest.raises(SemanticError) as exc_info:
            Parser(tokens, source, "test.cbl").parse()

        diag = exc_info.value.format_diagnostic()
        assert "error[E0004]: undeclared variable 'NONEXISTENT'" in diag
        assert "^^^^^^^^^^^ declare '01 NONEXISTENT PIC ...' before using it" in diag


# ==============================================================================
# 5. Code Generation & Execution Correctness Tests
# ==============================================================================

class TestExecutionCorrectness:
    """Verifies that transpiled code executes correctly and matches mathematical results."""

    def test_standard_backend_execution(self, tmp_path) -> None:
        cbl_code = """
        01 BALANCE PIC 9(7)V9(2).
        01 DEPOSIT PIC 9(5)V9(2).
        01 TOTAL PIC 9(9)V9(2).

        MOVE 1250.75 TO BALANCE.
        MOVE 45.25 TO DEPOSIT.
        ADD BALANCE TO DEPOSIT GIVING TOTAL.
        DISPLAY TOTAL.
        """
        out_script = str(tmp_path / "runnable_std.py")
        compile_cobol(cbl_code, target="standard", output_path=out_script)

        # Run script
        proc = subprocess.run(
            [sys.executable, out_script],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "1296.00" in proc.stdout

    def test_vectorized_backend_execution(self, tmp_path) -> None:
        cbl_code = """
        01 BALANCE PIC 9(7)V9(2).
        01 DEPOSIT PIC 9(5)V9(2).
        01 TOTAL PIC 9(9)V9(2).

        MOVE 1250.75 TO BALANCE.
        MOVE 45.25 TO DEPOSIT.
        ADD BALANCE TO DEPOSIT GIVING TOTAL.
        DISPLAY TOTAL.
        """
        out_script = str(tmp_path / "runnable_vec.py")
        compile_cobol(cbl_code, target="vectorized", output_path=out_script)

        proc = subprocess.run(
            [sys.executable, out_script],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "1296.00" in proc.stdout

    def test_parallel_batch_interest_parity(self, tmp_path) -> None:
        cbl_code = """
        01 BALANCE PIC 9(7)V9(2).
        01 INTEREST PIC 9(3)V9(2).

        MOVE 100.00 TO BALANCE.
        MOVE 5.50 TO INTEREST.
        PERFORM 1000 TIMES IN PARALLEL
            ADD INTEREST TO BALANCE.
        END-PERFORM.
        DISPLAY BALANCE.
        """
        script_std = str(tmp_path / "batch_std.py")
        script_vec = str(tmp_path / "batch_vec.py")

        compile_cobol(cbl_code, target="standard", output_path=script_std)
        compile_cobol(cbl_code, target="vectorized", output_path=script_vec)

        res_std = subprocess.run([sys.executable, script_std], capture_output=True, text=True, check=True)
        res_vec = subprocess.run([sys.executable, script_vec], capture_output=True, text=True, check=True)

        # Both should report 1,000 items and First 5 values equal to 105.50
        assert "105.50" in res_std.stdout
        assert "105.50" in res_vec.stdout
        assert "1,000 items" in res_std.stdout
        assert "1,000 items" in res_vec.stdout

    def test_main_cli_execution(self, tmp_path) -> None:
        cbl_file = str(tmp_path / "test.cbl")
        with open(cbl_file, "w", encoding="utf-8") as f:
            f.write("01 BAL PIC 9(5).\nMOVE 500 TO BAL.\nDISPLAY BAL.\n")

        # Run main.py with --run
        res = subprocess.run(
            [sys.executable, "main.py", "--input", cbl_file, "--target", "standard", "--run"],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert "Transpilation successful" in res.stdout
        assert "500" in res.stdout
