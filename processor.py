"""오케스트레이터 — 디렉토리 순회, 파싱, LLM 호출, 주석 삽입 통합"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    import chardet
except ImportError:
    chardet = None

from comment_inserter import insert_comments
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

        if self.root_path.is_file():
            files = [self.root_path]
        else:
            files = sorted(self._discover_files())

        if not files:
            logger.info("처리할 파일이 없습니다.")
            return results

        logger.info("발견된 파일: %d개", len(files))

        # 진행률 모니터 초기화 (dry-run이 아닐 때만)
        self.monitor = ProgressMonitor(
            total_files=len(files),
            enabled=not self.dry_run,
        )

        for file_path in files:
            result = self._process_file(file_path)
            if result:
                results.append(result)

        if self.monitor:
            self.monitor.finish()

        return results

    def _discover_files(self):
        for ext in self.allowed_extensions:
            pattern = f"*{ext}"
            yield from self.root_path.rglob(pattern)

    def _read_file(self, file_path: Path) -> tuple[str | None, str]:
        """파일을 읽어 (소스 텍스트, 감지된 인코딩)을 반환한다.

        UTF-8 → chardet 감지 → 일반적 인코딩 순으로 시도.
        모두 실패하면 (None, "") 반환.
        """
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
                    logger.info("인코딩 감지: %s → %s (신뢰도: %.0f%%)", file_path.name, enc, conf * 100)
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

    def _process_file(self, file_path: Path) -> FileResult | None:
        ext = file_path.suffix.lower()
        parser = get_parser(ext)
        if not parser:
            if self.monitor:
                self.monitor.skip_file(file_path.name, 0)
            return None

        # 파일 읽기 (인코딩 자동 감지)
        source, detected_encoding = self._read_file(file_path)
        if source is None:
            if self.monitor:
                self.monitor.skip_file(file_path.name, 0)
            return None

        # 함수 추출
        functions = parser.extract_functions(str(file_path), source)
        if not functions:
            if self.monitor:
                self.monitor.skip_file(file_path.name, 0)
            return None

        # 출력 경로 계산
        if self.root_path.is_file():
            rel_path = file_path.name
        else:
            rel_path = file_path.relative_to(self.root_path)
        dest_path = self.output_dir / rel_path

        result = FileResult(
            source_path=str(file_path),
            dest_path=str(dest_path),
            functions_found=len(functions),
        )

        # 처리 대상 필터링
        targets = self._filter_targets(functions)

        if not targets:
            result.functions_skipped = len(functions)
            if self.dry_run:
                self._print_dry_run(file_path, functions, targets)
            elif self.monitor:
                self.monitor.skip_file(file_path.name, len(functions))
            return result

        if self.dry_run:
            self._print_dry_run(file_path, functions, targets)
            return result

        # 모니터에 파일 시작 알림
        skipped_in_file = len(functions) - len(targets)
        if self.monitor:
            self.monitor.start_file(file_path.name, len(targets))
            # 필터링된 함수는 즉시 skip 처리
            if skipped_in_file > 0:
                self.monitor.add_skipped(skipped_in_file)

        # LLM 호출 + 주석 생성
        comment_results = self._generate_comments(targets, parser, file_path)

        result.functions_commented = len(comment_results)
        result.functions_skipped = len(functions) - len(comment_results)

        # 파일 처리 완료 → 파일 바 진행
        if self.monitor:
            self.monitor.finish_file()

        if not comment_results:
            return result

        # 주석 삽입
        original_lines = source.splitlines(keepends=True)
        if original_lines and not original_lines[-1].endswith("\n"):
            original_lines[-1] += "\n"

        new_lines = insert_comments(original_lines, comment_results)

        # 결과 파일 저장
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text("".join(new_lines), encoding="utf-8")
        logger.debug("저장: %s (%d개 함수)", dest_path, len(comment_results))

        return result

    def _filter_targets(self, functions: list[FunctionInfo]) -> list[FunctionInfo]:
        targets = []
        for func in functions:
            if func.is_declaration_only and not self.include_declarations:
                continue
            if func.has_existing_docstring and not self.overwrite:
                continue
            targets.append(func)
        return targets

    def _generate_comments(
        self,
        targets: list[FunctionInfo],
        parser,
        file_path: Path,
    ) -> list[CommentResult]:
        comment_results = []

        def process_one(func: FunctionInfo) -> CommentResult | None:
            if self.monitor:
                self.monitor.start_function(func.name)

            sys_prompt = get_system_prompt(func)
            user_prompt = build_user_prompt(func)
            raw = self.llm.generate_comment(sys_prompt, user_prompt)

            if not raw:
                if self.monitor:
                    self.monitor.finish_function(func.name, "error")
                return None

            parsed = parse_llm_response(raw)
            if not parsed:
                if self.monitor:
                    self.monitor.finish_function(func.name, "error")
                return None

            comment_lines = parser.format_comment(parsed, func.body_indent)

            if func.is_declaration_only:
                insert_lineno = func.lineno
            elif func.body_start_lineno:
                insert_lineno = func.body_start_lineno
            else:
                if self.monitor:
                    self.monitor.finish_function(func.name, "error")
                return None

            replace_end = None
            if func.has_existing_docstring and self.overwrite and func.body_start_lineno:
                replace_end = self._find_docstring_end(file_path, func)

            if self.monitor:
                self.monitor.finish_function(func.name, "success")

            return CommentResult(
                function_name=func.name,
                comment_lines=comment_lines,
                insert_lineno=insert_lineno,
                replace_end_lineno=replace_end,
            )

        if self.workers <= 1 or len(targets) <= 1:
            for func in targets:
                result = process_one(func)
                if result:
                    comment_results.append(result)
        else:
            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                futures = {executor.submit(process_one, func): func for func in targets}
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        if result:
                            comment_results.append(result)
                    except Exception as e:
                        func = futures[future]
                        logger.error("함수 '%s' 처리 실패: %s", func.name, e)
                        if self.monitor:
                            self.monitor.finish_function(func.name, "error")

        return comment_results

    def _find_docstring_end(self, file_path: Path, func: FunctionInfo) -> int | None:
        """기존 docstring의 끝 라인을 찾는다 (Python 전용)."""
        if func.language != "python" or not func.body_start_lineno:
            return None

        try:
            source = file_path.read_text(encoding="utf-8")
        except Exception:
            return None

        lines = source.splitlines()
        start_idx = func.body_start_lineno - 1

        if start_idx >= len(lines):
            return None

        first_line = lines[start_idx].strip()

        for quote in ('"""', "'''"):
            if quote in first_line:
                rest = first_line.split(quote, 1)[1]
                if quote in rest:
                    return func.body_start_lineno
                for i in range(start_idx + 1, min(start_idx + 200, len(lines))):
                    if quote in lines[i]:
                        return i + 1
                break

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
