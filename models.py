"""데이터 모델 정의"""

from dataclasses import dataclass, field


@dataclass
class FunctionInfo:
    """추출된 함수 정보"""
    name: str
    source_text: str
    lineno: int                        # def/함수선언 라인 (1-based)
    end_lineno: int                    # 함수 마지막 라인
    body_start_lineno: int | None      # 본문 첫 라인 (None이면 본문 없음)
    col_offset: int                    # 키워드 들여쓰기
    body_indent: str                   # 본문 들여쓰기 문자열
    is_method: bool = False
    is_async: bool = False
    class_name: str | None = None
    decorators: list[str] = field(default_factory=list)
    has_existing_docstring: bool = False
    language: str = "python"
    is_declaration_only: bool = False


@dataclass
class CommentResult:
    """생성된 주석 정보"""
    function_name: str
    comment_lines: list[str]           # 삽입할 주석 라인들 (들여쓰기 포함)
    insert_lineno: int                 # 삽입 위치 (1-based)
    replace_end_lineno: int | None = None  # 기존 주석 교체 시 끝 라인


@dataclass
class FileResult:
    """파일 처리 결과"""
    source_path: str
    dest_path: str
    functions_found: int = 0
    functions_commented: int = 0
    functions_skipped: int = 0
    errors: list[str] = field(default_factory=list)
