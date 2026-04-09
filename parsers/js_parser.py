"""JavaScript/TypeScript 파서 — tree-sitter 기반 함수 추출"""

import logging

from models import FunctionInfo
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

try:
    import tree_sitter_javascript
    import tree_sitter_typescript
    from tree_sitter import Language, Parser

    TS_JS_AVAILABLE = True
except ImportError:
    TS_JS_AVAILABLE = False


class JSParser(BaseParser):
    file_extensions = [".js", ".ts", ".jsx", ".tsx"]

    TS_EXTENSIONS = {".ts", ".tsx"}

    FUNC_TYPES = {
        "function_declaration",
        "method_definition",
        "arrow_function",
        "function",
        "generator_function_declaration",
    }

    def __init__(self):
        self._parsers = {}

    def _get_parser(self, ext: str):
        if not TS_JS_AVAILABLE:
            return None
        is_ts = ext in self.TS_EXTENSIONS
        key = "ts" if is_ts else "js"
        if key not in self._parsers:
            if is_ts:
                lang = Language(tree_sitter_typescript.language_typescript())
            else:
                lang = Language(tree_sitter_javascript.language())
            parser = Parser(lang)
            self._parsers[key] = parser
        return self._parsers[key]

    def extract_functions(self, file_path: str, source: str) -> list[FunctionInfo]:
        if not TS_JS_AVAILABLE:
            logger.warning("tree-sitter-javascript/typescript 미설치, JS 파싱 스킵: %s", file_path)
            return []

        from pathlib import Path
        ext = Path(file_path).suffix.lower()
        parser = self._get_parser(ext)
        if not parser:
            return []

        tree = parser.parse(source.encode("utf-8"))
        lines = source.splitlines(keepends=True)
        functions = []

        self._walk_node(tree.root_node, lines, class_name=None, functions=functions)
        return functions

    def _walk_node(self, node, lines, class_name, functions):
        if node.type == "class_declaration" or node.type == "class":
            name = None
            for child in node.children:
                if child.type == "identifier" or child.type == "type_identifier":
                    name = child.text.decode("utf-8")
                    break
            body = node.child_by_field_name("body")
            if body:
                for child in body.children:
                    self._walk_node(child, lines, class_name=name, functions=functions)
            return

        if node.type in self.FUNC_TYPES:
            func = self._extract_function(node, lines, class_name)
            if func:
                functions.append(func)

        # variable_declarator 안의 arrow_function 처리
        if node.type == "variable_declarator":
            value = node.child_by_field_name("value")
            if value and value.type in ("arrow_function", "function"):
                name_node = node.child_by_field_name("name")
                func = self._extract_function(value, lines, class_name, override_name=name_node)
                if func:
                    functions.append(func)
                return

        for child in node.children:
            self._walk_node(child, lines, class_name=class_name, functions=functions)

    def _extract_function(self, node, lines, class_name, override_name=None) -> FunctionInfo | None:
        # 이름 추출
        name = None
        if override_name:
            name = override_name.text.decode("utf-8")
        else:
            name_node = node.child_by_field_name("name")
            if name_node:
                name = name_node.text.decode("utf-8")

        if not name:
            name = "<anonymous>"

        lineno = node.start_point[0] + 1
        end_lineno = node.end_point[0] + 1
        source_text = "".join(lines[lineno - 1 : end_lineno])

        # body 확인
        body_node = node.child_by_field_name("body")
        if body_node and body_node.type == "statement_block":
            body_start = body_node.start_point[0] + 2  # { 다음 줄
            body_indent = self._detect_indent(lines, body_start)
            has_comment = self._has_existing_comment(lines, body_start)
            is_declaration_only = False
        elif body_node:
            # arrow function with expression body: () => expr
            body_start = body_node.start_point[0] + 1
            body_indent = self._detect_indent(lines, body_start)
            has_comment = False
            is_declaration_only = False
        else:
            body_start = None
            body_indent = "    "
            has_comment = False
            is_declaration_only = True

        is_async = any(
            child.type == "async" or (child.type == "identifier" and child.text == b"async")
            for child in node.children
        )

        return FunctionInfo(
            name=name,
            source_text=source_text,
            lineno=lineno,
            end_lineno=end_lineno,
            body_start_lineno=body_start,
            col_offset=node.start_point[1],
            body_indent=body_indent,
            is_method=class_name is not None,
            is_async=is_async,
            class_name=class_name,
            has_existing_docstring=has_comment,
            language="javascript",
            is_declaration_only=is_declaration_only,
        )

    def _detect_indent(self, lines, lineno) -> str:
        if lineno and lineno <= len(lines):
            line = lines[lineno - 1]
            stripped = line.lstrip()
            if stripped:
                return line[: len(line) - len(stripped)]
        return "    "

    def _has_existing_comment(self, lines, lineno) -> bool:
        if lineno and lineno <= len(lines):
            line = lines[lineno - 1].strip()
            return line.startswith("/*") or line.startswith("//")
        return False

    def format_comment(self, raw_comment: str, indent: str) -> list[str]:
        """LLM 응답을 JSDoc 스타일 주석으로 변환"""
        comment_lines = raw_comment.strip().splitlines()
        result = []
        result.append(f"{indent}/**\n")
        for line in comment_lines:
            if line.strip():
                result.append(f"{indent} * {line}\n")
            else:
                result.append(f"{indent} *\n")
        result.append(f"{indent} */\n")
        return result
