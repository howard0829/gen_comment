"""오케스트레이터 — 전체 복사 후 함수 단위 주석 삽입

작업 흐름:
1. 모든 파일을 result/ 폴더에 복사
2. result/ 내 파일에서 함수를 추출
3. 각 함수를 LLM에 보내 주석 생성
4. 주석이 생성되면 result/ 파일에서 해당 영역을 즉시 교체
"""

import logging
import shutil
from pathlib import Path

try:
    import chardet
except ImportError:
    chardet = None

from llm_client import OllamaClient
from models import CommentResult, FileResult, FunctionInfo
from parsers import get_parser, supported_extensions
from progress import ProgressMonitor
from prompt import build_user_prompt, get_system_prompt, parse_llm_response

logger = logging.getLogger(__name__)


class Processor:
    def __init__(
        self,
        root_path: str,
        output_dir: str,
        llm: OllamaClient,
        workers: int = 3,
        overwrite: bool = False,
        include_declarations: bool = False,
        allowed_languages: set[str] | None = None,
        dry_run: bool = False,
    ):
        self.root_path = Path(root_path).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.llm = llm
        self.workers = workers
        self.overwrite = overwrite
        self.include_declarations = include_declarations
        self.allowed_languages = allowed_languages
        self.dry_run = dry_run

        # 허용 확장자 필터
        self.allowed_extensions = set()
        if allowed_languages:
            from config import LANGUAGE_EXTENSIONS
            for lang in allowed_languages:
                for ext in LANGUAGE_EXTENSIONS.get(lang, []):
                    self.allowed_extensions.add(ext)
        else:
            self.allowed_extensions = set(supported_extensions())

        self.monitor: ProgressMonitor | None = None

    def run(self) -> list[FileResult]:
        results = []

        # ── 1단계: 모든 파일을 result/ 폴더에 복사 ──
        if not self.dry_run:
            self._copy_to_output()

        # 처리 대상 파일 탐색
        if self.dry_run:
            # dry-run: 원본에서 탐색
            if self.root_path.is_file():
                scan_files = [self.root_path]
            else:
                scan_files = sorted(self._discover_source_files())
        else:
            # 실제 실행: result/ 폴더에서 탐색
            if self.root_path.is_file():
                rel = self.root_path.name
                scan_files = [self.output_dir / rel]
            else:
                scan_files = sorted(self._discover_result_files())

        if not scan_files:
            logger.info("처리할 파일이 없습니다.")
            return results

        logger.info("발견된 파일: %d개", len(scan_files))

        # ── 2단계: 전체 파일 스캔 (함수 추출 + 필터링) ──
        scan_results = []  # (result_path, parser, functions, targets)
        total_targets = 0
        total_skipped = 0

        for result_path in scan_files:
            ext = result_path.suffix.lower()
            parser = get_parser(ext)
            if not parser:
                continue

            source, _ = self._read_file(result_path)
            if source is None:
                continue

            functions = parser.extract_functions(str(result_path), source)
            if not functions:
                continue

            targets = self._filter_targets(functions)

            if self.dry_run:
                self._print_dry_run(result_path, functions, targets)
                results.append(FileResult(
                    source_path=str(result_path),
                    dest_path=str(result_path),
                    functions_found=len(functions),
                    functions_skipped=len(functions) - len(targets),
                ))
                continue

            skipped_in_file = len(functions) - len(targets)
            total_skipped += skipped_in_file
            total_targets += len(targets)

            if targets:
                scan_results.append((result_path, parser, functions, targets))
            else:
                results.append(FileResult(
                    source_path=str(result_path),
                    dest_path=str(result_path),
                    functions_found=len(functions),
                    functions_skipped=len(functions),
                ))

        if self.dry_run:
            return results

        if not scan_results:
            logger.info("처리할 함수가 없습니다.")
            return results

        logger.info("처리 대상: %d개 파일, %d개 함수 (스킵: %d개)",
                     len(scan_results), total_targets, total_skipped)

        # ── 3단계: 진행률 모니터 초기화 후 함수 단위 처리 ──
        self.monitor = ProgressMonitor(
            total_files=len(scan_results),
            total_functions=total_targets,
            enabled=True,
        )
        self.monitor.add_skipped(total_skipped)

        for result_path, parser, functions, targets in scan_results:
            result = self._process_file(result_path, parser, functions, targets)
            results.append(result)

        self.monitor.finish()
        return results

    # ─── 파일 복사 ──────────────────────────────────────────────

    def _copy_to_output(self):
        """원본 파일/디렉토리를 result/ 폴더에 복사한다."""
        if self.dry_run:
            return

        if self.root_path.is_file():
            dest = self.output_dir / self.root_path.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.root_path, dest)
            logger.info("파일 복사: %s → %s", self.root_path, dest)
        else:
            if self.output_dir.exists():
                shutil.rmtree(self.output_dir)
            shutil.copytree(self.root_path, self.output_dir)
            logger.info("디렉토리 복사: %s → %s", self.root_path, self.output_dir)

    def _discover_source_files(self):
        """원본 디렉토리에서 처리 대상 파일을 탐색한다."""
        for ext in self.allowed_extensions:
            pattern = f"*{ext}"
            yield from self.root_path.rglob(pattern)

    def _discover_result_files(self):
        """result/ 폴더 내에서 처리 대상 파일을 탐색한다."""
        for ext in self.allowed_extensions:
            pattern = f"*{ext}"
            yield from self.output_dir.rglob(pattern)

    # ─── 파일 읽기 ──────────────────────────────────────────────

    def _read_file(self, file_path: Path) -> tuple[str | None, str]:
        """파일을 읽어 (소스 텍스트, 감지된 인코딩)을 반환한다."""
        # 1차: UTF-8 시도
        try:
            source = file_path.read_text(encoding="utf-8")
            return source, "utf-8"
        except UnicodeDecodeError:
            pass

        # 바이너리 읽기
        try:
            raw = file_path.read_bytes()
        except Exception as e:
            logger.warning("파일 읽기 실패: %s (%s)", file_path, e)
            return None, ""

        # 2차: chardet 인코딩 감지
        if chardet is not None:
            detected = chardet.detect(raw)
            enc = detected.get("encoding")
            conf = detected.get("confidence", 0)
            if enc and conf > 0.5:
                try:
                    source = raw.decode(enc)
                    logger.info("인코딩 감지: %s → %s (신뢰도: %.0f%%)",
                                file_path.name, enc, conf * 100)
                    return source, enc
                except (UnicodeDecodeError, LookupError):
                    pass

        # 3차: 일반적 인코딩 폴백
        for enc in ("euc-kr", "cp949", "latin-1", "shift_jis", "gb2312"):
            try:
                source = raw.decode(enc)
                logger.info("폴백 인코딩: %s → %s", file_path.name, enc)
                return source, enc
            except (UnicodeDecodeError, LookupError):
                continue

        logger.warning("인코딩 감지 실패, 스킵: %s", file_path)
        return None, ""

    # ─── 파일 처리 (함수 단위 교체) ─────────────────────────────

    def _process_file(
        self,
        result_path: Path,
        parser,
        functions: list[FunctionInfo],
        targets: list[FunctionInfo],
    ) -> FileResult:
        result = FileResult(
            source_path=str(result_path),
            dest_path=str(result_path),
            functions_found=len(functions),
        )

        self.monitor.start_file(result_path.name, len(targets))

        # 함수를 라인 번호 내림차순으로 정렬 (bottom-up 교체로 라인 시프트 방지)
        sorted_targets = sorted(targets, key=lambda f: f.lineno, reverse=True)

        commented = 0
        for func in sorted_targets:
            success = self._process_one_function(result_path, parser, func)
            if success:
                commented += 1

        result.functions_commented = commented
        result.functions_skipped = len(functions) - commented

        self.monitor.finish_file()
        return result

    def _process_one_function(
        self,
        result_path: Path,
        parser,
        func: FunctionInfo,
    ) -> bool:
        """함수 하나를 LLM으로 주석 생성 후, result 파일에서 해당 영역을 교체한다."""
        self.monitor.start_function(func.name)

        # LLM 호출
        sys_prompt = get_system_prompt(func)
        user_prompt = build_user_prompt(func)
        raw = self.llm.generate_comment(sys_prompt, user_prompt)

        if not raw:
            self.monitor.finish_function(func.name, "error")
            return False

        parsed = parse_llm_response(raw)
        if not parsed:
            self.monitor.finish_function(func.name, "error")
            return False

        # 삽입 위치 결정 + 주석 포맷
        if func.language == "c":
            # C: 함수 시그니처 앞에 블록 주석 삽입 (Doxygen 관례)
            indent = " " * func.col_offset
            comment_lines = parser.format_comment(parsed, indent)
            insert_lineno = func.lineno
        elif func.is_declaration_only:
            comment_lines = parser.format_comment(parsed, func.body_indent)
            insert_lineno = func.lineno
        elif func.body_start_lineno:
            comment_lines = parser.format_comment(parsed, func.body_indent)
            insert_lineno = func.body_start_lineno
        else:
            self.monitor.finish_function(func.name, "error")
            return False

        # result 파일을 읽어서 해당 위치에 주석 삽입 후 저장
        source, _ = self._read_file(result_path)
        if source is None:
            self.monitor.finish_function(func.name, "error")
            return False

        lines = source.splitlines(keepends=True)
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"

        idx = insert_lineno - 1  # 0-based

        # 기존 주석 교체 (--overwrite 시)
        if func.has_existing_docstring and self.overwrite:
            if func.language == "c":
                # C: 함수 위 doc-comment 제거 (/** ... */ 블록)
                del_start = self._find_doc_comment_range(lines, idx)
                if del_start is not None:
                    del lines[del_start:idx]
                    idx = del_start
            elif func.language == "python" and func.body_start_lineno:
                end = self._find_docstring_end_lineno(lines, func.body_start_lineno)
                if end is not None:
                    del lines[idx:end]

        # 주석 삽입
        for i, line in enumerate(comment_lines):
            lines.insert(idx + i, line)

        # 파일 저장
        result_path.write_text("".join(lines), encoding="utf-8")

        self.monitor.finish_function(func.name, "success")
        return True

    # ─── 유틸리티 ───────────────────────────────────────────────

    def _filter_targets(self, functions: list[FunctionInfo]) -> list[FunctionInfo]:
        targets = []
        for func in functions:
            if func.is_declaration_only and not self.include_declarations:
                continue
            if func.has_existing_docstring and not self.overwrite:
                continue
            targets.append(func)
        return targets

    def _find_docstring_end_lineno(self, lines: list[str], body_start_lineno: int) -> int | None:
        """Python docstring의 끝 라인 인덱스를 반환 (0-based exclusive)."""
        start_idx = body_start_lineno - 1
        if start_idx >= len(lines):
            return None

        first_line = lines[start_idx].strip()
        for quote in ('"""', "'''"):
            if quote in first_line:
                rest = first_line.split(quote, 1)[1]
                if quote in rest:
                    return start_idx + 1
                for i in range(start_idx + 1, min(start_idx + 200, len(lines))):
                    if quote in lines[i]:
                        return i + 1
                break
        return None

    def _find_doc_comment_range(self, lines: list[str], func_idx: int) -> int | None:
        """함수 시그니처(func_idx, 0-based) 위의 doc-comment 시작 인덱스를 반환.

        /** ... */ 또는 /* ... */ 블록 주석을 역추적.
        """
        check = func_idx - 1
        # 빈 줄 건너뛰기
        while check >= 0 and not lines[check].strip():
            check -= 1
        if check < 0:
            return None

        # */ 로 끝나는지 확인
        if not lines[check].strip().endswith("*/"):
            return None

        # /* 시작점 역추적
        end_idx = check + 1
        while check >= 0:
            if "/*" in lines[check]:
                return check  # doc-comment 시작 (0-based)
            check -= 1

        return None

    def _print_dry_run(self, file_path: Path, functions: list[FunctionInfo], targets: list[FunctionInfo]):
        print(f"\n📄 {file_path}")
        for func in functions:
            is_target = func in targets
            marker = "→" if is_target else "  (skip)"
            kind = "method" if func.is_method else "function"
            decl = " [declaration]" if func.is_declaration_only else ""
            doc = " [has docstring]" if func.has_existing_docstring else ""
            cls = f"{func.class_name}." if func.class_name else ""
            print(f"  {marker} {kind} {cls}{func.name} (L{func.lineno}-{func.end_lineno}){decl}{doc}")
