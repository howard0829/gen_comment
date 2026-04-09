"""파서 추상 베이스 클래스"""

from abc import ABC, abstractmethod

from models import FunctionInfo


class BaseParser(ABC):
    """언어별 파서의 공통 인터페이스"""

    file_extensions: list[str] = []

    @abstractmethod
    def extract_functions(self, file_path: str, source: str) -> list[FunctionInfo]:
        """소스 코드에서 모든 함수/메서드를 추출한다."""
        ...

    @abstractmethod
    def format_comment(self, raw_comment: str, indent: str) -> list[str]:
        """LLM 응답을 언어에 맞는 주석 라인 리스트로 변환한다."""
        ...
