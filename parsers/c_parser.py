"""C/C++ 파서 — tree-sitter 기반 함수 추출"""

import logging

from models import FunctionInfo
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

try:
    import tree_sitter_c
    import tree_sitter_cpp
    from tree_sitter import Language, Parser

    TS_AVAILABLE = True
except ImportError:
    TS_AVAILABLE = False


class CParser(BaseParser):
    file_extensions = [".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hh"]

    # C++ 확장자
    CPP_EXTENSIONS = {".cpp", ".hpp", ".cc", ".cxx", ".hh"}

    # 함수 정의 노드 타입
    FUNC_DEF_TYPES = {"function_definition"}
    # 함수 선언 노드 타입 (프로토타입)
    FUNC_DECL_TYPES = {"declaration"}

    def __init__(self):
        self._parsers = {}

    def _get_parser(self, ext: str):
        if not TS_AVAILABLE:
            return None
        is_cpp = ext in self.CPP_EXTENSIONS
        key = "cpp" if is_cpp else "c"
        if key not in self._parsers:
            lang = Language(tree_sitter_cpp.language()) if is_cpp else Language(tree_sitter_c.language())
            parser = Parser(lang)
            self._parsers[key] = parser
        return self._parsers[key]

    def extract_functions(self, file_path: str, source: str) -> list[FunctionInfo]:
        if not TS_AVAILABLE:
            logger.warning("tree-sitter 미설치, C/C++ 파싱 스킵: %s", file_path)
            return []

        from pathlib import Path
        ext = Path(file_path).suffix.lower()
        parser = self._get_parser(ext)
        if not parser:
            return []

        tree = parser.parse(source.encode("utf-8"))
        lines = source.splitlines(keepends=True)
        functions = []

        self._walk_node(tree.root_node, lines, functions)
        return functions

    def _walk_node(self, node, lines, functions):
        if node.type == "function_definition":
            func = self._extract_definition(node, lines)
            if func:
                functions.append(func)
        elif node.type == "declaration":
            func = self._extract_declaration(node, lines)
            if func:
                functions.append(func)
        elif node.type in ("class_specifier", "struct_specifier"):
            class_name = None
            for child in node.children:
                if child.type == "type_identifier":
                    class_name = child.text.decode("utf-8")
                    break
            body_node = node.child_by_field_name("body")
            if body_node:
                for child in body_node.children:
                    if child.type == "function_definition":
                        func = self._extract_definition(child, lines, class_name=class_name)
                        if func:
                            functions.append(func)
                    elif child.type == "declaration":
                        func = self._extract_declaration(child, lines, class_name=class_name)
                        if func:
                            functions.append(func)
            return  # 내부는 이미 처리

        for child in node.children:
            self._walk_node(child, lines, functions)

    def _extract_definition(self, node, lines, class_name=None) -> FunctionInfo | None:
        name = self._get_func_name(node)
        if not name:
            return None

        lineno = node.start_point[0] + 1
        end_lineno = node.end_point[0] + 1
        source_text = "".join(lines[lineno - 1 : end_lineno])

        # body (compound_statement) 찾기
        body_node = node.child_by_field_name("body")
        if body_node and body_node.type == "compound_statement":
            body_start = body_node.start_point[0] + 2  # { 다음 줄
            body_indent = self._detect_indent(lines, body_start)
        else:
            body_start = lineno + 1
            body_indent = "    "

        has_docstring = self._has_existing_comment(lines, body_start)

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
            has_existing_docstring=has_docstring,
            language="c",
            is_declaration_only=False,
        )

    def _extract_declaration(self, node, lines, class_name=None) -> FunctionInfo | None:
        """함수 프로토타입(선언) 추출"""
        # declarator 안에 function_declarator가 있는지 확인
        func_declarator = self._find_func_declarator(node)
        if not func_declarator:
            return None

        name = self._get_declarator_name(func_declarator)
        if not name:
            return None

        # 순수 가상 함수 (= 0) 도 포함
        lineno = node.start_point[0] + 1
        end_lineno = node.end_point[0] + 1
        source_text = "".join(lines[lineno - 1 : end_lineno])

        return FunctionInfo(
            name=name,
            source_text=source_text,
            lineno=lineno,
            end_lineno=end_lineno,
            body_start_lineno=None,
            col_offset=node.start_point[1],
            body_indent="",
            is_method=class_name is not None,
            class_name=class_name,
            has_existing_docstring=False,
            language="c",
            is_declaration_only=True,
        )

    def _find_func_declarator(self, node):
        """노드 내에서 function_declarator를 재귀 탐색"""
        if node.type == "function_declarator":
            return node
        for child in node.children:
            result = self._find_func_declarator(child)
            if result:
                return result
        return None

    def _get_func_name(self, node) -> str | None:
        declarator = node.child_by_field_name("declarator")
        if declarator:
            return self._get_declarator_name(declarator)
        return None

    def _get_declarator_name(self, node) -> str | None:
        if node.type == "identifier":
            return node.text.decode("utf-8")
        if node.type == "qualified_identifier":
            return node.text.decode("utf-8")
        for child in node.children:
            name = self._get_declarator_name(child)
            if name:
                return name
        return None

    def _detect_indent(self, lines, lineno) -> str:
        if lineno <= len(lines):
            line = lines[lineno - 1]
            stripped = line.lstrip()
            if stripped:
                return line[: len(line) - len(stripped)]
        return "    "

    def _has_existing_comment(self, lines, body_start_lineno) -> bool:
        if body_start_lineno <= len(lines):
            line = lines[body_start_lineno - 1].strip()
            return line.startswith("/*") or line.startswith("//")
        return False

    def format_comment(self, raw_comment: str, indent: str) -> list[str]:
        """LLM 응답을 C 블록 주석으로 변환"""
        comment_lines = raw_comment.strip().splitlines()
        result = []
        result.append(f"{indent}/*\n")
        for line in comment_lines:
            if line.strip():
                result.append(f"{indent} * {line}\n")
            else:
                result.append(f"{indent} *\n")
        result.append(f"{indent} */\n")
        return result
