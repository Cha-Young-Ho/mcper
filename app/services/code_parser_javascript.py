"""JavaScript/TypeScript code parser using regex-based extraction."""

from __future__ import annotations

import logging
import re

from app.services.code_parser import CodeParserBase, CodeSymbol

logger = logging.getLogger(__name__)


def _find_function_end(content: str, start_pos: int) -> int:
    """Find the end of a function body by counting braces."""
    brace_count = 0
    found_start = False

    for i, char in enumerate(content[start_pos:], start=start_pos):
        if char == "{":
            brace_count += 1
            found_start = True
        elif char == "}":
            brace_count -= 1
            if found_start and brace_count == 0:
                return i + 1

    return len(content)


def _extract_function_body(content: str, match_obj: re.Match) -> str:
    """Extract complete function body from match position."""
    start = match_obj.start()
    # Find opening brace
    brace_pos = content.find("{", match_obj.end())
    if brace_pos == -1:
        return content[start : match_obj.end() + 50]

    end = _find_function_end(content, brace_pos)
    return content[start:end].rstrip()


def _extract_class_body(content: str, match_obj: re.Match) -> str:
    """Extract complete class body from match position."""
    start = match_obj.start()
    # Find opening brace
    brace_pos = content.find("{", match_obj.end())
    if brace_pos == -1:
        return content[start : match_obj.end() + 100]

    end = _find_function_end(content, brace_pos)
    return content[start:end].rstrip()


def _get_line_number(content: str, pos: int) -> int:
    """Get line number at a specific position in content."""
    return content[:pos].count("\n") + 1


class JavaScriptCodeParser(CodeParserBase):
    """Parser for JavaScript/TypeScript source code using regex."""

    def parse(self, file_path: str, content: str) -> list[CodeSymbol]:
        """
        Parse JavaScript/TypeScript source code and extract functions and classes.

        Uses regex-based extraction (not a full parser, but handles common patterns).

        Args:
            file_path: Path to JS/TS file
            content: Source code content

        Returns:
            List of CodeSymbol objects
        """
        symbols: list[CodeSymbol] = []

        # Pattern 1: Arrow function assignments (const foo = () => {})
        arrow_pattern = r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(\s*[^)]*\s*\)\s*=>"
        for match in re.finditer(arrow_pattern, content):
            try:
                source = _extract_function_body(content, match)
                if not source.strip():
                    continue

                symbol = CodeSymbol(
                    name=match.group(1),
                    kind="function",
                    line_number=_get_line_number(content, match.start()),
                    content=source,
                    signature=f"const {match.group(1)} = (...) =>",
                )
                symbols.append(symbol)
            except Exception as e:
                logger.warning("Failed to extract arrow function: %s", e)
                continue

        # Pattern 2: Function declarations (function foo() {})
        func_pattern = r"(?:async\s+)?function\s+(\w+)\s*\(\s*[^)]*\s*\)"
        for match in re.finditer(func_pattern, content):
            try:
                source = _extract_function_body(content, match)
                if not source.strip():
                    continue

                symbol = CodeSymbol(
                    name=match.group(1),
                    kind="function",
                    line_number=_get_line_number(content, match.start()),
                    content=source,
                    signature=f"function {match.group(1)}(...)",
                )
                symbols.append(symbol)
            except Exception as e:
                logger.warning("Failed to extract function declaration: %s", e)
                continue

        # Pattern 3: Class declarations (class Foo {})
        class_pattern = r"(?:export\s+)?(?:default\s+)?class\s+(\w+)(?:\s+extends\s+\w+)?"
        for match in re.finditer(class_pattern, content):
            try:
                source = _extract_class_body(content, match)
                if not source.strip():
                    continue

                symbol = CodeSymbol(
                    name=match.group(1),
                    kind="class",
                    line_number=_get_line_number(content, match.start()),
                    content=source,
                    signature=f"class {match.group(1)}",
                )
                symbols.append(symbol)
            except Exception as e:
                logger.warning("Failed to extract class: %s", e)
                continue

        # Pattern 4: Object method definitions (foo: function() {} or foo() {})
        # This is a simplified pattern
        method_pattern = r"(\w+)\s*:\s*(?:async\s+)?function\s*\(\s*[^)]*\s*\)"
        for match in re.finditer(method_pattern, content):
            try:
                source = _extract_function_body(content, match)
                if not source.strip():
                    continue

                symbol = CodeSymbol(
                    name=match.group(1),
                    kind="function",
                    line_number=_get_line_number(content, match.start()),
                    content=source,
                    signature=f"{match.group(1)}: function(...)",
                )
                symbols.append(symbol)
            except Exception as e:
                logger.warning("Failed to extract object method: %s", e)
                continue

        # Pattern 5: Object shorthand methods (foo() {})
        shorthand_pattern = r"(?:async\s+)?(\w+)\s*\(\s*[^)]*\s*\)\s*(?=\{)"
        # Avoid duplicate matches - only match if not already captured by method_pattern
        for match in re.finditer(shorthand_pattern, content):
            # Skip if this is inside a function declaration (already matched)
            context_start = max(0, match.start() - 100)
            context = content[context_start : match.start()]
            if "function" in context or "=>" in context:
                continue

            try:
                source = _extract_function_body(content, match)
                if not source.strip():
                    continue

                symbol = CodeSymbol(
                    name=match.group(1),
                    kind="function",
                    line_number=_get_line_number(content, match.start()),
                    content=source,
                    signature=f"{match.group(1)}(...)",
                )
                symbols.append(symbol)
            except Exception as e:
                logger.warning("Failed to extract shorthand method: %s", e)
                continue

        return symbols
