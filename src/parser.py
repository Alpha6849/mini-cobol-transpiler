"""Recursive descent parser for Mini COBOL enforcing grammar and symbol constraints."""

from __future__ import annotations

from typing import List, Optional

from src.ast_nodes import (
    AddStmtNode,
    DisplayStmtNode,
    ExprNode,
    IdentifierNode,
    MoveStmtNode,
    NumberLiteralNode,
    ParallelPerformStmtNode,
    ProgramNode,
    StatementNode,
    StringLiteralNode,
    VarDeclNode,
)
from src.symbol_table import Symbol, SymbolTable, parse_pic_clause
from src.tokens import ParserError, SemanticError, Token, TokenType


class Parser:
    """
    Recursive descent parser for Mini COBOL.
    Validates syntax, enforces strict '.' termination, validates symbol declarations,
    and constructs the Abstract Syntax Tree (AST).
    """

    def __init__(
        self,
        tokens: List[Token],
        source: str = "",
        file_path: str = "<input>",
    ) -> None:
        self.tokens = tokens
        self.source = source
        self.file_path = file_path
        self.pos = 0
        self.symbol_table = SymbolTable()

    @property
    def current_token(self) -> Token:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return self.tokens[-1]  # EOF token

    @property
    def previous_token(self) -> Token:
        if self.pos > 0:
            return self.tokens[self.pos - 1]
        return self.tokens[0]

    def is_at_end(self) -> bool:
        return self.current_token.type == TokenType.EOF

    def check(self, token_type: TokenType) -> bool:
        if self.is_at_end():
            return token_type == TokenType.EOF
        return self.current_token.type == token_type

    def advance(self) -> Token:
        tok = self.current_token
        if not self.is_at_end():
            self.pos += 1
        return tok

    def match(self, *token_types: TokenType) -> bool:
        for t in token_types:
            if self.check(t):
                self.advance()
                return True
        return False

    def consume(self, token_type: TokenType, expectation: str) -> Token:
        if self.check(token_type):
            return self.advance()

        curr = self.current_token
        prev = self.previous_token
        raise ParserError(
            message=f"expected {expectation}, found {curr.value!r}",
            line=curr.line,
            column=curr.column,
            length=max(1, curr.length),
            source_code=self.source,
            file_path=self.file_path,
            hint=f"insert {expectation} here",
            error_code="E0007",
        )

    def consume_period(self, after_what: str = "statement") -> None:
        """
        Enforce strict period termination.
        Produces Rust-style diagnostic showing exactly where the period is missing.
        """
        if self.check(TokenType.PERIOD):
            self.advance()
            return

        prev = self.previous_token
        curr = self.current_token

        # If current token is on a new line or at EOF, missing period is at end of previous token
        if curr.type == TokenType.EOF or curr.line > prev.line:
            err_line = prev.line
            err_col = prev.column + prev.length
            raise ParserError(
                message=f"missing terminating '.' after {after_what}",
                line=err_line,
                column=err_col,
                length=1,
                source_code=self.source,
                file_path=self.file_path,
                hint=f"expected '.' here to terminate {after_what}",
                error_code="E0006",
            )
        else:
            raise ParserError(
                message=f"expected '.' after {after_what}, found {curr.value!r}",
                line=curr.line,
                column=curr.column,
                length=max(1, curr.length),
                source_code=self.source,
                file_path=self.file_path,
                hint=f"expected '.' before {curr.value!r}",
                error_code="E0006",
            )

    # --------------------------------------------------------------------------
    # Parsing Entry Point
    # --------------------------------------------------------------------------

    def parse(self) -> tuple[ProgramNode, SymbolTable]:
        """Parse source into AST and populate SymbolTable."""
        declarations: List[VarDeclNode] = []
        statements: List[StatementNode] = []

        # Check for optional COBOL Division headers
        self._skip_identification_division()

        # Handle DATA DIVISION / WORKING-STORAGE SECTION if present
        if self.match(TokenType.DATA):
            self.consume(TokenType.DIVISION, "'DIVISION' after 'DATA'")
            self.consume_period("DATA DIVISION header")
            if self.match(TokenType.WORKING_STORAGE):
                self.consume(TokenType.SECTION, "'SECTION' after 'WORKING-STORAGE'")
                self.consume_period("WORKING-STORAGE SECTION header")

        # Parse variable declarations (01 ...)
        while self.check(TokenType.LEVEL_01):
            decl = self._parse_var_declaration()
            declarations.append(decl)

        # Handle PROCEDURE DIVISION header if present
        if self.match(TokenType.PROCEDURE):
            self.consume(TokenType.DIVISION, "'DIVISION' after 'PROCEDURE'")
            self.consume_period("PROCEDURE DIVISION header")

        # Parse executable statements until EOF or STOP RUN
        while not self.is_at_end():
            if self.match(TokenType.STOP):
                self.consume(TokenType.RUN, "'RUN' after 'STOP'")
                self.consume_period("STOP RUN statement")
                break

            stmt = self._parse_statement()
            if stmt is not None:
                statements.append(stmt)

        return ProgramNode(declarations=declarations, statements=statements), self.symbol_table

    def _skip_identification_division(self) -> None:
        """Skip optional IDENTIFICATION DIVISION and PROGRAM-ID."""
        if self.match(TokenType.IDENTIFICATION):
            self.consume(TokenType.DIVISION, "'DIVISION' after 'IDENTIFICATION'")
            self.consume_period("IDENTIFICATION DIVISION header")

            if self.match(TokenType.PROGRAM_ID):
                # Consume program name
                self.consume(TokenType.IDENTIFIER, "program name identifier")
                self.consume_period("PROGRAM-ID declaration")

    # --------------------------------------------------------------------------
    # Declaration Parsing
    # --------------------------------------------------------------------------

    def _parse_var_declaration(self) -> VarDeclNode:
        """Parse: 01 IDENTIFIER PIC 9(digits)[V9(decimals)]."""
        lvl_tok = self.consume(TokenType.LEVEL_01, "'01'")
        id_tok = self.consume(TokenType.IDENTIFIER, "variable name identifier")
        pic_tok = self.consume(TokenType.PIC, "'PIC' or 'PICTURE'")

        # PIC specification: could be PIC_SPEC or manual tokens
        if self.check(TokenType.PIC_SPEC):
            spec_tok = self.advance()
            pic_str = spec_tok.value
        elif self.check(TokenType.NUMBER_LITERAL) or self.check(TokenType.IDENTIFIER):
            # Fallback if PIC clause wasn't combined by lexer
            spec_tok = self.advance()
            pic_str = spec_tok.value
        else:
            curr = self.current_token
            raise ParserError(
                message=f"expected PIC specification (e.g. 9(7)V9(2)), found {curr.value!r}",
                line=curr.line,
                column=curr.column,
                length=max(1, curr.length),
                source_code=self.source,
                file_path=self.file_path,
                hint="specify picture clause like 9(7)V9(2) or 9(5)",
                error_code="E0008",
            )

        # Enforce period termination for declaration
        self.consume_period("variable declaration")

        # Parse PIC clause details & validate
        digits, decimals, scale_factor = parse_pic_clause(
            pic_str,
            line=spec_tok.line,
            col=spec_tok.column,
            source_code=self.source,
            file_path=self.file_path,
        )

        sym = Symbol(
            name=id_tok.value,
            pic_spec=pic_str,
            digits=digits,
            decimals=decimals,
            scale_factor=scale_factor,
            line=id_tok.line,
            column=id_tok.column,
        )
        self.symbol_table.define(
            sym,
            source_code=self.source,
            file_path=self.file_path,
        )

        return VarDeclNode(
            line=lvl_tok.line,
            col=lvl_tok.column,
            name=id_tok.value,
            pic_spec=pic_str,
            digits=digits,
            decimals=decimals,
            scale_factor=scale_factor,
        )

    # --------------------------------------------------------------------------
    # Statement Parsing
    # --------------------------------------------------------------------------

    def _parse_statement(self) -> StatementNode:
        """Parse any executable Mini COBOL statement."""
        curr = self.current_token

        if curr.type == TokenType.MOVE:
            return self._parse_move_statement()
        elif curr.type == TokenType.ADD:
            return self._parse_add_statement()
        elif curr.type == TokenType.DISPLAY:
            return self._parse_display_statement()
        elif curr.type == TokenType.PERFORM:
            return self._parse_perform_statement()
        else:
            raise ParserError(
                message=f"unexpected token {curr.value!r}, expected COBOL statement (MOVE, ADD, DISPLAY, PERFORM)",
                line=curr.line,
                column=curr.column,
                length=max(1, curr.length),
                source_code=self.source,
                file_path=self.file_path,
                hint="valid statements: MOVE, ADD, DISPLAY, PERFORM",
                error_code="E0009",
            )

    def _parse_move_statement(self) -> MoveStmtNode:
        """Parse: MOVE <literal|id> TO <id>."""
        move_tok = self.advance()  # consume MOVE

        source = self._parse_literal_or_identifier("source value in MOVE")
        to_tok = self.consume(TokenType.TO, "'TO'")
        target_tok = self.consume(TokenType.IDENTIFIER, "target identifier in MOVE")

        # Validate that target variable was declared
        self.symbol_table.require(
            target_tok.value,
            line=target_tok.line,
            column=target_tok.column,
            length=target_tok.length,
            source_code=self.source,
            file_path=self.file_path,
        )

        self.consume_period("MOVE statement")

        return MoveStmtNode(
            line=move_tok.line,
            col=move_tok.column,
            source=source,
            target=IdentifierNode(
                line=target_tok.line,
                col=target_tok.column,
                name=target_tok.value,
            ),
        )

    def _parse_add_statement(self) -> AddStmtNode:
        """
        Parse:
          ADD <literal|id> TO <literal|id> GIVING <id>.
          or
          ADD <literal|id> TO <id>.
        """
        add_tok = self.advance()  # consume ADD

        op1 = self._parse_literal_or_identifier("first operand in ADD")
        self.consume(TokenType.TO, "'TO'")

        # Second item after TO: could be target (if no GIVING) or op2 (if GIVING)
        second_item = self._parse_literal_or_identifier("second operand or target in ADD")

        if self.match(TokenType.GIVING):
            # ADD op1 TO op2 GIVING target.
            target_tok = self.consume(TokenType.IDENTIFIER, "target identifier after GIVING")
            self.symbol_table.require(
                target_tok.value,
                line=target_tok.line,
                column=target_tok.column,
                length=target_tok.length,
                source_code=self.source,
                file_path=self.file_path,
            )
            self.consume_period("ADD statement")
            return AddStmtNode(
                line=add_tok.line,
                col=add_tok.column,
                operand1=op1,
                operand2=second_item,
                target=IdentifierNode(
                    line=target_tok.line,
                    col=target_tok.column,
                    name=target_tok.value,
                ),
            )
        else:
            # ADD op1 TO target.
            if not isinstance(second_item, IdentifierNode):
                raise ParserError(
                    message=f"target of ADD TO must be a variable, found literal '{second_item}'",
                    line=second_item.line,
                    column=second_item.col,
                    length=1,
                    source_code=self.source,
                    file_path=self.file_path,
                    hint="specify a declared variable identifier as the target",
                    error_code="E0010",
                )
            self.consume_period("ADD statement")
            return AddStmtNode(
                line=add_tok.line,
                col=add_tok.column,
                operand1=op1,
                operand2=None,
                target=second_item,
            )

    def _parse_display_statement(self) -> DisplayStmtNode:
        """Parse: DISPLAY <id|string|literal>+."""
        disp_tok = self.advance()  # consume DISPLAY

        items: List[ExprNode] = []
        # Consume at least one item
        first_item = self._parse_display_item("item in DISPLAY")
        items.append(first_item)

        # Allow multiple display items before terminating period
        while not self.check(TokenType.PERIOD) and not self.is_at_end():
            item = self._parse_display_item("item in DISPLAY")
            items.append(item)

        self.consume_period("DISPLAY statement")

        return DisplayStmtNode(
            line=disp_tok.line,
            col=disp_tok.column,
            items=items,
        )

    def _parse_perform_statement(self) -> ParallelPerformStmtNode:
        """
        Parse:
          PERFORM <N> TIMES IN PARALLEL
              <operation>...
          END-PERFORM.
        """
        perf_tok = self.advance()  # consume PERFORM

        count = self._parse_literal_or_identifier("iteration count in PERFORM")
        self.consume(TokenType.TIMES, "'TIMES'")
        self.consume(TokenType.IN, "'IN'")
        self.consume(TokenType.PARALLEL, "'PARALLEL'")

        # Optional period after PERFORM ... IN PARALLEL
        if self.check(TokenType.PERIOD):
            self.advance()

        body: List[StatementNode] = []
        while not self.check(TokenType.END_PERFORM) and not self.is_at_end():
            body_stmt = self._parse_statement()
            if body_stmt is not None:
                body.append(body_stmt)

        end_perf_tok = self.consume(TokenType.END_PERFORM, "'END-PERFORM'")
        self.consume_period("END-PERFORM")

        return ParallelPerformStmtNode(
            line=perf_tok.line,
            col=perf_tok.column,
            count=count,
            body=body,
        )

    # --------------------------------------------------------------------------
    # Helper Expression Parsers
    # --------------------------------------------------------------------------

    def _parse_literal_or_identifier(self, context_desc: str) -> ExprNode:
        """Parse an identifier or numeric literal."""
        curr = self.current_token

        if curr.type == TokenType.NUMBER_LITERAL or curr.type == TokenType.LEVEL_01:
            tok = self.advance()
            val_str = "1" if tok.type == TokenType.LEVEL_01 else tok.value
            return NumberLiteralNode(
                line=tok.line,
                col=tok.column,
                raw=val_str,
            )

        if curr.type == TokenType.STRING_LITERAL:
            tok = self.advance()
            return StringLiteralNode(
                line=tok.line,
                col=tok.column,
                value=tok.value,
            )

        if curr.type == TokenType.IDENTIFIER:
            tok = self.advance()
            # Verify variable is declared
            self.symbol_table.require(
                tok.value,
                line=tok.line,
                column=tok.column,
                length=tok.length,
                source_code=self.source,
                file_path=self.file_path,
            )
            return IdentifierNode(
                line=tok.line,
                col=tok.column,
                name=tok.value,
            )

        raise ParserError(
            message=f"expected {context_desc}, found {curr.value!r}",
            line=curr.line,
            column=curr.column,
            length=max(1, curr.length),
            source_code=self.source,
            file_path=self.file_path,
            hint=f"provide a valid variable or number for {context_desc}",
            error_code="E0011",
        )

    def _parse_display_item(self, context_desc: str) -> ExprNode:
        """Parse an identifier, string literal, or numeric literal for DISPLAY."""
        curr = self.current_token

        if curr.type == TokenType.STRING_LITERAL:
            tok = self.advance()
            return StringLiteralNode(
                line=tok.line,
                col=tok.column,
                value=tok.value,
            )

        if curr.type == TokenType.IDENTIFIER:
            tok = self.advance()
            self.symbol_table.require(
                tok.value,
                line=tok.line,
                column=tok.column,
                length=tok.length,
                source_code=self.source,
                file_path=self.file_path,
            )
            return IdentifierNode(
                line=tok.line,
                col=tok.column,
                name=tok.value,
            )

        if curr.type == TokenType.NUMBER_LITERAL or curr.type == TokenType.LEVEL_01:
            tok = self.advance()
            val_str = "1" if tok.type == TokenType.LEVEL_01 else tok.value
            return NumberLiteralNode(
                line=tok.line,
                col=tok.column,
                raw=val_str,
            )

        raise ParserError(
            message=f"expected {context_desc}, found {curr.value!r}",
            line=curr.line,
            column=curr.column,
            length=max(1, curr.length),
            source_code=self.source,
            file_path=self.file_path,
            hint="provide a string in quotes or a declared variable identifier",
            error_code="E0012",
        )
