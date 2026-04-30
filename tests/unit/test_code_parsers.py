"""Unit tests for code_parser, code_parser_python, code_parser_javascript, code_parser_factory."""

from __future__ import annotations


from app.services.code_parser import CodeSymbol
from app.services.code_parser_factory import CodeParserFactory, parse_code_file
from app.services.code_parser_python import (
    PythonCodeParser,
    _extract_source_lines,
)
from app.services.code_parser_javascript import (
    JavaScriptCodeParser,
    _find_function_end,
    _get_line_number,
)


# ── CodeSymbol dataclass ────────────────────────────────────────────


class TestCodeSymbol:
    def test_creation(self):
        sym = CodeSymbol(
            name="foo", kind="function", line_number=1, content="def foo(): pass"
        )
        assert sym.name == "foo"
        assert sym.docstring is None
        assert sym.signature is None

    def test_with_optional_fields(self):
        sym = CodeSymbol(
            name="Bar",
            kind="class",
            line_number=10,
            content="class Bar: ...",
            docstring="A class.",
            signature="class Bar",
        )
        assert sym.docstring == "A class."
        assert sym.signature == "class Bar"


# ── PythonCodeParser ────────────────────────────────────────────────


class TestPythonCodeParser:
    def setup_method(self):
        self.parser = PythonCodeParser()

    def test_parse_simple_function(self):
        code = 'def hello():\n    """Say hello."""\n    print("hi")\n'
        symbols = self.parser.parse("test.py", code)
        names = [s.name for s in symbols]
        assert "hello" in names
        func = [s for s in symbols if s.name == "hello"][0]
        assert func.kind == "function"
        assert func.docstring == "Say hello."

    def test_parse_async_function(self):
        code = "async def fetch():\n    pass\n"
        symbols = self.parser.parse("test.py", code)
        assert any(s.name == "fetch" and s.kind == "function" for s in symbols)

    def test_parse_class(self):
        code = 'class MyClass:\n    """A class."""\n    pass\n'
        symbols = self.parser.parse("test.py", code)
        cls = [s for s in symbols if s.name == "MyClass"][0]
        assert cls.kind == "class"
        assert cls.docstring == "A class."

    def test_parse_syntax_error_returns_empty(self):
        code = "def broken(\n"
        symbols = self.parser.parse("bad.py", code)
        assert symbols == []

    def test_parse_empty_content(self):
        symbols = self.parser.parse("empty.py", "")
        assert symbols == []

    def test_function_signature_extraction(self):
        code = "def add(a, b):\n    return a + b\n"
        symbols = self.parser.parse("math.py", code)
        func = [s for s in symbols if s.name == "add"][0]
        assert "a" in func.signature
        assert "b" in func.signature

    def test_multiple_functions(self):
        code = "def a():\n    pass\n\ndef b():\n    pass\n\ndef c():\n    pass\n"
        symbols = self.parser.parse("multi.py", code)
        names = {s.name for s in symbols}
        assert names == {"a", "b", "c"}

    def test_nested_function_extracted(self):
        code = "def outer():\n    def inner():\n        pass\n"
        symbols = self.parser.parse("nested.py", code)
        names = {s.name for s in symbols}
        assert "outer" in names
        assert "inner" in names


# ── PythonCodeParser helpers ────────────────────────────────────────


class TestPythonHelpers:
    def test_extract_source_lines(self):
        import ast

        code = "x = 1\ndef foo():\n    pass\n"
        tree = ast.parse(code)
        funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        src = _extract_source_lines(code, funcs[0])
        assert "def foo" in src

    def test_get_line_number_js(self):
        content = "line1\nline2\nline3"
        assert _get_line_number(content, 0) == 1
        assert _get_line_number(content, 6) == 2
        assert _get_line_number(content, 12) == 3


# ── JavaScriptCodeParser ───────────────────────────────────────────


class TestJavaScriptCodeParser:
    def setup_method(self):
        self.parser = JavaScriptCodeParser()

    def test_parse_function_declaration(self):
        code = "function hello() {\n  console.log('hi');\n}\n"
        symbols = self.parser.parse("test.js", code)
        assert any(s.name == "hello" and s.kind == "function" for s in symbols)

    def test_parse_arrow_function(self):
        code = "const greet = () => {\n  return 'hi';\n};\n"
        symbols = self.parser.parse("test.js", code)
        assert any(s.name == "greet" and s.kind == "function" for s in symbols)

    def test_parse_async_function(self):
        code = "async function fetchData() {\n  return await fetch();\n}\n"
        symbols = self.parser.parse("test.js", code)
        assert any(s.name == "fetchData" for s in symbols)

    def test_parse_class(self):
        code = "class MyComponent {\n  render() {\n    return null;\n  }\n}\n"
        symbols = self.parser.parse("test.jsx", code)
        assert any(s.name == "MyComponent" and s.kind == "class" for s in symbols)

    def test_parse_empty_content(self):
        symbols = self.parser.parse("empty.js", "")
        assert symbols == []

    def test_find_function_end_balanced(self):
        content = "{ a { b } c }"
        end = _find_function_end(content, 0)
        assert end == len(content)

    def test_find_function_end_unbalanced(self):
        content = "{ open without close"
        end = _find_function_end(content, 0)
        assert end == len(content)

    def test_parse_object_method(self):
        code = "const obj = {\n  method: function() {\n    return 1;\n  }\n};\n"
        symbols = self.parser.parse("test.js", code)
        assert any(s.name == "method" for s in symbols)


# ── CodeParserFactory ───────────────────────────────────────────────


class TestCodeParserFactory:
    def test_get_parser_python(self):
        parser = CodeParserFactory.get_parser("foo.py")
        assert isinstance(parser, PythonCodeParser)

    def test_get_parser_javascript(self):
        parser = CodeParserFactory.get_parser("app.js")
        assert isinstance(parser, JavaScriptCodeParser)

    def test_get_parser_typescript(self):
        parser = CodeParserFactory.get_parser("component.tsx")
        assert isinstance(parser, JavaScriptCodeParser)

    def test_get_parser_unknown_returns_none(self):
        assert CodeParserFactory.get_parser("file.rb") is None
        assert CodeParserFactory.get_parser("file.go") is None
        assert CodeParserFactory.get_parser("noext") is None

    def test_parse_code_file_python(self):
        code = "def greet():\n    pass\n"
        symbols = parse_code_file("greet.py", code)
        assert any(s.name == "greet" for s in symbols)

    def test_parse_code_file_unsupported(self):
        symbols = parse_code_file("style.css", "body { color: red; }")
        assert symbols == []
