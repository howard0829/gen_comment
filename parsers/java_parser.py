"""Java 파서 — tree-sitter 기반 함수 추출"""

import logging

from models import FunctionInfo
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

try:
    import tree_sitter_java
    from tree_sitter import Language, Parser

    TS_JAVA_AVAILABLE = True
except ImportError:
    TS_JAVA_AVAILABLE = False


class JavaParser(BaseParser):
    file_extensions = [".java"]

    METHOD_TYPES = {"method_declaration", "constructor_declaration"}

    def __init__(self):
        self._parser = None

    def _get_parser(self):
        if not TS_JAVA_AVAILABLE:
            return None
        if self._parser is None:
            lang = Language(tree_sitter_java.language())
            self._parser = Parser(lang)
        return self._parser

    def extract_functions(self, file_path: str, source: str) -> list[FunctionInfo]:
        if not TS_JAVA_AVAILABLE:
            logger.warning("tree-sitter-java 미설치, Java 파싱 스킵: %s", file_path)
            return []

        parser = self._get_parser()
        if not parser:
            return []

        tree = parser.parse(source.encode("utf-8"))
        lines = source.splitlines(keepends=True)
        functions = []

        self._walk_node(tree.root_node, lines, class_name=None, functions=functions)
        return functions

    def _walk_node(self, node, lines, class_name, functions):
        if node.type in ("class_declaration", "interface_declaration", "enum_declaration"):
            name = None
            for child in node.children:
                if child.type == "identifier":
                    name = child.text.decode("utf-8")
                    break
            body = node.child_by_field_name("body")
            if body:
                for child in body.children:
                    self._walk_node(child, lines, class_name=name, functions=functions)
            return

        if node.type in self.METHOD_TYPES:
            func = self._extract_method(node, lines, class_name)
            if func:
                functions.append(func)
            return

        for child in node.children:
            self._walk_node(child, lines, class_name=class_name, functions=functions)

    def _extract_method(self, node, lines, class_name) -> FunctionInfo | None:
        name = None
        for child in node.children:
            if child.type == "identifier":
                name = child.text.decode("utf-8")
                break
        if not name:
            return None

        lineno = node.start_point[0] + 1
        end_lineno = node.end_point[0] + 1
        source_text = "".join(lines[lineno - 1 : end_lineno])

        # body (block) 확인
        body_node = node.child_by_field_name("body")
        is_declaration_only = body_node is None

        if body_node and body_node.type == "block":
            body_start = body_node.start_point[0] + 2  # { 다음 줄
            body_indent = self._detect_indent(lines, body_start)
        else:
            body_start = None
            body_indent = self._detect_indent(lines, lineno) + "    "

        has_docstring = False
        if body_start and body_start <= len(lines):
            line = lines[body_start - 1].strip()
            has_docstring = line.startswith("/*") or line.startswith("//")

        # 어노테이션 추출
        decorators = []
        for child in node.children:
            if child.type == "marker_annotation" or child.type == "annotation":
                decorators.append(child.text.decode("utf-8"))

        return FunctionInfo(
            name=name,
            source_text=source_text,
            lineno=lineno,
            end_lineno=end_lineno,
            body_start_lineno=body_start,
            col_offset=node.start_point[1],
            body_indent=body_indent,
            is_method=class_name is not None,
            class_name=class_name,
            decorators=decorators,
            has_existing_docstring=has_docstring,
            language="java",
            is_declaration_only=is_declaration_only,
        )

    def _detect_indent(self, lines, lineno) -> str:
        if lineno and lineno <= len(lines):
            line = lines[lineno - 1]
            stripped = line.lstrip()
            if stripped:
                return line[: len(line) - len(stripped)]
        return "        "

    def format_comment(self, raw_comment: str, indent: str) -> list[str]:
        """LLM 응답을 Javadoc 스타일 주석으로 변환"""
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
