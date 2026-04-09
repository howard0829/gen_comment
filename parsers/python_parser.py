"""Python 파서 — ast 모듈 기반 함수 추출"""

import ast

from models import FunctionInfo
from parsers.base import BaseParser


class PythonParser(BaseParser):
    file_extensions = [".py"]

    def extract_functions(self, file_path: str, source: str) -> list[FunctionInfo]:
        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            return []

        lines = source.splitlines(keepends=True)
        functions = []
        self._walk(tree, lines, file_path, parent_class=None, functions=functions)
        return functions

    def _walk(self, node, lines, file_path, parent_class, functions):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                self._walk(child, lines, file_path, parent_class=child.name, functions=functions)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_info = self._extract_one(child, lines, parent_class)
                if func_info:
                    functions.append(func_info)
                # 중첩 함수도 탐색
                self._walk(child, lines, file_path, parent_class=None, functions=functions)
            else:
                self._walk(child, lines, file_path, parent_class=parent_class, functions=functions)

    def _extract_one(self, node, lines, parent_class) -> FunctionInfo | None:
        if not node.body:
            return None

        lineno = node.lineno
        end_lineno = node.end_lineno or lineno
        body_first = node.body[0]
        body_start_lineno = body_first.lineno

        # 소스 텍스트 추출
        source_text = "".join(lines[lineno - 1 : end_lineno])

        # 본문 들여쓰기 감지
        body_line = lines[body_start_lineno - 1] if body_start_lineno <= len(lines) else ""
        body_indent = body_line[: len(body_line) - len(body_line.lstrip())]
        if not body_indent:
            body_indent = " " * (node.col_offset + 4)

        # 기존 docstring 확인
        has_docstring = (
            isinstance(body_first, ast.Expr)
            and isinstance(body_first.value, ast.Constant)
            and isinstance(body_first.value.value, str)
        )

        # 데코레이터
        decorators = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                decorators.append(ast.dump(dec))
            elif isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    decorators.append(dec.func.id)
                elif isinstance(dec.func, ast.Attribute):
                    decorators.append(ast.dump(dec.func))

        # 선언 전용 판별: body가 pass, ..., 또는 raise NotImplementedError만
        is_declaration_only = self._is_declaration_only(node)

        return FunctionInfo(
            name=node.name,
            source_text=source_text,
            lineno=lineno,
            end_lineno=end_lineno,
            body_start_lineno=body_start_lineno,
            col_offset=node.col_offset,
            body_indent=body_indent,
            is_method=parent_class is not None,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            class_name=parent_class,
            decorators=decorators,
            has_existing_docstring=has_docstring,
            language="python",
            is_declaration_only=is_declaration_only,
        )

    def _is_declaration_only(self, node) -> bool:
        """본문이 pass, Ellipsis, raise NotImplementedError만인지 확인"""
        body = node.body
        # docstring 제외
        start = 0
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            start = 1

        remaining = body[start:]
        if not remaining:
            return True

        for stmt in remaining:
            if isinstance(stmt, ast.Pass):
                continue
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                if stmt.value.value is ...:
                    continue
            if isinstance(stmt, ast.Raise):
                if isinstance(stmt.exc, ast.Call) and isinstance(stmt.exc.func, ast.Name):
                    if stmt.exc.func.id == "NotImplementedError":
                        continue
            return False
        return True

    def format_comment(self, raw_comment: str, indent: str) -> list[str]:
        """LLM 응답을 Python docstring 라인 리스트로 변환"""
        comment_lines = raw_comment.strip().splitlines()
        result = []
        result.append(f'{indent}"""\n')
        for line in comment_lines:
            if line.strip():
                result.append(f"{indent}{line}\n")
            else:
                result.append(f"{indent}\n")
        result.append(f'{indent}"""\n')
        return result
