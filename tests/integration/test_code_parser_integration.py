"""Integration tests for code parser factory + language parsers."""

import pytest

from app.services.code_parser_factory import CodeParserFactory, parse_code_file


@pytest.mark.integration
class TestCodeParserFactoryIntegration:
    """Test parser factory selects correct parser and parses code."""

    def test_python_parser_selected(self):
        """Factory returns Python parser for .py files."""
        parser = CodeParserFactory.get_parser("main.py")
        assert parser is not None

    def test_javascript_parser_selected_js(self):
        """Factory returns JS parser for .js files."""
        parser = CodeParserFactory.get_parser("app.js")
        assert parser is not None

    def test_javascript_parser_selected_ts(self):
        """Factory returns JS parser for .ts files."""
        parser = CodeParserFactory.get_parser("app.ts")
        assert parser is not None

    def test_javascript_parser_selected_tsx(self):
        """Factory returns JS parser for .tsx files."""
        parser = CodeParserFactory.get_parser("component.tsx")
        assert parser is not None

    def test_unsupported_extension_returns_none(self):
        """Factory returns None for unsupported file types."""
        assert CodeParserFactory.get_parser("data.csv") is None
        assert CodeParserFactory.get_parser("Makefile") is None
        assert CodeParserFactory.get_parser("readme.md") is None

    def test_parse_python_function(self):
        """Python parser extracts function symbols."""
        code = '''
def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}!"
'''
        symbols = parse_code_file("test.py", code)
        assert len(symbols) >= 1
        func = next((s for s in symbols if s.name == "hello"), None)
        assert func is not None
        assert func.kind == "function"

    def test_parse_python_class(self):
        """Python parser extracts class symbols."""
        code = '''
class MyService:
    """A service class."""

    def process(self):
        pass
'''
        symbols = parse_code_file("service.py", code)
        cls = next((s for s in symbols if s.name == "MyService"), None)
        assert cls is not None
        assert cls.kind == "class"

    def test_parse_python_async_function(self):
        """Python parser extracts async function symbols."""
        code = '''
async def fetch_data(url: str):
    """Fetch data from URL."""
    pass
'''
        symbols = parse_code_file("async_mod.py", code)
        func = next((s for s in symbols if s.name == "fetch_data"), None)
        assert func is not None

    def test_parse_empty_file(self):
        """Parsing an empty file returns empty list."""
        symbols = parse_code_file("empty.py", "")
        assert symbols == []

    def test_parse_syntax_error_file(self):
        """Parsing a file with syntax errors doesn't crash."""
        code = "def broken(:\n  pass"
        symbols = parse_code_file("broken.py", code)
        assert isinstance(symbols, list)

    def test_parse_unsupported_file(self):
        """Parsing unsupported file type returns empty list."""
        symbols = parse_code_file("data.csv", "col1,col2\nval1,val2")
        assert symbols == []

    def test_parse_python_nested_classes(self):
        """Python parser handles nested classes."""
        code = """
class Outer:
    class Inner:
        def method(self):
            pass
"""
        symbols = parse_code_file("nested.py", code)
        assert len(symbols) >= 1

    def test_parse_python_module_level_vars(self):
        """Python parser handles module with only assignments."""
        code = """
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30
"""
        symbols = parse_code_file("config.py", code)
        assert isinstance(symbols, list)
