"""파서 레지스트리 — 확장자별 파서 자동 매핑"""

from parsers.base import BaseParser
from parsers.python_parser import PythonParser
from parsers.c_parser import CParser
from parsers.java_parser import JavaParser
from parsers.js_parser import JSParser

# 확장자 → 파서 인스턴스 매핑
_REGISTRY: dict[str, BaseParser] = {}


def _register(parser: BaseParser):
    for ext in parser.file_extensions:
        _REGISTRY[ext] = parser


# 파서 등록
_register(PythonParser())
_register(CParser())
_register(JavaParser())
_register(JSParser())


def get_parser(file_extension: str) -> BaseParser | None:
    """확장자에 맞는 파서 반환. 미지원 확장자면 None."""
    return _REGISTRY.get(file_extension.lower())


def supported_extensions() -> list[str]:
    """지원되는 모든 확장자 목록"""
    return list(_REGISTRY.keys())
