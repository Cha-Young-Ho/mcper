"""Factory for creating language-specific code parsers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.code_parser import CodeParserBase, CodeSymbol

logger = logging.getLogger(__name__)


class CodeParserFactory:
    """Factory for selecting appropriate parser based on file extension."""

    # Lazy-loaded parsers to avoid circular imports
    _PARSER_MAP: dict[str, str] = {
        "py": "app.services.code_parser_python:PythonCodeParser",
        "pyx": "app.services.code_parser_python:PythonCodeParser",
        "js": "app.services.code_parser_javascript:JavaScriptCodeParser",
        "jsx": "app.services.code_parser_javascript:JavaScriptCodeParser",
        "ts": "app.services.code_parser_javascript:JavaScriptCodeParser",
        "tsx": "app.services.code_parser_javascript:JavaScriptCodeParser",
    }

    @classmethod
    def get_parser(cls, file_path: str) -> CodeParserBase | None:
        """
        Get parser instance for a given file path.

        Args:
            file_path: Path to source file

        Returns:
            CodeParser instance or None if no parser for file type
        """
        ext = file_path.split(".")[-1].lower()
        parser_spec = cls._PARSER_MAP.get(ext)

        if not parser_spec:
            return None

        try:
            module_path, class_name = parser_spec.split(":")
            parts = module_path.split(".")
            module = __import__(module_path, fromlist=[parts[-1]])
            parser_class = getattr(module, class_name)
            return parser_class()
        except (ImportError, AttributeError, ValueError) as e:
            logger.warning("Failed to load parser for %s: %s", file_path, e)
            return None


def parse_code_file(file_path: str, content: str) -> list[CodeSymbol]:
    """
    Parse a code file and extract symbols.

    Args:
        file_path: Path to source file
        content: Source code content

    Returns:
        List of CodeSymbol objects
    """
    parser = CodeParserFactory.get_parser(file_path)
    if not parser:
        logger.debug("No parser available for file type: %s", file_path)
        return []

    try:
        return parser.parse(file_path, content)
    except Exception as e:
        logger.exception("Parser failed for %s: %s", file_path, e)
        return []
