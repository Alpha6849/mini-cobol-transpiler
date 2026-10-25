"""Lexer implementation for Mini COBOL."""

from __future__ import annotations

import re
from typing import List, Optional

from src.tokens import CompilerError, LexerError, Token, TokenType

# Keyword map: canonical uppercase name -> TokenType
KEYWORDS = {
    "01": TokenType.LEVEL_01,
    "PIC": TokenType.PIC,
    "PICTURE": TokenType.PIC,
    "MOVE": TokenType.MOVE,
    "TO": TokenType.TO,
    "ADD": TokenType.ADD,
    "GIVING": TokenType.GIVING,
    "DISPLAY": TokenType.DISPLAY,
    "PERFORM": TokenType.PERFORM,
    "TIMES": TokenType.TIMES,
    "IN": TokenType.IN,
    "PARALLEL": TokenType.PARALLEL,
    "END-PERFORM": TokenType.END_PERFORM,
    # Standard COBOL Division / Header Support
    "IDENTIFICATION": TokenType.IDENTIFICATION,
    "DIVISION": TokenType.DIVISION,
    "PROGRAM-ID": TokenType.PROGRAM_ID,
    "DATA": TokenType.DATA,
    "WORKING-STORAGE": TokenType.WORKING_STORAGE,
    "SECTION": TokenType.SECTION,
    "PROCEDURE": TokenType.PROCEDURE,
    "STOP": TokenType.STOP,
    "RUN": TokenType.RUN,
}

# Regex for PIC clause pattern: e.g., 9(7)V9(2), 9(5), 9(7)V99, 999V99
RE_PIC_SPEC = re.compile(
    r"^9(?:\(\s*\d+\s*\)|\d*)(?:[Vv]9(?:\(\s*\d+\s*\)|\d*))?",
    re.IGNORECASE,
)


class Lexer:
    """Regex-based tokenizer for Mini COBOL preserving coordinates and comments."""

    def __init__(self, source: str, file_path: str = "<input>") -> None:
        self.source = source
        self.file_path = file_path
        self.tokens: List[Token] = []
        self.pos = 0
        self.line = 1
        self.col = 1
        self.length = len(source)

    def tokenize(self) -> List[Token]:
        """Tokenize the entire source code into a list of Token objects."""
        self.tokens = []
        self.pos = 0
        self.line = 1
        self.col = 1

        while self.pos < self.length:
            char = self.source[self.pos]

            # 1. Newlines
            if char == "\n":
                self.pos += 1
                self.line += 1
                self.col = 1
                continue
            if char == "\r":
                if self.pos + 1 < self.length and self.source[self.pos + 1] == "\n":
                    self.pos += 2
                else:
                    self.pos += 1
                self.line += 1
                self.col = 1
                continue

            # 2. Whitespace (spaces, tabs)
            if char in " \t":
                self.pos += 1
                self.col += 1
                continue

            # 3. Comments:
            # - Modern inline comment: *> to end-of-line
            # - Traditional column 7 comment (* in col 7) or line starting with *
            if self.source.startswith("*>", self.pos):
                self._skip_line_comment()
                continue

            # If column 1 or first non-whitespace on the line has '*'
            if char == "*" and self._is_line_comment_context():
                self._skip_line_comment()
                continue

            # 4. Period: must be checked carefully.
            # In COBOL, a period '.' can be a statement terminator, or part of a float like 100.50.
            # If the current char is '.', and next char is NOT a digit, it's a PERIOD token.
            if char == ".":
                # Check if it could be a leading decimal like .50
                if self.pos + 1 < self.length and self.source[self.pos + 1].isdigit():
                    self._read_number()
                    continue
                else:
                    self.tokens.append(
                        Token(TokenType.PERIOD, ".", self.line, self.col, 1)
                    )
                    self.pos += 1
                    self.col += 1
                    continue

            # 5. Parentheses
            if char == "(":
                self.tokens.append(
                    Token(TokenType.LPAREN, "(", self.line, self.col, 1)
                )
                self.pos += 1
                self.col += 1
                continue

            if char == ")":
                self.tokens.append(
                    Token(TokenType.RPAREN, ")", self.line, self.col, 1)
                )
                self.pos += 1
                self.col += 1
                continue

            # 6. String Literals ("..." or '...')
            if char in ('"', "'"):
                self._read_string(char)
                continue

            # 7. Level 01 or Numbers or PIC Spec starting with digit
            if char.isdigit():
                # Check if preceding token was PIC or PICTURE; if so, this might be a PIC pattern like 9(7)V9(2)
                last_token = self.tokens[-1] if self.tokens else None
                if last_token and last_token.type == TokenType.PIC:
                    if self._try_read_pic_spec():
                        continue

                # Check specifically for "01" level number
                if self.source.startswith("01", self.pos):
                    # Make sure it's not part of a larger number like 0123 or 01.5
                    end_idx = self.pos + 2
                    is_boundary = True
                    if end_idx < self.length:
                        next_ch = self.source[end_idx]
                        if next_ch.isalnum() or next_ch == ".":
                            is_boundary = False
                    if is_boundary:
                        self.tokens.append(
                            Token(TokenType.LEVEL_01, "01", self.line, self.col, 2)
                        )
                        self.pos += 2
                        self.col += 2
                        continue

                self._read_number()
                continue

            # 8. Identifiers and Keywords
            if char.isalpha() or char == "_":
                self._read_identifier_or_keyword()
                continue

            # 9. Unexpected character
            err = LexerError(
                message=f"unexpected character {char!r}",
                line=self.line,
                column=self.col,
                length=1,
                source_code=self.source,
                file_path=self.file_path,
                hint="remove or replace this invalid character",
                error_code="E0001",
            )
            raise err

        # Emit EOF token
        self.tokens.append(
            Token(TokenType.EOF, "", self.line, self.col, 0)
        )
        return self.tokens

    def _skip_line_comment(self) -> None:
        """Skip all characters until the next newline."""
        while self.pos < self.length and self.source[self.pos] not in ("\r", "\n"):
            self.pos += 1
            self.col += 1

    def _is_line_comment_context(self) -> bool:
        """Check if '*' indicates a comment (e.g. column 1, column 7, or sole line prefix)."""
        if self.col == 1 or self.col == 7:
            return True
        # Check if preceding characters on this line are all whitespace
        line_start = self.pos - (self.col - 1)
        prefix = self.source[line_start : self.pos]
        return prefix.strip() == ""

    def _read_string(self, quote_char: str) -> None:
        """Read a quoted string literal."""
        start_line = self.line
        start_col = self.col
        self.pos += 1  # skip opening quote
        self.col += 1
        chars: List[str] = []

        while self.pos < self.length:
            ch = self.source[self.pos]
            if ch in ("\r", "\n"):
                raise LexerError(
                    message="unterminated string literal before end of line",
                    line=start_line,
                    column=start_col,
                    length=self.col - start_col,
                    source_code=self.source,
                    file_path=self.file_path,
                    hint=f"add a closing {quote_char} to terminate the string",
                    error_code="E0002",
                )
            if ch == quote_char:
                # Check for escaped quote (e.g., "" in COBOL)
                if self.pos + 1 < self.length and self.source[self.pos + 1] == quote_char:
                    chars.append(quote_char)
                    self.pos += 2
                    self.col += 2
                    continue
                else:
                    self.pos += 1
                    self.col += 1
                    string_val = "".join(chars)
                    total_len = (self.col - start_col)
                    self.tokens.append(
                        Token(
                            TokenType.STRING_LITERAL,
                            string_val,
                            start_line,
                            start_col,
                            total_len,
                        )
                    )
                    return
            chars.append(ch)
            self.pos += 1
            self.col += 1

        raise LexerError(
            message="unterminated string literal at end of input",
            line=start_line,
            column=start_col,
            length=max(1, self.col - start_col),
            source_code=self.source,
            file_path=self.file_path,
            hint=f"add a closing {quote_char}",
            error_code="E0002",
        )

    def _read_number(self) -> None:
        """Read an integer or decimal numeric literal."""
        start_line = self.line
        start_col = self.col
        start_pos = self.pos

        # Read digits
        while self.pos < self.length and self.source[self.pos].isdigit():
            self.pos += 1
            self.col += 1

        # Check for fractional part: must be followed by at least one digit
        if (
            self.pos < self.length
            and self.source[self.pos] == "."
            and self.pos + 1 < self.length
            and self.source[self.pos + 1].isdigit()
        ):
            self.pos += 1  # eat dot
            self.col += 1
            while self.pos < self.length and self.source[self.pos].isdigit():
                self.pos += 1
                self.col += 1

        num_str = self.source[start_pos : self.pos]
        length = self.pos - start_pos
        self.tokens.append(
            Token(
                TokenType.NUMBER_LITERAL,
                num_str,
                start_line,
                start_col,
                length,
            )
        )

    def _try_read_pic_spec(self) -> bool:
        """Attempt to match a COBOL picture clause pattern (e.g., 9(7)V9(2))."""
        remainder = self.source[self.pos :]
        match = RE_PIC_SPEC.match(remainder)
        if match:
            spec_str = match.group(0).upper()
            length = len(match.group(0))
            self.tokens.append(
                Token(
                    TokenType.PIC_SPEC,
                    spec_str,
                    self.line,
                    self.col,
                    length,
                )
            )
            self.pos += length
            self.col += length
            return True
        return False

    def _read_identifier_or_keyword(self) -> None:
        """Read an identifier or keyword (including hyphenated COBOL names)."""
        start_line = self.line
        start_col = self.col
        start_pos = self.pos

        # COBOL identifier allows letters, digits, underscores, and hyphens.
        # Hyphen cannot be trailing before a period or space if part of expression,
        # but in COBOL words like END-PERFORM or PROGRAM-ID, hyphens are standard.
        while self.pos < self.length:
            ch = self.source[self.pos]
            if ch.isalnum() or ch == "_" or ch == "-":
                self.pos += 1
                self.col += 1
            else:
                break

        raw_word = self.source[start_pos : self.pos]
        upper_word = raw_word.upper()
        length = self.pos - start_pos

        # Check if keyword
        if upper_word in KEYWORDS:
            token_type = KEYWORDS[upper_word]
            self.tokens.append(
                Token(token_type, upper_word, start_line, start_col, length)
            )
        else:
            # Normalized identifier: canonical uppercase
            self.tokens.append(
                Token(
                    TokenType.IDENTIFIER,
                    upper_word,
                    start_line,
                    start_col,
                    length,
                )
            )
