"""C/C++ 파서 — 정규식 + 중괄호 매칭 기반 함수 추출 (외부 의존성 없음)

전략:
1. 소스에서 주석/문자열을 플레이스홀더로 치환 (중괄호 오인 방지)
2. 중괄호 매칭으로 모든 블록 경계를 파악
3. 정규식으로 함수 시그니처 패턴을 탐지
4. 시그니처 뒤에 { 가 오면 함수 정의, ; 가 오면 함수 선언
"""

import re
from dataclasses import dataclass

from models import FunctionInfo
from parsers.base import BaseParser


@dataclass
class _Block:
    """중괄호 블록 정보"""
    open_line: int   # { 가 있는 라인 (1-based)
    close_line: int  # } 가 있는 라인 (1-based)
    open_pos: int    # 소스 내 { 의 위치
    close_pos: int   # 소스 내 } 의 위치


# 함수 시그니처에 해당하지 않는 키워드 (이것들 뒤에 (가 오면 함수가 아님)
_NON_FUNC_KEYWORDS = {
    "if", "else", "for", "while", "do", "switch", "case", "return",
    "sizeof", "typeof", "alignof", "static_assert", "catch", "throw",
    "typedef", "using", "namespace",
}

# 함수 시그니처 패턴:
#   [template<...>] [키워드들] 반환타입 [클래스::] 함수명 (파라미터)
#   여러 줄에 걸쳐 올 수 있으므로, 소스에서 ( ) 쌍을 찾은 뒤 역추적
_FUNC_NAME_RE = re.compile(
    r"""
    (?:^|[\s;{}])                       # 시작 경계
    (                                   # 캡처 그룹: 전체 시그니처
        (?:template\s*<[^>]*>\s*)?      # 선택: template<...>
        (?:[\w:*&<>\[\]\s,]+\s+)        # 반환 타입 (포인터/레퍼런스/템플릿 포함)
        (~?\w[\w:]*)                    # 함수명 (소멸자 ~, 네임스페이스 :: 포함)
        \s*
    )
    \(                                  # 여는 괄호
    """,
    re.VERBOSE | re.MULTILINE,
)

# 전처리기 지시문 패턴
_PREPROCESSOR_RE = re.compile(r"^\s*#", re.MULTILINE)


class CParser(BaseParser):
    file_extensions = [".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hh"]

    def extract_functions(self, file_path: str, source: str) -> list[FunctionInfo]:
        lines = source.splitlines(keepends=True)
        if not lines:
            return []

        # 1단계: 주석/문자열을 공백으로 치환한 클린 소스 생성
        clean = self._strip_comments_and_strings(source)

        # 2단계: 중괄호 블록 매핑
        blocks = self._find_brace_blocks(clean, lines)

        # 3단계: class/struct 블록 식별 (메서드 감지용)
        class_ranges = self._find_class_ranges(clean, blocks, lines)

        # 4단계: 함수 정의 + 선언 추출
        functions = []
        self._find_function_definitions(clean, source, lines, blocks, class_ranges, functions)
        self._find_function_declarations(clean, source, lines, class_ranges, functions)

        # 라인 순으로 정렬
        functions.sort(key=lambda f: f.lineno)
        return functions

    # ─── 1단계: 주석/문자열 제거 ─────────────────────────────────

    def _strip_comments_and_strings(self, source: str) -> str:
        """주석과 문자열 리터럴을 공백으로 치환. 줄바꿈은 보존하여 라인 번호 유지."""
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
            # 문자열 리터럴
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
                # delimiter 추출
                delim_start = i
                while i < n and source[i] != "(":
                    i += 1
                delim = source[delim_start:i]
                end_marker = f"){delim}\""
                result.append(" " * (i - delim_start + 1))
                i += 1  # skip (
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

    # ─── 2단계: 중괄호 블록 매핑 ────────────────────────────────

    def _find_brace_blocks(self, clean: str, lines: list[str]) -> list[_Block]:
        """중괄호 쌍을 매칭하여 블록 리스트 반환."""
        blocks = []
        stack = []  # (pos, line_num)

        line_num = 1
        for i, ch in enumerate(clean):
            if ch == "\n":
                line_num += 1
            elif ch == "{":
                stack.append((i, line_num))
            elif ch == "}":
                if stack:
                    open_pos, open_line = stack.pop()
                    blocks.append(_Block(
                        open_line=open_line,
                        close_line=line_num,
                        open_pos=open_pos,
                        close_pos=i,
                    ))

        return blocks

    # ─── 3단계: class/struct 범위 식별 ──────────────────────────

    def _find_class_ranges(self, clean, blocks, lines):
        """class/struct 이름과 블록 범위를 매핑."""
        # class/struct 이름 { 패턴
        pattern = re.compile(
            r"\b(?:class|struct)\s+(\w+)(?:\s*:[^{]*)?\s*\{",
            re.MULTILINE,
        )
        ranges = {}  # (open_pos, close_pos) -> class_name

        for m in pattern.finditer(clean):
            class_name = m.group(1)
            brace_pos = m.end() - 1  # { 의 위치

            # 이 { 에 매칭되는 블록 찾기
            for block in blocks:
                if block.open_pos == brace_pos:
                    ranges[(block.open_pos, block.close_pos)] = class_name
                    break

        return ranges

    def _get_class_at(self, pos: int, class_ranges) -> str | None:
        """주어진 위치가 어떤 class/struct 블록 안에 있는지 반환."""
        for (open_pos, close_pos), name in class_ranges.items():
            if open_pos < pos < close_pos:
                return name
        return None

    # ─── 4단계: 함수 정의 추출 ──────────────────────────────────

    def _find_function_definitions(self, clean, source, lines, blocks, class_ranges, functions):
        """함수 정의(본문 있음)를 추출."""
        # { 로 시작하는 블록 중 바로 앞에 함수 시그니처가 있는 것을 찾음
        for block in blocks:
            # 전처리기 블록 무시
            open_pos = block.open_pos

            # { 앞의 텍스트에서 함수 시그니처 탐색
            sig_info = self._extract_signature_before(clean, open_pos)
            if not sig_info:
                continue

            func_name, sig_start_pos = sig_info

            # 비함수 키워드 필터링
            if func_name in _NON_FUNC_KEYWORDS:
                continue

            # class/struct/enum/namespace 블록 필터링
            before_sig = clean[max(0, sig_start_pos - 50):sig_start_pos].strip()
            if re.search(r"\b(?:class|struct|enum|union|namespace)\s*$", before_sig):
                continue

            # 소속 클래스 판별
            class_name = self._get_class_at(open_pos, class_ranges)

            # :: 로 클래스 메서드 판별 (클래스 외부 정의)
            if "::" in func_name and not class_name:
                parts = func_name.rsplit("::", 1)
                class_name = parts[0]
                func_name = parts[1]

            # 라인 번호 계산
            sig_line = clean[:sig_start_pos].count("\n") + 1
            body_start_line = block.open_line + 1
            end_line = block.close_line

            # 원본 소스 텍스트
            source_text = "".join(lines[sig_line - 1 : end_line])

            # 본문 들여쓰기 감지
            body_indent = self._detect_indent(lines, body_start_line)

            # 기존 주석 확인
            has_comment = self._has_existing_comment(lines, body_start_line)

            # col_offset
            col_offset = 0
            if sig_line <= len(lines):
                sig_line_text = lines[sig_line - 1]
                col_offset = len(sig_line_text) - len(sig_line_text.lstrip())

            functions.append(FunctionInfo(
                name=func_name,
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

    def _extract_signature_before(self, clean: str, brace_pos: int) -> tuple[str, int] | None:
        """{ 바로 앞의 함수 시그니처에서 함수명과 시작 위치를 추출.

        Returns:
            (함수명, 시그니처 시작 위치) 또는 None
        """
        # { 앞에서 함수 파라미터의 닫는 ) 를 찾는다.
        # ) 와 { 사이에 올 수 있는 것들:
        #   - const, override, noexcept, final, volatile
        #   - 후행 반환 타입: -> Type
        #   - 이니셜라이저 리스트: : member(val), member2(val)
        #
        # 전략: { 부터 역추적하면서 이니셜라이저의 : 를 찾고,
        # : 앞의 ) 가 진짜 함수 파라미터의 ) 임.
        # : 가 없으면 가장 가까운 ) 를 사용.

        i = brace_pos - 1
        while i >= 0 and clean[i] in " \t\n\r":
            i -= 1

        if i < 0:
            return None

        # 이니셜라이저 리스트 감지: { 앞에서 ) 를 찾되,
        # 그 ) 와 { 사이에 ':' 가 있으면 이니셜라이저가 있는 것
        # → ':' 앞의 ) 를 찾아야 함
        between_start = i
        found_colon = False
        colon_pos = -1

        # { 와 가장 가까운 ) 사이의 텍스트에서 이니셜라이저 ':' 탐색
        scan = brace_pos - 1
        paren_depth = 0
        while scan >= 0:
            ch = clean[scan]
            if ch == ")":
                paren_depth += 1
            elif ch == "(":
                paren_depth -= 1
            elif ch == ":" and paren_depth == 0:
                # 이것이 이니셜라이저 ':' 인지 확인 (:: 가 아닌)
                if scan > 0 and clean[scan - 1] != ":":
                    if scan + 1 < len(clean) and clean[scan + 1] != ":":
                        found_colon = True
                        colon_pos = scan
                        break
            elif ch in ";{}":
                break
            scan -= 1

        if found_colon:
            # 이니셜라이저 ':' 앞의 ) 를 찾아야 함
            i = colon_pos - 1
            while i >= 0 and clean[i] in " \t\n\r":
                i -= 1
            # const/noexcept 등의 키워드 건너뛰기
            while i >= 0:
                # 현재 위치에서 끝나는 키워드 확인
                word_end = i + 1
                while i >= 0 and (clean[i].isalpha() or clean[i] == "_"):
                    i -= 1
                word = clean[i + 1:word_end]
                if word in ("const", "override", "noexcept", "final", "volatile"):
                    while i >= 0 and clean[i] in " \t\n\r":
                        i -= 1
                else:
                    i = word_end - 1
                    break
        else:
            # 이니셜라이저 없음 → { 직전에서 역추적
            i = brace_pos - 1
            while i >= 0 and clean[i] in " \t\n\r":
                i -= 1
            # 후행 반환타입 건너뛰기: -> Type
            i = self._skip_trailing_return_type(clean, i)
            # const/noexcept 등의 키워드 건너뛰기
            while i >= 0:
                word_end = i + 1
                while i >= 0 and (clean[i].isalpha() or clean[i] == "_"):
                    i -= 1
                word = clean[i + 1:word_end]
                if word in ("const", "override", "noexcept", "final", "volatile"):
                    while i >= 0 and clean[i] in " \t\n\r":
                        i -= 1
                else:
                    i = word_end - 1
                    break

        if i < 0 or clean[i] != ")":
            return None

        # 후행 반환타입이 ) 직전에 올 수도 있으므로 한번 더 체크
        # (이니셜라이저 경로에서는 이미 건너뛰지 않았으므로)

        # 괄호 매칭으로 ( 찾기
        paren_depth = 1
        i -= 1
        while i >= 0 and paren_depth > 0:
            if clean[i] == ")":
                paren_depth += 1
            elif clean[i] == "(":
                paren_depth -= 1
            i -= 1

        if paren_depth != 0:
            return None

        open_paren_pos = i + 1

        # ( 앞의 함수명 추출
        j = open_paren_pos - 1
        while j >= 0 and clean[j] in " \t\n\r":
            j -= 1

        if j < 0:
            return None

        # 함수명 끝 위치
        name_end = j + 1

        # 함수명 추출: 영문자, 숫자, _, :, ~ 허용
        while j >= 0 and (clean[j].isalnum() or clean[j] in "_:~"):
            j -= 1

        name_start = j + 1
        func_name = clean[name_start:name_end].strip()

        if not func_name or func_name.startswith("::"):
            return None

        # 시그니처 시작 위치: 반환 타입까지 역추적
        sig_start = name_start
        k = name_start - 1
        while k >= 0 and clean[k] in " \t\n\r":
            k -= 1

        # 반환 타입이 있는지 확인 (알파벳/*/& 으로 끝나야 함)
        if k >= 0 and (clean[k].isalnum() or clean[k] in "*&>_"):
            # 반환 타입 시작점까지 역추적
            while k >= 0 and (clean[k].isalnum() or clean[k] in "*&<>:_, \t"):
                k -= 1
            sig_start = k + 1

        # template<...> 까지 포함
        temp_check = clean[max(0, sig_start - 30):sig_start].rstrip()
        if temp_check.endswith(">"):
            t = sig_start - 1
            while t >= 0 and clean[t] in " \t\n\r":
                t -= 1
            if t >= 0 and clean[t] == ">":
                depth = 1
                t -= 1
                while t >= 0 and depth > 0:
                    if clean[t] == ">":
                        depth += 1
                    elif clean[t] == "<":
                        depth -= 1
                    t -= 1
                # template 키워드 확인
                temp_word = clean[max(0, t - 8):t + 1].strip()
                if "template" in temp_word:
                    sig_start = t + 1 - len(temp_word) + temp_word.index("template")

        return func_name, sig_start

    # ─── 함수 선언(프로토타입) 추출 ─────────────────────────────

    def _find_function_declarations(self, clean, source, lines, class_ranges, functions):
        """함수 선언(; 으로 끝나는 프로토타입)을 추출."""
        # 이미 정의로 추출된 함수의 라인 범위
        defined_ranges = set()
        for f in functions:
            for ln in range(f.lineno, f.end_lineno + 1):
                defined_ranges.add(ln)

        # 패턴: 반환타입 함수명(파라미터) [const] [= 0] ;
        pattern = re.compile(
            r"""
            (?:^|[;{}])                     # 시작 경계
            \s*
            (                               # 그룹1: 전체 선언
                (?:[\w:*&<>\[\]\s,]+\s+)?   # 반환 타입
                (~?\w[\w:]*)                # 그룹2: 함수명
                \s*
                \([^)]*\)                   # 파라미터
                \s*
                (?:const\s*)?               # 선택: const
                (?:=\s*0\s*)?               # 선택: = 0 (순수 가상)
                (?:override\s*)?            # 선택: override
                (?:noexcept\s*)?            # 선택: noexcept
            )
            \s*;                            # 세미콜론으로 끝남
            """,
            re.VERBOSE | re.MULTILINE,
        )

        for m in pattern.finditer(clean):
            func_name = m.group(2)
            if not func_name or func_name in _NON_FUNC_KEYWORDS:
                continue

            # 변수 선언과 구분: 반환 타입이 있어야 함
            full = m.group(1).strip()
            # 함수명만 있으면 (반환 타입 없으면) 변수일 가능성 → 스킵
            before_name = full[:full.find(func_name)].strip()
            if not before_name:
                continue

            # typedef 안의 함수 포인터 스킵
            line_start = clean.rfind("\n", 0, m.start()) + 1
            line_prefix = clean[line_start:m.start()].strip()
            if "typedef" in line_prefix:
                continue

            pos = m.start()
            lineno = clean[:pos].count("\n") + 1
            end_lineno = clean[:m.end()].count("\n") + 1

            # 이미 정의로 추출된 범위 안이면 스킵
            if lineno in defined_ranges:
                continue

            source_text = "".join(lines[lineno - 1 : end_lineno])
            class_name = self._get_class_at(pos, class_ranges)

            col_offset = 0
            if lineno <= len(lines):
                lt = lines[lineno - 1]
                col_offset = len(lt) - len(lt.lstrip())

            functions.append(FunctionInfo(
                name=func_name,
                source_text=source_text,
                lineno=lineno,
                end_lineno=end_lineno,
                body_start_lineno=None,
                col_offset=col_offset,
                body_indent="",
                is_method=class_name is not None,
                class_name=class_name,
                has_existing_docstring=False,
                language="c",
                is_declaration_only=True,
            ))

    # ─── 유틸리티 ───────────────────────────────────────────────

    def _skip_trailing_return_type(self, clean: str, i: int) -> int:
        """후행 반환타입 `-> Type` 을 역추적하여 건너뛴다.

        예: `auto foo(int x) -> int {` 에서 i가 `int`의 `t`를 가리킬 때,
        `->` 를 찾아 그 앞의 `)` 위치를 반환한다.
        """
        # { 이전 같은 줄/근처에서 -> 패턴을 역방향 검색
        # i 부터 뒤로 최대 200자까지 -> 를 찾음
        search_start = max(0, i - 200)
        segment = clean[search_start:i + 1]

        # 가장 마지막 -> 를 찾음
        arrow_pos = segment.rfind("->")
        if arrow_pos == -1:
            return i

        abs_arrow = search_start + arrow_pos

        # -> 와 i 사이에 ; { } 가 없어야 함 (같은 문맥인지 확인)
        between = clean[abs_arrow + 2:i + 1]
        if any(ch in between for ch in ";{}"):
            return i

        # -> 앞으로 이동
        j = abs_arrow - 1
        while j >= 0 and clean[j] in " \t\n\r":
            j -= 1

        return j

    def _detect_indent(self, lines, lineno) -> str:
        if 1 <= lineno <= len(lines):
            line = lines[lineno - 1]
            stripped = line.lstrip()
            if stripped:
                return line[: len(line) - len(stripped)]
        return "    "

    def _has_existing_comment(self, lines, body_start_lineno) -> bool:
        if 1 <= body_start_lineno <= len(lines):
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
