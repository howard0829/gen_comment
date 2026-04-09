"""C/C++ 파서 — 소스 파일 전용, 단순 패턴 매칭 기반 함수 추출

함수 인식 규칙:
  (자료형) (함수명)(인풋) { ... }
  - 함수명 바로 뒤 '(' 부터 대응하는 ')' 까지가 인풋
  - ')' 뒤 '{' 부터 대응하는 '}' 까지가 함수 본문
  - 중괄호는 열린 수만큼 닫힐 때까지 함수로 간주

헤더 파일(.h, .hpp, .hh)은 스킵한다.
"""

import re

from models import FunctionInfo
from parsers.base import BaseParser

# 헤더 확장자
_HEADER_EXTENSIONS = {".h", ".hpp", ".hh"}

# 함수가 아닌 키워드 (이것들 뒤에 '('가 와도 함수가 아님)
_NON_FUNC_KEYWORDS = {
    "if", "else", "for", "while", "do", "switch", "case", "return",
    "sizeof", "typeof", "alignof", "static_assert", "catch", "throw",
    "typedef", "using", "namespace", "struct", "class", "enum", "union",
}


class CParser(BaseParser):
    file_extensions = [".c", ".cpp", ".cc", ".cxx"]

    def extract_functions(self, file_path: str, source: str) -> list[FunctionInfo]:
        # 헤더 파일 스킵
        lower_path = file_path.lower()
        for ext in _HEADER_EXTENSIONS:
            if lower_path.endswith(ext):
                return []

        lines = source.splitlines(keepends=True)
        if not lines:
            return []

        # 주석/문자열을 공백으로 치환한 클린 소스
        clean = self._strip_comments_and_strings(source)
        functions = []

        # 패턴: 함수명 바로 뒤에 '(' → 인풋 → ')' → 공백/키워드 → '{'
        # 전략: clean 소스에서 모든 '{'를 찾고, 그 앞에 ')' ... '{' 패턴이 있는지 역추적
        i = 0
        n = len(clean)

        while i < n:
            if clean[i] != "{":
                i += 1
                continue

            brace_open_pos = i

            # '{' 앞에서 ')' 를 찾는다 (const, volatile, noexcept 등 키워드 건너뛰기)
            close_paren_pos = self._find_close_paren_before_brace(clean, brace_open_pos)
            if close_paren_pos is None:
                i += 1
                continue

            # ')' 에서 매칭하는 '(' 찾기
            open_paren_pos = self._match_paren_backward(clean, close_paren_pos)
            if open_paren_pos is None:
                i += 1
                continue

            # '(' 바로 앞에서 함수명 추출
            func_name = self._extract_func_name_before(clean, open_paren_pos)
            if not func_name or func_name in _NON_FUNC_KEYWORDS:
                i += 1
                continue

            # 함수명 앞에 자료형(반환 타입)이 있는지 확인
            name_start = open_paren_pos - 1
            while name_start >= 0 and clean[name_start] in " \t\n\r":
                name_start -= 1
            # 함수명 길이만큼 되돌리기
            raw_name = func_name.replace("::", "").replace("~", "")
            name_start_pos = open_paren_pos
            j = open_paren_pos - 1
            while j >= 0 and clean[j] in " \t\n\r":
                j -= 1
            # 함수명의 시작 위치 찾기
            fname_end = j + 1
            while j >= 0 and (clean[j].isalnum() or clean[j] in "_:~"):
                j -= 1
            fname_start = j + 1

            # 반환 타입 확인: 함수명 앞에 뭔가 있어야 함
            k = fname_start - 1
            while k >= 0 and clean[k] in " \t\n\r":
                k -= 1
            if k < 0 or clean[k] in "{};#":
                # 반환 타입 없음 → 매크로이거나 비함수
                # 단, 생성자/소멸자는 반환 타입이 없을 수 있음
                if "::" not in func_name and "~" not in func_name:
                    i += 1
                    continue

            # '{' 부터 대응하는 '}' 찾기 (중괄호 매칭)
            brace_close_pos = self._match_brace_forward(clean, brace_open_pos)
            if brace_close_pos is None:
                i += 1
                continue

            # 시그니처 시작 위치 (반환 타입 시작)
            sig_start = self._find_signature_start(clean, fname_start)

            # 라인 번호 계산
            sig_line = clean[:sig_start].count("\n") + 1
            body_start_line = clean[:brace_open_pos].count("\n") + 1 + 1  # { 다음 줄
            end_line = clean[:brace_close_pos].count("\n") + 1

            # 원본 소스 텍스트
            source_text = "".join(lines[sig_line - 1 : end_line])

            # 본문 들여쓰기
            body_indent = self._detect_indent(lines, body_start_line)

            # 기존 주석 확인 (함수 앞에 /** ... */ 스타일 doc-comment가 있는지)
            has_comment = self._has_existing_doc_comment(lines, sig_line)

            # col_offset
            col_offset = 0
            if sig_line <= len(lines):
                lt = lines[sig_line - 1]
                col_offset = len(lt) - len(lt.lstrip())

            # 클래스명 분리 (Class::method → class_name=Class, name=method)
            class_name = None
            short_name = func_name
            if "::" in func_name:
                parts = func_name.rsplit("::", 1)
                class_name = parts[0]
                short_name = parts[1]

            functions.append(FunctionInfo(
                name=short_name,
                source_text=source_text,
                lineno=sig_line,
                end_lineno=end_line,
                body_start_lineno=body_start_line,
                col_offset=col_offset,
                body_indent=body_indent,
                is_method=class_name is not None,
                class_name=class_name,
                has_existing_docstring=has_comment,
                language="c",
                is_declaration_only=False,
            ))

            # 함수 본문 이후로 스캔 위치 이동
            i = brace_close_pos + 1

        functions.sort(key=lambda f: f.lineno)
        return functions

    # ─── 헬퍼 메서드들 ──────────────────────────────────────────

    def _strip_comments_and_strings(self, source: str) -> str:
        """주석과 문자열 리터럴을 공백으로 치환. 줄바꿈은 보존."""
        result = []
        i = 0
        n = len(source)

        while i < n:
            # 한줄 주석
            if source[i:i+2] == "//":
                result.append("  ")
                i += 2
                while i < n and source[i] != "\n":
                    result.append(" ")
                    i += 1
            # 블록 주석
            elif source[i:i+2] == "/*":
                result.append("  ")
                i += 2
                while i < n and source[i:i+2] != "*/":
                    result.append("\n" if source[i] == "\n" else " ")
                    i += 1
                if i < n:
                    result.append("  ")
                    i += 2
            # 문자열
            elif source[i] in ('"', "'"):
                quote = source[i]
                result.append(" ")
                i += 1
                while i < n and source[i] != quote:
                    if source[i] == "\\" and i + 1 < n:
                        result.append("  ")
                        i += 2
                    else:
                        result.append("\n" if source[i] == "\n" else " ")
                        i += 1
                if i < n:
                    result.append(" ")
                    i += 1
            # Raw string R"(...)"
            elif source[i:i+2] == 'R"':
                result.append("  ")
                i += 2
                delim_start = i
                while i < n and source[i] != "(":
                    i += 1
                delim = source[delim_start:i]
                end_marker = f"){delim}\""
                result.append(" " * (i - delim_start + 1))
                i += 1
                while i < n:
                    if source[i:i+len(end_marker)] == end_marker:
                        result.append(" " * len(end_marker))
                        i += len(end_marker)
                        break
                    result.append("\n" if source[i] == "\n" else " ")
                    i += 1
            else:
                result.append(source[i])
                i += 1

        return "".join(result)

    def _find_close_paren_before_brace(self, clean: str, brace_pos: int) -> int | None:
        """'{' 앞에서 가장 가까운 ')' 위치를 찾는다.
        '{' 와 ')' 사이에는 공백, const, volatile, override, noexcept, final,
        후행 반환 타입(-> Type), 이니셜라이저 리스트(: member(val)) 등이 올 수 있다.
        """
        i = brace_pos - 1
        # 이니셜라이저 리스트 감지: ':' 가 있으면 그 앞으로 이동
        scan = brace_pos - 1
        paren_depth = 0
        while scan >= 0:
            ch = clean[scan]
            if ch == ")":
                paren_depth += 1
            elif ch == "(":
                paren_depth -= 1
            elif ch == ":" and paren_depth == 0:
                if scan > 0 and clean[scan - 1] != ":" and (scan + 1 >= len(clean) or clean[scan + 1] != ":"):
                    # 이니셜라이저 ':' 발견 → 이 앞에서 ')' 를 찾는다
                    i = scan - 1
                    break
            elif ch in ";{}":
                break
            scan -= 1

        # 공백 + 키워드 건너뛰기
        while i >= 0 and clean[i] in " \t\n\r":
            i -= 1

        # 후행 반환 타입/키워드 건너뛰기
        while i >= 0:
            # 현재 위치에서 끝나는 단어 확인
            if clean[i].isalpha() or clean[i] == "_":
                word_end = i + 1
                while i >= 0 and (clean[i].isalpha() or clean[i] == "_"):
                    i -= 1
                word = clean[i + 1:word_end]
                if word in ("const", "override", "noexcept", "final", "volatile"):
                    while i >= 0 and clean[i] in " \t\n\r":
                        i -= 1
                    continue
                else:
                    # 후행 반환 타입의 일부일 수 있음 → '->' 확인
                    temp = i
                    while temp >= 0 and clean[temp] in " \t\n\r":
                        temp -= 1
                    if temp >= 1 and clean[temp - 1:temp + 1] == "->":
                        # '->' 앞으로 이동
                        i = temp - 2
                        while i >= 0 and clean[i] in " \t\n\r":
                            i -= 1
                        continue
                    else:
                        i = word_end - 1
                        break
            elif clean[i] == ">":
                # 템플릿 반환 타입 건너뛰기
                depth = 1
                i -= 1
                while i >= 0 and depth > 0:
                    if clean[i] == ">":
                        depth += 1
                    elif clean[i] == "<":
                        depth -= 1
                    i -= 1
                # '->' 확인
                temp = i
                while temp >= 0 and clean[temp] in " \t\n\r":
                    temp -= 1
                if temp >= 1 and clean[temp - 1:temp + 1] == "->":
                    i = temp - 2
                    while i >= 0 and clean[i] in " \t\n\r":
                        i -= 1
                    continue
                else:
                    break
            else:
                break

        if i < 0 or clean[i] != ")":
            return None
        return i

    def _match_paren_backward(self, clean: str, close_pos: int) -> int | None:
        """')' 에서 역방향으로 매칭되는 '(' 위치를 반환."""
        depth = 1
        i = close_pos - 1
        while i >= 0 and depth > 0:
            if clean[i] == ")":
                depth += 1
            elif clean[i] == "(":
                depth -= 1
            i -= 1
        if depth != 0:
            return None
        return i + 1  # '(' 위치

    def _extract_func_name_before(self, clean: str, open_paren_pos: int) -> str | None:
        """'(' 바로 앞에서 함수명을 추출."""
        j = open_paren_pos - 1
        while j >= 0 and clean[j] in " \t\n\r":
            j -= 1
        if j < 0:
            return None

        name_end = j + 1
        while j >= 0 and (clean[j].isalnum() or clean[j] in "_:~"):
            j -= 1
        name_start = j + 1

        name = clean[name_start:name_end].strip()
        if not name or name.startswith("::"):
            return None
        return name

    def _match_brace_forward(self, clean: str, open_pos: int) -> int | None:
        """'{' 에서 정방향으로 매칭되는 '}' 위치를 반환."""
        depth = 1
        i = open_pos + 1
        n = len(clean)
        while i < n and depth > 0:
            if clean[i] == "{":
                depth += 1
            elif clean[i] == "}":
                depth -= 1
            i += 1
        if depth != 0:
            return None
        return i - 1  # '}' 위치

    def _find_signature_start(self, clean: str, fname_start: int) -> int:
        """함수명 시작 위치에서 역추적하여 반환 타입/template 시작 위치를 찾는다."""
        k = fname_start - 1
        while k >= 0 and clean[k] in " \t\n\r":
            k -= 1

        if k >= 0 and (clean[k].isalnum() or clean[k] in "*&>_"):
            while k >= 0 and (clean[k].isalnum() or clean[k] in "*&<>:_, \t"):
                k -= 1
            return k + 1

        return fname_start

    def _detect_indent(self, lines, lineno) -> str:
        if 1 <= lineno <= len(lines):
            line = lines[lineno - 1]
            stripped = line.lstrip()
            if stripped:
                return line[: len(line) - len(stripped)]
        return "    "

    def _has_existing_doc_comment(self, lines, func_lineno) -> bool:
        """함수 시그니처 바로 위에 doc-comment(/** ... */)가 있는지 확인."""
        check_line = func_lineno - 2  # func_lineno는 1-based, 바로 윗줄은 -2 (0-based)
        if check_line < 0:
            return False
        line = lines[check_line].strip()
        # */ 로 끝나는 블록 주석 (Doxygen /** ... */ 스타일)
        if line.endswith("*/"):
            return True
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
