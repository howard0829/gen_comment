"""gen_comment — LLM 기반 함수 주석 자동 생성기"""

import argparse
import logging
import sys
from pathlib import Path

from config import DEFAULT_MODEL, DEFAULT_OLLAMA_URL, DEFAULT_OUTPUT_DIR, DEFAULT_WORKERS
from llm_client import OllamaClient
from processor import Processor


def main():
    parser = argparse.ArgumentParser(
        description="코드 파일의 모든 함수에 LLM으로 구조화된 주석을 자동 생성합니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
예시:
  python main.py ./src                          # src 폴더 전체 처리
  python main.py ./src/auth.py -o commented/    # 단일 파일, 출력 폴더 지정
  python main.py ./src --dry-run                # 함수 목록만 출력
  python main.py ./src --lang python,java       # Python, Java만 처리
  python main.py ./src --overwrite              # 기존 docstring도 재생성
""",
    )

    parser.add_argument("path", help="처리할 디렉토리 또는 파일 경로")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT_DIR, help=f"출력 디렉토리 (기본: {DEFAULT_OUTPUT_DIR}/)")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL, help=f"Ollama 모델 (기본: {DEFAULT_MODEL})")
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL, help=f"Ollama URL (기본: {DEFAULT_OLLAMA_URL})")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"파일 내 병렬 LLM 호출 수 (기본: {DEFAULT_WORKERS})")
    parser.add_argument("--overwrite", action="store_true", help="기존 docstring/주석도 재생성")
    parser.add_argument("--include-declarations", action="store_true", help="본문 없는 함수 선언에도 주석 생성")
    parser.add_argument("--lang", default=None, help="처리할 언어 제한 (예: python,c,java)")
    parser.add_argument("--dry-run", action="store_true", help="함수 목록만 출력, LLM 미호출")
    parser.add_argument("-v", "--verbose", action="store_true", help="상세 로그 출력")

    args = parser.parse_args()

    # 로깅 설정
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    # 경로 확인
    target_path = Path(args.path)
    if not target_path.exists():
        print(f"오류: 경로가 존재하지 않습니다: {args.path}", file=sys.stderr)
        sys.exit(1)

    # 언어 필터
    allowed_languages = None
    if args.lang:
        allowed_languages = {lang.strip().lower() for lang in args.lang.split(",")}

    # LLM 연결 확인 (dry-run이 아닐 때만)
    llm = OllamaClient(base_url=args.ollama_url, model=args.model)
    if not args.dry_run:
        ok, msg = llm.check_connection()
        if not ok:
            print(f"오류: {msg}", file=sys.stderr)
            sys.exit(1)
        logging.info("Ollama %s", msg)

    # 처리 실행
    proc = Processor(
        root_path=str(target_path),
        output_dir=args.output,
        llm=llm,
        workers=args.workers,
        overwrite=args.overwrite,
        include_declarations=args.include_declarations,
        allowed_languages=allowed_languages,
        dry_run=args.dry_run,
    )

    results = proc.run()

    # 요약 리포트
    _print_summary(results, args.output, args.dry_run)


def _print_summary(results, output_dir, dry_run):
    if not results:
        print("\n처리된 파일이 없습니다.")
        return

    total_files = len(results)
    total_found = sum(r.functions_found for r in results)
    total_commented = sum(r.functions_commented for r in results)
    total_skipped = sum(r.functions_skipped for r in results)
    total_errors = sum(len(r.errors) for r in results)

    mode = "[DRY-RUN] " if dry_run else ""
    print(f"\n{'=' * 50}")
    print(f"{mode}처리 완료: {total_files}개 파일, {total_found}개 함수 발견")
    if not dry_run:
        print(f"  주석 생성: {total_commented} | 스킵: {total_skipped} | 오류: {total_errors}")
        print(f"  결과 경로: {Path(output_dir).resolve()}/")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
