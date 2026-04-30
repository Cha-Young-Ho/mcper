"""Python code parser using AST module."""

from __future__ import annotations

import ast
import logging

from app.services.code_parser import CodeParserBase, CodeSymbol

logger = logging.getLogger(__name__)


def _extract_source_lines(content: str, node: ast.AST) -> str:
    """Extract source code for an AST node from original content."""
    lines = content.split("\n")
    if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
        return ""

    start = node.lineno - 1
    end = node.end_lineno or node.lineno

    if start < 0 or start >= len(lines):
        return ""

    return "\n".join(lines[start:end])


def _get_docstring(node: ast.AST) -> str | None:
    """Extract docstring from an AST node."""
    try:
        docstring = ast.get_docstring(node)
        return docstring if docstring else None
    except Exception:
        return None


def _get_function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Extract function signature."""
    try:
        args = []
        for arg in node.args.args:
            args.append(arg.arg)
        for arg in node.args.posonlyargs:
            args.append(arg.arg)
        for arg in node.args.kwonlyargs:
            args.append(arg.arg)

        sig = f"def {node.name}({', '.join(args)})"
        if node.returns:
            sig += " -> ..."
        return sig
    except Exception:
        return f"def {node.name}(...)"


class PythonCodeParser(CodeParserBase):
    """Parser for Python source code using AST."""

    def parse(self, file_path: str, content: str) -> list[CodeSymbol]:
        """
        Parse Python source code and extract functions and classes.

        Args:
            file_path: Path to Python file
            content: Source code content

        Returns:
            List of CodeSymbol objects
        """
        symbols: list[CodeSymbol] = []

        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            logger.warning("Failed to parse Python file %s: %s", file_path, e)
            return []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(
                node, ast.AsyncFunctionDef
            ):
                try:
                    source = _extract_source_lines(content, node)
                    if not source.strip():
                        continue

                    symbol = CodeSymbol(
                        name=node.name,
                        kind="function",
                        line_number=node.lineno,
                        content=source,
                        docstring=_get_docstring(node),
                        signature=_get_function_signature(node),
                    )
                    symbols.append(symbol)
                except Exception as e:
                    logger.warning("Failed to extract function %s: %s", node.name, e)
                    continue

            elif isinstance(node, ast.ClassDef):
                try:
                    source = _extract_source_lines(content, node)
                    if not source.strip():
                        continue

                    symbol = CodeSymbol(
                        name=node.name,
                        kind="class",
                        line_number=node.lineno,
                        content=source,
                        docstring=_get_docstring(node),
                        signature=f"class {node.name}",
                    )
                    symbols.append(symbol)
                except Exception as e:
                    logger.warning("Failed to extract class %s: %s", node.name, e)
                    continue

        return symbols
