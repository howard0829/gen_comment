"""주석 삽입 모듈 — bottom-up 삽입 + 대형 파일 청크 기반 쓰기"""

from config import LARGE_FILE_THRESHOLD
from models import CommentResult


def insert_comments(original_lines: list[str], comments: list[CommentResult]) -> list[str]:
    """원본 라인 리스트에 주석을 삽입하여 새 라인 리스트를 반환한다.

    파일 크기에 따라 전략을 분기한다:
    - 1만줄 이하: bottom-up 리스트 삽입 (단순)
    - 1만줄 초과: 오름차순 단일 패스 (O(n) 스트리밍)
    """
    if not comments:
        return list(original_lines)

    if len(original_lines) <= LARGE_FILE_THRESHOLD:
        return _insert_bottom_up(original_lines, comments)
    else:
        return _insert_streaming(original_lines, comments)


def _insert_bottom_up(original_lines: list[str], comments: list[CommentResult]) -> list[str]:
    """Bottom-up 삽입 — 뒤쪽 함수부터 처리하여 라인 번호 시프트 방지"""
    lines = list(original_lines)

    # insert_lineno 기준 내림차순 정렬
    sorted_comments = sorted(comments, key=lambda c: c.insert_lineno, reverse=True)

    for comment in sorted_comments:
        idx = comment.insert_lineno - 1  # 0-based

        if comment.replace_end_lineno is not None:
            # 기존 주석 교체: 해당 범위 제거 후 삽입
            replace_end_idx = comment.replace_end_lineno  # 1-based → 0-based exclusive
            del lines[idx:replace_end_idx]

        # 주석 라인 삽입
        for i, line in enumerate(comment.comment_lines):
            lines.insert(idx + i, line)

    return lines


def _insert_streaming(original_lines: list[str], comments: list[CommentResult]) -> list[str]:
    """오름차순 단일 패스 — 대형 파일용 O(n) 처리"""
    # insert_lineno 기준 오름차순 정렬
    sorted_comments = sorted(comments, key=lambda c: c.insert_lineno)

    result = []
    comment_idx = 0
    line_num = 1  # 1-based

    # 교체 범위를 빠르게 조회하기 위한 매핑
    replace_ranges = {}
    for c in sorted_comments:
        if c.replace_end_lineno is not None:
            for ln in range(c.insert_lineno, c.replace_end_lineno + 1):
                replace_ranges[ln] = c.insert_lineno  # 이 범위의 시작 라인 가리킴

    skip_until = 0  # 교체 범위 스킵용

    for line in original_lines:
        # 현재 라인이 교체 범위 안이면 스킵
        if line_num <= skip_until:
            line_num += 1
            continue

        # 삽입 포인트 도달 확인
        while (
            comment_idx < len(sorted_comments)
            and sorted_comments[comment_idx].insert_lineno == line_num
        ):
            comment = sorted_comments[comment_idx]

            # 교체 모드면 기존 범위 스킵 설정
            if comment.replace_end_lineno is not None:
                skip_until = comment.replace_end_lineno

            # 주석 라인 삽입
            result.extend(comment.comment_lines)
            comment_idx += 1

        # 스킵 범위가 아니면 원본 라인 추가
        if line_num > skip_until:
            result.append(line)

        line_num += 1

    return result
