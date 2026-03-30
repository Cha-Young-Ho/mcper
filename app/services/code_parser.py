"""Code parser interface for language-specific AST extraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CodeSymbol:
    """Represents a single code symbol (function, class, variable, etc.)."""

    name: str  # Function/class/variable name
    kind: str  # "function" / "class" / "variable" / "fragment"
    line_number: int  # Starting line in source file
    content: str  # Source code snippet
    docstring: str | None = None  # Documentation string if present
    signature: str | None = None  # Function/class signature


class CodeParserBase(ABC):
    """Abstract base class for language-specific code parsers."""

    @abstractmethod
    def parse(self, file_path: str, content: str) -> list[CodeSymbol]:
        """
        Parse source code and extract symbols.

        Args:
            file_path: Path to the source file (for metadata)
            content: Source code content

        Returns:
            List of CodeSymbol objects
        """
        pass
